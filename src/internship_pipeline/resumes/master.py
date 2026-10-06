"""Saved-profile master PDFs, compiled by the existing durable worker queue."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import stat
import time
from typing import Any

from pypdf import PdfReader

from internship_pipeline.models import Settings, utcnow
from internship_pipeline.profile_settings import ProfileSettings, Snapshot
from internship_pipeline.queue import Queue, Task
from internship_pipeline.resumes.errors import ResumeMatcherError
from internship_pipeline.resumes.latex import LatexCompiler
from internship_pipeline.resumes.master_template import (
    MAX_PAGES,
    TEMPLATE_REVISION,
    MasterDocument,
    comparable,
    render_master,
)
from internship_pipeline.resumes.validation import ResumeValidationError, validate_pdf
from internship_pipeline.storage import Store, enqueue


class MasterConflict(ValueError):
    pass


def validate_master_pdf(content: bytes, snapshot: Snapshot, document: MasterDocument) -> int:
    candidate = snapshot.candidate().model_copy(update={"max_resume_pages": MAX_PAGES})
    report = validate_pdf(content, candidate, {})
    if report.warnings:
        raise ResumeValidationError("Text extends outside the page. Shorten saved facts and retry.")
    reader = PdfReader(io.BytesIO(content), strict=True)
    text = comparable("\n".join(page.extract_text() or "" for page in reader.pages))
    if any(comparable(value) not in text for value in document.required_text):
        raise ResumeValidationError(
            "The PDF omitted saved factual text. Review unsupported characters or shorten facts."
        )
    return len(reader.pages)


class MasterResumes:
    def __init__(self, store: Store, settings: Settings, *, compiler: LatexCompiler | None = None):
        self.store = store
        self.settings = settings
        self.profiles = ProfileSettings(store)
        self.queue = Queue(store, settings.lease_seconds, settings.max_attempts)
        self.compiler = compiler or LatexCompiler()
        self.root = settings.artifact_dir / "master"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise ValueError("Master artifact directory must not be a symbolic link")
        self.root.chmod(0o700)
        with store.connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS master_resumes (
                    key TEXT PRIMARY KEY,
                    profile_revision INTEGER NOT NULL
                        REFERENCES profile_settings_revisions(revision),
                    template_revision TEXT NOT NULL, created_at TEXT NOT NULL,
                    completed_at TEXT, filename TEXT, sha256 TEXT, pages INTEGER, manifest TEXT
                );
            """)

    @staticmethod
    def key(revision: int) -> str:
        return hashlib.sha256(f"master:{revision}:{TEMPLATE_REVISION}".encode()).hexdigest()

    def request(self, expected_revision: int) -> dict[str, Any]:
        snapshot = self.profiles.read()
        if snapshot.revision != expected_revision:
            raise MasterConflict("Your saved profile changed. Reload Settings and generate again.")
        render_master(snapshot)  # Fail before queueing invalid/empty profiles.
        key = self.key(snapshot.revision)
        cached = self.status(key)
        cache_invalid = False
        if cached["state"] == "ready":
            try:
                self.pdf(key)
            except (OSError, ValueError):
                cache_invalid = True
        now = utcnow()
        with self.store.transaction() as connection:
            if self._revision(connection) != snapshot.revision:
                raise MasterConflict(
                    "Your saved profile changed. Reload Settings and generate again."
                )
            connection.execute(
                "INSERT OR IGNORE INTO master_resumes"
                "(key,profile_revision,template_revision,created_at) "
                "VALUES(?,?,?,?)",
                (key, snapshot.revision, TEMPLATE_REVISION, now.isoformat()),
            )
            enqueue(
                connection,
                "master_resume",
                "master:" + key,
                {
                    "key": key,
                    "profile_revision": snapshot.revision,
                    "template_revision": TEMPLATE_REVISION,
                },
                now.timestamp(),
            )
            if cache_invalid:
                connection.execute(
                    "UPDATE master_resumes SET filename=NULL,sha256=NULL,pages=NULL,"
                    "manifest=NULL,completed_at=NULL WHERE key=?",
                    (key,),
                )
                connection.execute(
                    "UPDATE tasks SET status='failed' WHERE key=? AND status='done'",
                    ("master:" + key,),
                )
            # A deliberate retry is bounded by the same single unique task.
            connection.execute(
                "UPDATE tasks SET status='pending',attempts=0,available_at=?,error=NULL "
                "WHERE key=? AND status='failed'",
                (now.timestamp(), "master:" + key),
            )
        return self.status(key)

    @staticmethod
    def _revision(connection: sqlite3.Connection) -> int:
        return int(
            connection.execute(
                "SELECT COALESCE(MAX(revision),0) FROM profile_settings_revisions"
            ).fetchone()[0]
        )

    def latest(self) -> dict[str, Any]:
        snapshot = self.profiles.read()
        return self.status(self.key(snapshot.revision))

    def status(self, key: str) -> dict[str, Any]:
        with self.store.connection() as connection:
            revision = self._revision(connection)
            row = connection.execute(
                "SELECT m.*,t.status,t.error FROM master_resumes m "
                "JOIN tasks t ON t.key='master:'||m.key "
                "WHERE m.key=?",
                (key,),
            ).fetchone()
        if row is None:
            return {
                "state": "idle",
                "profile_revision": revision,
                "template_revision": TEMPLATE_REVISION,
            }
        state = "ready" if row["filename"] and row["status"] == "done" else row["status"]
        if row["profile_revision"] != revision or row["template_revision"] != TEMPLATE_REVISION:
            state = "stale"
        response: dict[str, Any] = {
            "key": key,
            "state": state,
            "profile_revision": row["profile_revision"],
            "template_revision": row["template_revision"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
            "pages": row["pages"],
        }
        if state == "failed":
            response["error"] = row["error"] or "Generation stopped. Generate again to retry."
        if state == "ready":
            response["preview_url"] = (
                f"/api/master-resume/{key}/pdf#toolbar=0&navpanes=0&view=FitH"
            )
            response["download_url"] = f"/api/master-resume/{key}/pdf?download=true"
            response["omitted_unknown"] = len(json.loads(row["manifest"])["omitted_unknown_ids"])
        return response

    def pdf(self, key: str) -> bytes:
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise FileNotFoundError
        with self.store.connection() as connection:
            row = connection.execute("SELECT * FROM master_resumes WHERE key=?", (key,)).fetchone()
        if row is None or not row["filename"]:
            raise FileNotFoundError
        name = row["filename"]
        if not re.fullmatch(r"[0-9a-f]{64}-[0-9a-f]{32}\.pdf", name):
            raise FileNotFoundError
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            with os.fdopen(fd, "rb") as stream:
                metadata = os.fstat(stream.fileno())
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 16 * 1024 * 1024:
                    raise FileNotFoundError
                content = stream.read(16 * 1024 * 1024 + 1)
        finally:
            os.close(directory)
        if not content.startswith(b"%PDF-") or hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise FileNotFoundError
        return content

    def _snapshot(self, revision: int) -> Snapshot:
        with self.store.connection() as connection:
            row = connection.execute(
                "SELECT * FROM profile_settings_revisions WHERE revision=?", (revision,)
            ).fetchone()
        if row is None:
            raise ResumeValidationError(
                "Saved profile revision is unavailable. Save and generate again."
            )
        return Snapshot(
            revision=row["revision"],
            saved_at=row["saved_at"],
            profile=json.loads(row["profile"]),
            preferences=json.loads(row["preferences"]),
        )

    def process_next(self) -> bool:
        task = self.queue.claim(["master_resume"])
        if task is None:
            return False
        try:
            with self.queue.heartbeat(task):
                self._generate(task)
        except ResumeValidationError as exc:
            message = str(exc)
            if "compiler" in message or "compile" in message:
                message = (
                    "PDF compilation failed. Check that the deployment has pdflatex "
                    "and template packages, then retry."
                )
            elif "overflow" in message or "page count" in message:
                message = (
                    "Your saved facts exceed this two-page template. Shorten facts "
                    "or remove entries and save, then generate again."
                )
            self.queue.needs_attention(task, message)
        except ResumeMatcherError:
            self.queue.needs_attention(
                task,
                "PDF compilation timed out. Shorten facts and retry; "
                "check the deployment compiler if this continues.",
            )
        except Exception:
            self.queue.needs_attention(
                task, "The PDF could not be saved. Check the private artifact directory and retry."
            )
        return True

    def _generate(self, task: Task) -> None:
        snapshot = self._snapshot(task.payload["profile_revision"])
        key = self.key(snapshot.revision)
        if task.payload.get("template_revision") != TEMPLATE_REVISION or task.payload["key"] != key:
            raise ResumeValidationError("Template changed. Reload Settings and generate again.")
        document = render_master(snapshot)
        content = self.compiler.compile(
            document.source, time.monotonic() + min(self.settings.generation_timeout_seconds, 60)
        )
        pages = validate_master_pdf(content, snapshot, document)
        name = key + "-" + task.token + ".pdf"
        target = self.root / name
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            with self.store.transaction() as connection:
                owned = connection.execute(
                    "SELECT 1 FROM tasks WHERE id=? AND token=? AND status='running' "
                    "AND lease_until>?",
                    (task.id, task.token, utcnow().timestamp()),
                ).fetchone()
                if owned is None:
                    target.unlink(missing_ok=True)
                    return
                connection.execute(
                    "UPDATE master_resumes SET completed_at=?,filename=?,sha256=?,pages=?,"
                    "manifest=? WHERE key=?",
                    (
                        utcnow().isoformat(),
                        name,
                        hashlib.sha256(content).hexdigest(),
                        pages,
                        json.dumps(document.manifest),
                        key,
                    ),
                )
                connection.execute(
                    "UPDATE tasks SET status='done',lease_until=NULL,updated=?,error=NULL "
                    "WHERE id=? AND token=?",
                    (utcnow().timestamp(), task.id, task.token),
                )
        except BaseException:
            target.unlink(missing_ok=True)
            raise
