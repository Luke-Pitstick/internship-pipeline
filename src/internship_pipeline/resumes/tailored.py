"""Manual, grounded job drafts on the shared durable SQLite queue."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
import time
from typing import Any

import httpx

from internship_pipeline.generation_policy import AutomationDenied, allows_automatic, task_allowed
from internship_pipeline.model_connections import ModelConnectionStore
from internship_pipeline.models import Settings, utcnow
from internship_pipeline.queue import Queue, Task
from internship_pipeline.resumes.errors import DocumentCompileTimeout
from internship_pipeline.resumes.latex import LatexCompiler
from internship_pipeline.resumes.master import MasterConflict, MasterResumes, validate_master_pdf
from internship_pipeline.resumes.master_template import TEMPLATE_REVISION, render_master
from internship_pipeline.resumes.tailored_provider import (
    Selection,
    TailoringFailure,
    request_payload,
    select_facts,
)
from internship_pipeline.resumes.validation import ResumeValidationError
from internship_pipeline.run_limits import RunLimitError, finish, reserve
from internship_pipeline.storage import Store, enqueue

POLICY = "confirmed-selection-v1"


class TailoredResumes:
    def __init__(
        self,
        store: Store,
        settings: Settings,
        *,
        connections: ModelConnectionStore | None = None,
        compiler: LatexCompiler | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.store, self.settings = store, settings
        self.master = MasterResumes(store, settings, compiler=compiler)
        self.profiles = self.master.profiles
        self.compiler = self.master.compiler
        self.queue = Queue(store, settings.lease_seconds, min(settings.max_attempts, 3))
        self.connections = connections or ModelConnectionStore(
            store.path, store.path.parent / "model-credentials.key"
        )
        self.transport = transport
        self.root = settings.artifact_dir / "tailored"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise ValueError("Artifact directory must not be a symbolic link")
        self.root.chmod(0o700)
        with store.connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS tailored_resumes (
                key TEXT PRIMARY KEY, job_id TEXT NOT NULL, job_revision TEXT NOT NULL,
                profile_revision INTEGER NOT NULL, model_revision INTEGER NOT NULL,
                template_revision TEXT NOT NULL, created_at TEXT NOT NULL,
                selection TEXT, usage TEXT, stage TEXT NOT NULL DEFAULT 'queued',
                completed_at TEXT, filename TEXT, sha256 TEXT, pages INTEGER,
                manifest TEXT, reviewed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tailored_attempts (
              id INTEGER PRIMARY KEY, key TEXT NOT NULL, task_attempt INTEGER NOT NULL,
              started_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL,
              effective_model TEXT, input_tokens INTEGER, output_tokens INTEGER
            );
            """)

    def identity(self, job_id: str) -> tuple[str, Any, Any, int]:
        job = self.store.get_job(job_id)
        snapshot = self.profiles.read()
        model_revision = self.connections.summary()["general"]["revision"]
        revision = hashlib.sha256(f"{job.content_hash}:{job.opening_revision}".encode()).hexdigest()
        key = hashlib.sha256(
            json.dumps(
                [job.id, revision, snapshot.revision, model_revision, TEMPLATE_REVISION, POLICY]
            ).encode()
        ).hexdigest()
        return key, job, snapshot, model_revision

    def latest(self, job_id: str) -> dict[str, Any]:
        return self.status(self.identity(job_id)[0], job_id)

    def request(
        self, job_id: str, profile_revision: int, model_revision: int, *, automatic: bool = False
    ) -> dict[str, Any]:
        key, job, snapshot, current_model = self.identity(job_id)
        if automatic:
            with self.store.connection() as db:
                if not allows_automatic(db, job_id):
                    raise AutomationDenied
        if profile_revision != snapshot.revision or model_revision != current_model:
            raise MasterConflict("Profile or model changed. Reload the job and generate again.")
        render_master(snapshot)
        if not any(f.status == "confirmed" for f in snapshot.profile.facts):
            raise ResumeValidationError("Confirm at least one experience, project or skill fact.")
        self.connections.ready_connection("general", model_revision)
        cached = self.status(key, job_id)
        invalid = False
        if cached["state"] in {"draft", "reviewed"}:
            try:
                self.pdf(key)
                return cached
            except (ValueError, OSError):
                invalid = True
        now = utcnow()
        with self.store.transaction() as db:
            if automatic and not allows_automatic(db, job_id):
                raise AutomationDenied
            # Profile/model/job saves cannot quietly relabel a requested revision.
            if self.master._revision(db) != snapshot.revision:
                raise MasterConflict("Profile changed. Reload before generating.")
            db.execute(
                "INSERT OR IGNORE INTO tailored_resumes "
                "(key,job_id,job_revision,profile_revision,model_revision,"
                "template_revision,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    key,
                    job.id,
                    hashlib.sha256(
                        f"{job.content_hash}:{job.opening_revision}".encode()
                    ).hexdigest(),
                    snapshot.revision,
                    model_revision,
                    TEMPLATE_REVISION,
                    now.isoformat(),
                ),
            )
            enqueue(
                db,
                "tailored_resume",
                "tailored:" + key,
                {"key": key, "origin": "automatic" if automatic else "manual"},
                now.timestamp(),
            )
            if not automatic:
                db.execute(
                    "UPDATE tasks SET payload=? WHERE key=? AND status!='running'",
                    (json.dumps({"key": key, "origin": "manual"}), "tailored:" + key),
                )
            if invalid:
                db.execute(
                    "UPDATE tailored_resumes SET filename=NULL,reviewed_at=NULL WHERE key=?", (key,)
                )
                db.execute(
                    "UPDATE tasks SET status='failed' WHERE key=? AND status='done'",
                    ("tailored:" + key,),
                )
            if automatic:
                db.execute(
                    "UPDATE tasks SET status='pending',available_at=?,error=NULL "
                    "WHERE key=? AND status='cancelled' "
                    "AND json_extract(payload,'$.origin')='automatic'",
                    (now.timestamp(), "tailored:" + key),
                )
            if not automatic:
                db.execute(
                    "UPDATE tasks SET status='pending',attempts=0,available_at=?,error=NULL "
                    "WHERE key=? AND status IN ('failed','cancelled')",
                    (now.timestamp(), "tailored:" + key),
                )
        return self.status(key, job_id)

    def status(self, key: str, job_id: str) -> dict[str, Any]:
        _, _, snapshot, model_revision = self.identity(job_id)
        with self.store.connection() as db:
            row = db.execute(
                "SELECT r.*,t.status,t.error,t.attempts FROM tailored_resumes r "
                "JOIN tasks t ON t.key='tailored:'||r.key WHERE r.key=?",
                (key,),
            ).fetchone()
        if row is None:
            return {
                "state": "idle",
                "profile_revision": snapshot.revision,
                "model_revision": model_revision,
            }
        state = row["status"]
        if row["filename"] and state == "done":
            state = "reviewed" if row["reviewed_at"] else "draft"
        if key != self.identity(job_id)[0]:
            state = "stale"
        result = {
            "key": key,
            "state": state,
            "profile_revision": row["profile_revision"],
            "model_revision": row["model_revision"],
            "stage": row["stage"],
            "attempts": row["attempts"],
            "pages": row["pages"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
            "reviewed_at": row["reviewed_at"],
        }
        if row["error"] and state in {"failed", "pending"}:
            result["error"] = row["error"]
        if state in {"draft", "reviewed"}:
            info = json.loads(row["usage"]) if row["usage"] else [None, None, None]
            result["model_usage"] = {
                "effective_model": info[0],
                "input_tokens": info[1],
                "output_tokens": info[2],
            }
            manifest = json.loads(row["manifest"])
            result.update(
                changes=manifest["changes"],
                warnings=manifest["warnings"],
                preview_url=f"/api/tailored-resume/{key}/pdf",
                download_url=f"/api/tailored-resume/{key}/pdf?download=true",
            )
        return result

    def review(self, key: str) -> dict[str, Any]:
        with self.store.transaction() as db:
            row = db.execute("SELECT job_id FROM tailored_resumes WHERE key=?", (key,)).fetchone()
            if row is None:
                raise FileNotFoundError
            status = self.status(key, row[0])
            if status["state"] not in {"draft", "reviewed"}:
                raise MasterConflict("Only the current completed draft can be reviewed.")
            self.pdf(key)
            db.execute(
                "UPDATE tailored_resumes SET reviewed_at=? WHERE key=?", (utcnow().isoformat(), key)
            )
        return self.status(key, row[0])

    def pdf(self, key: str) -> bytes:
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM tailored_resumes WHERE key=?", (key,)).fetchone()
        if row is None or not row["filename"] or key != self.identity(row["job_id"])[0]:
            raise FileNotFoundError
        return self._read_pdf(row, key)

    def process_next(self) -> bool:
        task = self.queue.claim(["tailored_resume"], guard=task_allowed)
        if task is None:
            return False
        try:
            with self.queue.heartbeat(task):
                self._generate(task)
        except AutomationDenied:
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE tasks SET status='cancelled',attempts=MAX(0,attempts-1),"
                    "lease_until=NULL,error='Automation disabled or job no longer qualifies' "
                    "WHERE id=? AND token=? AND status='running'",
                    (task.id, task.token),
                )
        except RunLimitError as exc:
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE tasks SET attempts=MAX(0,attempts-1) "
                    "WHERE id=? AND token=? AND status='running'",
                    (task.id, task.token),
                )
            self.queue.needs_attention(task, str(exc))
        except TailoringFailure as exc:
            message = {
                "grounding": "The model selected unsupported facts. Retry or change the model.",
                "output": "The model returned malformed or incomplete output. "
                "Retry or change the model.",
                "input_limit": "Confirmed facts and job context exceed the "
                "request limit. Shorten them.",
                "timeout": "Model request timed out; usage is unknown. Retry "
                "after checking the provider.",
                "authentication": "Model authentication failed. Replace and test "
                "the general LLM key.",
                "rate_limit": "The model quota was reached. Check your provider account.",
                "unsupported": "The selected model does not support structured generation.",
                "unavailable": "The model is unavailable. Bounded retries are pending.",
            }[exc.status]
            if exc.status in {"unavailable", "rate_limit"}:
                self.queue.fail(task, message)
            else:
                self.queue.needs_attention(task, message)
        except (ResumeValidationError, DocumentCompileTimeout):
            self.queue.needs_attention(
                task,
                "PDF validation or compilation failed. Shorten confirmed facts "
                "or check the compiler, then retry.",
            )
        except ValueError:
            self.queue.needs_attention(
                task, "Profile, job or model changed. Reload and generate again."
            )
        except Exception:
            self.queue.needs_attention(
                task, "Document storage failed. Check private artifact storage and retry."
            )
        return True

    def _checkpoint(self, task: Task, **values: Any) -> bool:
        with self.store.transaction() as db:
            owned = db.execute(
                "SELECT 1 FROM tasks WHERE id=? AND token=? AND status='running' AND lease_until>?",
                (task.id, task.token, utcnow().timestamp()),
            ).fetchone()
            if not owned:
                return False
            db.execute(
                "UPDATE tailored_resumes SET "
                + ",".join(f"{k}=?" for k in values)
                + " WHERE key=?",
                (*values.values(), task.payload["key"]),
            )
            return True

    def _generate(self, task: Task) -> None:
        key = task.payload["key"]
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM tailored_resumes WHERE key=?", (key,)).fetchone()
        current_key, job, snapshot, model_revision = self.identity(row["job_id"])
        if current_key != key:
            raise MasterConflict("Stale draft")
        if task.payload.get("origin") == "automatic":
            with self.store.transaction() as db:
                if not allows_automatic(db, job.id):
                    raise AutomationDenied
        config, secret = self.connections.ready_connection("general", model_revision)
        facts = [
            f.model_dump(mode="json") for f in snapshot.profile.facts if f.status == "confirmed"
        ]
        if row["selection"]:
            selection = Selection.model_validate_json(row["selection"])
        else:
            if not self._checkpoint(task, stage="selecting confirmed facts"):
                return
            with self.store.transaction() as db:
                if task.payload.get("origin") == "automatic" and not allows_automatic(db, job.id):
                    raise AutomationDenied
                payload = request_payload(
                    config,
                    facts,
                    {
                        "title": job.posting.title,
                        "company": job.posting.company,
                        "description": job.posting.description,
                    },
                )
                reservation = reserve(
                    db,
                    job.id,
                    "generation",
                    len(json.dumps(payload).encode()) + config.max_output_tokens,
                )
                attempt = db.execute(
                    "INSERT INTO "
                    "tailored_attempts(key,task_attempt,started_at,status) VALUES(?,?,?,?)",
                    (key, task.attempts, utcnow().isoformat(), "pending"),
                ).lastrowid
            try:
                selection, info = asyncio.run(
                    select_facts(
                        config,
                        secret,
                        facts,
                        {
                            "title": job.posting.title,
                            "company": job.posting.company,
                            "description": job.posting.description,
                        },
                        transport=self.transport,
                    )
                )
            except TailoringFailure as exc:
                with self.store.transaction() as db:
                    finish(db, reservation, exc.status, exc.info[1], exc.info[2])
                    db.execute(
                        "UPDATE tailored_attempts SET "
                        "completed_at=?,status=?,effective_model=?,input_tokens=?,"
                        "output_tokens=? WHERE id=?",
                        (utcnow().isoformat(), exc.status, *exc.info, attempt),
                    )
                self._checkpoint(task, usage=json.dumps(exc.info))
                raise
            with self.store.transaction() as db:
                finish(db, reservation, "success", info[1], info[2])
                db.execute(
                    "UPDATE tailored_attempts SET "
                    "completed_at=?,status=?,effective_model=?,input_tokens=?,"
                    "output_tokens=? WHERE id=?",
                    (utcnow().isoformat(), "success", *info, attempt),
                )
            if not self._checkpoint(
                task,
                selection=selection.model_dump_json(),
                usage=json.dumps(info),
                stage="validated selection",
            ):
                return
        by_id = {f.id: f for f in snapshot.profile.facts if f.status == "confirmed"}
        if len(set(selection.fact_ids)) != len(selection.fact_ids) or not set(
            selection.fact_ids
        ) <= set(by_id):
            raise TailoringFailure("grounding")
        selected = snapshot.model_copy(
            update={
                "profile": snapshot.profile.model_copy(
                    update={"facts": [by_id[id] for id in selection.fact_ids]}
                )
            }
        )
        document = render_master(selected)
        omitted = [f.id for f in snapshot.profile.facts if f.id not in selection.fact_ids]
        document.manifest.update(
            job_id=job.id,
            job_revision=row["job_revision"],
            model_revision=model_revision,
            policy_revision=POLICY,
            changes={
                "selected_fact_ids": selection.fact_ids,
                "omitted_fact_ids": omitted,
                "selected": [{"id": id, "text": by_id[id].text} for id in selection.fact_ids],
                "omitted": [
                    {"id": f.id, "text": f.text, "status": f.status}
                    for f in snapshot.profile.facts
                    if f.id in omitted
                ],
                "wording": "Confirmed wording preserved verbatim; selected facts "
                "ordered within their sections.",
            },
            warnings=[
                "Review every fact, omitted experience and the job requirements before applying.",
                "Job requirements are untrusted matching context and cannot "
                "create candidate claims.",
                "Unknown profile facts and eligibility remain unknown; this "
                "draft does not establish eligibility.",
            ],
        )
        if not self._checkpoint(task, stage="compiling and validating PDF"):
            return
        content = self.compiler.compile(
            document.source, time.monotonic() + min(60, self.settings.generation_timeout_seconds)
        )
        pages = validate_master_pdf(content, selected, document)
        if key != self.identity(job.id)[0]:
            raise MasterConflict("Stale completion")
        name = key + "-" + task.token + ".pdf"
        target = self.root / name
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            with self.store.transaction() as db:
                if (
                    key != self.identity(job.id)[0]
                    or not db.execute(
                        "SELECT 1 FROM tasks WHERE id=? AND token=? AND status='running' "
                        "AND lease_until>?",
                        (task.id, task.token, utcnow().timestamp()),
                    ).fetchone()
                ):
                    target.unlink(missing_ok=True)
                    return
                db.execute(
                    "UPDATE tailored_resumes SET "
                    "filename=?,sha256=?,pages=?,manifest=?,completed_at=?,stage=? WHERE key=?",
                    (
                        name,
                        hashlib.sha256(content).hexdigest(),
                        pages,
                        json.dumps(document.manifest),
                        utcnow().isoformat(),
                        "awaiting user review",
                        key,
                    ),
                )
                db.execute(
                    "UPDATE tasks SET status='done',lease_until=NULL,error=NULL "
                    "WHERE id=? AND token=?",
                    (task.id, task.token),
                )
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    def _read_pdf(self, row: Any, key: str) -> bytes:
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
