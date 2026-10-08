"""Optional encrypted SMTP destination and independent durable delivery work."""

from __future__ import annotations

import json
import re
import sqlite3
import tempfile
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import InvalidToken
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from internship_pipeline.assessments import current_identity, stored_view
from internship_pipeline.model_connections import ModelConnectionStore
from internship_pipeline.models import Job
from internship_pipeline.queue import Queue, Task
from internship_pipeline.storage import Store, enqueue


class EmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    host: str = Field(min_length=1, max_length=253, pattern=r"^[a-zA-Z0-9.-]+$")
    port: int = Field(default=587, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=320)
    password: SecretStr | None = None
    sender: str
    recipient: str
    security: Literal["starttls", "ssl"] = "starttls"
    enabled: bool = False
    mode: Literal["alerts", "digest"] = "alerts"
    minimum_score: float = Field(default=70, ge=0, le=100)
    digest_hour: int = Field(default=9, ge=0, le=23)
    timezone: str = "UTC"
    attach_pdf: bool = False

    @model_validator(mode="after")
    def validate_fields(self) -> EmailInput:
        for address in (self.sender, self.recipient):
            if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", address):
                raise ValueError("Enter one valid sender and recipient email address.")
        if any(c in self.username for c in "\r\n"):
            raise ValueError("Invalid SMTP username.")
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Choose an IANA timezone, such as America/Denver.") from None
        return self


def apprise_email(
    config: dict[str, Any], password: str, title: str, body: str, attachments: list[bytes]
) -> str:
    """Apprise's false result has ambiguous remote acceptance; require explicit retry."""
    import apprise

    url = "mailtos://_?" + urlencode(
        {
            "smtp": config["host"],
            "port": config["port"],
            "user": config["username"],
            "pass": password,
            "from": config["sender"],
            "to": config["recipient"],
            "mode": config["security"],
            "timeout": 20,
        }
    )
    client = apprise.Apprise()
    if not client.add(url):
        return "rejected"
    with tempfile.TemporaryDirectory(prefix="pipeline-email-") as folder:
        paths = []
        if all(service.attachment_support for service in client):
            for index, content in enumerate(attachments):
                path = Path(folder) / f"draft-{index + 1}.pdf"
                path.write_bytes(content)
                path.chmod(0o600)
                paths.append(str(path))
        try:
            accepted = client.notify(
                title=title, body=body, body_format=apprise.NotifyFormat.TEXT, attach=paths or None
            )
        except Exception:
            return "uncertain"
        return "accepted" if accepted is True else "uncertain"


class EmailIntegrations:
    def __init__(
        self,
        store: Store,
        connections: ModelConnectionStore,
        *,
        transport: Callable[..., str] | None = None,
        pdf_provider: Callable[[str], bytes | None] | None = None,
    ):
        self.store, self.connections = store, connections
        from internship_pipeline.job_workspace import initialize

        initialize(store.path)
        self.queue = Queue(store, lease_seconds=120, max_attempts=3)
        self.transport = transport or apprise_email
        self.pdf_provider = pdf_provider
        with store.connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS email_config (
              id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL,
              config TEXT NOT NULL, encrypted BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS email_deliveries (
              id TEXT PRIMARY KEY, revision INTEGER NOT NULL, created REAL NOT NULL,
              status TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
              delivered_at REAL, error TEXT);
            CREATE TABLE IF NOT EXISTS email_members (
              delivery_id TEXT NOT NULL, identity TEXT NOT NULL, job_id TEXT NOT NULL,
              PRIMARY KEY(identity));
            CREATE TABLE IF NOT EXISTS email_attempts (
              id INTEGER PRIMARY KEY, delivery_id TEXT NOT NULL, started REAL NOT NULL,
              completed REAL, status TEXT NOT NULL);
            """)

    def summary(self) -> dict[str, Any]:
        with self.store.connection() as db:
            row = db.execute("SELECT revision,config FROM email_config WHERE id=1").fetchone()
            return {
                "revision": row["revision"] if row else 0,
                "config": json.loads(row["config"]) if row else None,
                "deliveries": [
                    dict(r)
                    for r in db.execute(
                        "SELECT id,created,status,delivered_at,error FROM email_deliveries "
                        "ORDER BY created DESC LIMIT 50"
                    )
                ],
            }

    def save(self, body: EmailInput) -> dict[str, Any]:
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM email_config WHERE id=1").fetchone()
            if (row["revision"] if row else 0) != body.expected_revision:
                raise ValueError("Email settings changed. Reload before saving.")
            if body.password is None and row is None:
                raise ValueError("Enter an SMTP password to create this destination.")
            secret = (
                self.connections.cipher.encrypt(body.password.get_secret_value().encode())
                if body.password is not None
                else row["encrypted"]
            )
            config = body.model_dump(exclude={"password", "expected_revision"})
            db.execute(
                "UPDATE tasks SET status='done',lease_until=NULL WHERE kind='email_delivery' "
                "AND status='pending' AND json_extract(payload,'$.id') IN "
                "(SELECT id FROM email_deliveries WHERE status IN ('queued','retrying'))"
            )
            db.execute(
                "DELETE FROM email_members WHERE delivery_id IN (SELECT id FROM "
                "email_deliveries WHERE status IN ('queued','retrying'))"
            )
            db.execute(
                "UPDATE email_deliveries SET status='cancelled',error='Settings changed' "
                "WHERE status IN ('queued','retrying')"
            )
            db.execute(
                "INSERT OR REPLACE INTO email_config VALUES(1,?,?,?)",
                (body.expected_revision + 1, json.dumps(config), secret),
            )
        return self.summary()

    def _queue(
        self,
        db: Any,
        revision: int,
        title: str,
        body: str,
        members: list[tuple[str, str]],
        now: float,
    ) -> str:
        delivery = uuid.uuid4().hex
        db.execute(
            "INSERT INTO email_deliveries(id,revision,created,status,title,body) "
            "VALUES(?,?,?,'queued',?,?)",
            (delivery, revision, now, title, body),
        )
        db.executemany(
            "INSERT INTO email_members VALUES(?,?,?)",
            [(delivery, identity, job) for identity, job in members],
        )
        enqueue(db, "email_delivery", "email:" + delivery, {"id": delivery}, now)
        return delivery

    def test(self, expected_revision: int) -> str:
        with self.store.transaction() as db:
            row = db.execute("SELECT revision FROM email_config WHERE id=1").fetchone()
            if not row or row[0] != expected_revision:
                raise ValueError("Save current email settings before testing.")
            recent = db.execute(
                "SELECT COUNT(*) FROM email_deliveries WHERE title=? AND created>?",
                ("Internship Pipeline test", time.time() - 3600),
            ).fetchone()[0]
            if recent >= 5:
                raise ValueError("Email test limit reached: five per hour.")
            return self._queue(
                db,
                expected_revision,
                "Internship Pipeline test",
                "Synthetic destination test. No application was submitted.",
                [],
                time.time(),
            )

    def schedule(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM email_config WHERE id=1").fetchone()
            if not row:
                return 0
            config = json.loads(row["config"])
            if not config["enabled"]:
                return 0
            if config["mode"] == "digest":
                local = datetime.fromtimestamp(now, UTC).astimezone(ZoneInfo(config["timezone"]))
                if local.hour < config["digest_hour"]:
                    return 0
                start = local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                if db.execute(
                    "SELECT 1 FROM email_deliveries WHERE title=? AND created>=?",
                    ("Internship Pipeline daily digest", start),
                ).fetchone():
                    return 0
            candidates = []
            for row_job in db.execute("SELECT data FROM jobs WHERE status='open'"):
                job = Job.model_validate_json(row_job[0])
                result = self._eligible(db, job, config)
                if result is None:
                    continue
                identity = current_identity(db, job)
                if db.execute(
                    "SELECT 1 FROM email_members WHERE identity=?", (identity,)
                ).fetchone():
                    continue
                candidates.append((identity, job.id, self._message(job, result)))
                if len(candidates) >= 100:
                    break
            if config["mode"] == "digest" and candidates:
                self._queue(
                    db,
                    row["revision"],
                    "Internship Pipeline daily digest",
                    "\n\n".join(item[2] for item in candidates),
                    [(item[0], item[1]) for item in candidates],
                    now,
                )
                return 1
            for identity, job_id, message in candidates:
                self._queue(
                    db,
                    row["revision"],
                    "Internship opportunity",
                    message,
                    [(identity, job_id)],
                    now,
                )
            return len(candidates)

    @staticmethod
    def _message(job: Job, result: dict[str, Any]) -> str:
        return (
            f"{job.posting.company}: {job.posting.title}\nJob ID: {job.id}\n"
            f"Fit: {result['normalized_fit']} / 100\n"
            f"Source timestamp: {job.posting.published_at or 'Not supplied'}\n"
            f"First observed: {job.first_seen_at.isoformat()}\n"
            f"Apply: {job.posting.apply_url}\nApplication not submitted by this pipeline."
        )

    def retry(self, delivery: str) -> None:
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT status FROM email_deliveries WHERE id=?", (delivery,)
            ).fetchone()
            if not row or row[0] not in {"uncertain", "failed"}:
                raise ValueError("Only failed or uncertain deliveries can be deliberately retried.")
            db.execute(
                "UPDATE email_attempts SET status='uncertain',completed=? "
                "WHERE delivery_id=? AND status='pending'",
                (time.time(), delivery),
            )
            db.execute(
                "UPDATE email_deliveries SET status='queued',error=NULL WHERE id=?", (delivery,)
            )
            db.execute(
                "UPDATE tasks SET status='pending',attempts=0,available_at=?,error=NULL "
                "WHERE key=?",
                (time.time(), "email:" + delivery),
            )

    def _prepare(
        self,
        db: sqlite3.Connection,
        task: Task,
    ) -> tuple[sqlite3.Row, sqlite3.Row, dict[str, Any], list[str]] | None:
        """Revalidate the current members at the fenced transport admission boundary."""
        if not db.execute(
            "SELECT 1 FROM tasks WHERE id=? AND token=? AND status='running' AND lease_until>?",
            (task.id, task.token, time.time()),
        ).fetchone():
            return None
        delivery = task.payload["id"]
        row = db.execute("SELECT * FROM email_deliveries WHERE id=?", (delivery,)).fetchone()
        if row is None:
            self.queue.checkpoint(db, task, "done")
            return None
        if row["status"] in {"accepted", "cancelled", "uncertain", "failed"}:
            self.queue.checkpoint(
                db,
                task,
                "done" if row["status"] in {"accepted", "cancelled"} else "failed",
                None if row["status"] in {"accepted", "cancelled"} else "Delivery requires review",
            )
            return None
        if db.execute(
            "SELECT 1 FROM email_attempts WHERE delivery_id=? AND status='pending'",
            (delivery,),
        ).fetchone():
            db.execute(
                "UPDATE email_attempts SET status='uncertain',completed=? "
                "WHERE delivery_id=? AND status='pending'",
                (time.time(), delivery),
            )
            db.execute(
                "UPDATE email_deliveries SET status='uncertain',error='Acceptance "
                "unknown after interruption' WHERE id=?",
                (delivery,),
            )
            if not self.queue.checkpoint(
                db, task, "failed", "Acceptance unknown; explicit retry required"
            ):
                raise ValueError("Email lease changed")
            return None
        config_row = db.execute("SELECT * FROM email_config WHERE id=1").fetchone()
        config = json.loads(config_row["config"]) if config_row else {}
        is_test = row["title"] == "Internship Pipeline test"
        valid_config = config_row is not None and row["revision"] == config_row["revision"]
        messages, jobs = [], []
        if valid_config and (config.get("enabled") or is_test):
            members = db.execute(
                "SELECT identity,job_id FROM email_members WHERE delivery_id=? ORDER BY job_id",
                (delivery,),
            ).fetchall()
            for member in members:
                job_row = db.execute(
                    "SELECT data FROM jobs WHERE id=?", (member["job_id"],)
                ).fetchone()
                job = Job.model_validate_json(job_row[0]) if job_row else None
                result = self._eligible(db, job, config) if job else None
                if job is not None and result and current_identity(db, job) == member["identity"]:
                    jobs.append(job.id)
                    messages.append(self._message(job, result))
                else:
                    db.execute("DELETE FROM email_members WHERE identity=?", (member["identity"],))
        if not valid_config or not (config.get("enabled") or is_test) or (not jobs and not is_test):
            db.execute("DELETE FROM email_members WHERE delivery_id=?", (delivery,))
            db.execute(
                "UPDATE email_deliveries SET status='cancelled',error='Settings changed "
                "or no current eligible members' WHERE id=?",
                (delivery,),
            )
            if not self.queue.checkpoint(db, task, "done"):
                raise ValueError("Email lease changed")
            return None
        if not is_test:
            db.execute(
                "UPDATE email_deliveries SET body=? WHERE id=?", ("\n\n".join(messages), delivery)
            )
            row = db.execute("SELECT * FROM email_deliveries WHERE id=?", (delivery,)).fetchone()
        return row, config_row, config, jobs

    @staticmethod
    def _eligible(
        db: sqlite3.Connection, job: Job, config: dict[str, Any]
    ) -> dict[str, Any] | None:
        if job.status != "open" or job.applied_at:
            return None
        workspace = db.execute(
            "SELECT dismissed,decision FROM job_workspace WHERE job_id=?",
            (job.id,),
        ).fetchone()
        if workspace and (workspace["dismissed"] or workspace["decision"] == "rejected"):
            return None
        result = stored_view(db, job)["result"]
        if (
            not result
            or result["recommendation"] != "recommended"
            or result["normalized_fit"] < config["minimum_score"]
        ):
            return None
        return dict(result)

    def process_next(self) -> bool:
        # The final exhausted lease cannot be claimed. Preserve its interrupted transport
        # uncertainty and its terminal task together before ordinary queue admission.
        with self.store.transaction() as db:
            interrupted = db.execute(
                "SELECT d.id,t.id AS task_id FROM email_deliveries d JOIN tasks t "
                "ON t.key='email:' || d.id WHERE d.status IN ('queued','sending','retrying') "
                "AND (t.status='failed' OR (t.status='running' AND t.lease_until<=? "
                "AND t.attempts>=?)) AND EXISTS (SELECT 1 FROM email_attempts a "
                "WHERE a.delivery_id=d.id AND a.status='pending')",
                (time.time(), self.queue.max_attempts),
            ).fetchall()
            for row in interrupted:
                db.execute(
                    "UPDATE email_deliveries SET status='uncertain',error='Interrupted "
                    "delivery: remote acceptance unknown' WHERE id=?",
                    (row["id"],),
                )
                db.execute(
                    "UPDATE email_attempts SET status='uncertain',completed=? "
                    "WHERE delivery_id=? AND status='pending'",
                    (time.time(), row["id"]),
                )
                db.execute(
                    "UPDATE tasks SET status='failed',lease_until=NULL,error='Acceptance unknown; "
                    "explicit retry required',updated=? WHERE id=?",
                    (time.time(), row["task_id"]),
                )
        task = self.queue.claim(["email_delivery"])
        if task is None:
            return False
        with self.store.transaction() as db:
            prepared = self._prepare(db, task)
        if prepared is None:
            return True
        _, _, config, jobs = prepared
        attachments: dict[str, bytes] = {}
        if config["attach_pdf"] and self.pdf_provider:
            for job_id in jobs[:10]:
                try:
                    content = self.pdf_provider(job_id)
                    if content and content.startswith(b"%PDF-") and len(content) <= 5_000_000:
                        attachments[job_id] = content
                except (ValueError, OSError):
                    pass
        # Reading a supported draft can take time. Admit again afterwards so a changed
        # assessment/member/config or a lost lease cannot reach transport with an old body.
        with self.store.transaction() as db:
            prepared = self._prepare(db, task)
            if prepared is None:
                return True
            row, config_row, config, jobs = prepared
            attempt = db.execute(
                "INSERT INTO email_attempts(delivery_id,started,status) VALUES(?,?,'pending')",
                (task.payload["id"], time.time()),
            ).lastrowid
            db.execute(
                "UPDATE email_deliveries SET status='sending' WHERE id=?", (task.payload["id"],)
            )
        try:
            password = self.connections.cipher.decrypt(config_row["encrypted"]).decode()
            with self.queue.heartbeat(task):
                result = self.transport(
                    config,
                    password,
                    row["title"],
                    row["body"],
                    [attachments[job] for job in jobs if job in attachments],
                )
        except InvalidToken:
            result = "credential_unavailable"
        except Exception:
            result = "uncertain"
        if result not in {"accepted", "rejected", "uncertain", "credential_unavailable"}:
            result = "uncertain"
        status = {
            "accepted": "accepted",
            "rejected": "failed" if task.attempts >= self.queue.max_attempts else "retrying",
            "uncertain": "uncertain",
            "credential_unavailable": "failed",
        }[result]
        queue_status = (
            "done" if result == "accepted" else "pending" if status == "retrying" else "failed"
        )
        error = (
            None
            if result == "accepted"
            else "Transport rejected; retry scheduled"
            if status == "retrying"
            else "Transport requires attention"
        )
        with self.store.transaction() as db:
            if self.queue.checkpoint(db, task, queue_status, error):
                db.execute(
                    "UPDATE email_attempts SET completed=?,status=? WHERE id=?",
                    (time.time(), result, attempt),
                )
                db.execute(
                    "UPDATE email_deliveries SET status=?,delivered_at=?,error=? WHERE id=?",
                    (
                        status,
                        time.time() if result == "accepted" else None,
                        error,
                        task.payload["id"],
                    ),
                )
        return True
