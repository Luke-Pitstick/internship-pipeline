"""Stable-ID Sheets plans, cell ownership and restart-safe shared-queue work."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
import time
import uuid
from collections.abc import Callable, Generator
from contextlib import closing
from typing import Any

from cryptography.fernet import InvalidToken
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from internship_pipeline.assessments import stored_view
from internship_pipeline.model_connections import ModelConnectionStore
from internship_pipeline.models import Job, utcnow
from internship_pipeline.queue import Queue
from internship_pipeline.sheets_provider import GoogleSheets, SheetsFailure, credential_info
from internship_pipeline.storage import Store, enqueue

FIELDS = [
    "job_id",
    "company",
    "title",
    "location",
    "score",
    "posted_at",
    "first_observed_at",
    "deadline",
    "apply_url",
    "source_status",
]
DEFAULT_MAPPING = dict(zip(FIELDS, "ABCDEFGHIJ", strict=True))
MAX_SHEETS_JOBS = 10000


def column_index(column: str) -> int:
    value = 0
    for character in column:
        value = value * 26 + ord(character) - 64
    return value - 1


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def cell(rows: list[list[Any]], row: int, column: str) -> Any:
    index = column_index(column)
    return rows[row - 1][index] if row <= len(rows) and index < len(rows[row - 1]) else ""


class SheetsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    spreadsheet_id: str = Field(min_length=10, max_length=150, pattern=r"^[A-Za-z0-9_-]+$")
    tab: str = Field(default="", max_length=100)
    service_account: SecretStr | None = Field(default=None, max_length=16384)
    mapping: dict[str, str] = Field(default_factory=lambda: DEFAULT_MAPPING.copy())
    inward_status: str | None = None
    inward_notes: str | None = None
    enabled: bool = False
    interval_minutes: int = Field(default=60, ge=5, le=10080)

    @model_validator(mode="after")
    def mappings(self) -> SheetsInput:
        if not self.mapping.get("job_id") or set(self.mapping) - set(FIELDS):
            raise ValueError("Map stable job_id and only the documented outward fields.")
        columns = [
            *self.mapping.values(),
            *[c for c in (self.inward_status, self.inward_notes) if c],
        ]
        if any(not re.fullmatch(r"[A-Z]|A[A-Z]", c) for c in columns) or len(set(columns)) != len(
            columns
        ):
            raise ValueError(
                "Choose distinct columns from A through AZ; inward columns cannot be "
                "outward columns."
            )
        if any(ord(c) < 32 for c in self.tab):
            raise ValueError("Choose a valid spreadsheet tab.")
        return self


class SheetsIntegration:
    def __init__(
        self,
        store: Store,
        connections: ModelConnectionStore,
        *,
        provider_factory: Callable[..., Any] | None = None,
    ):
        self.store, self.connections = store, connections
        from internship_pipeline.job_workspace import initialize

        initialize(store.path)
        self.provider_factory = provider_factory or GoogleSheets
        self.queue = Queue(store, lease_seconds=120, max_attempts=3)
        with store.connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS sheets_config (
              id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, config TEXT NOT NULL,
              encrypted BLOB NOT NULL, tested INTEGER, next_due REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS sheets_tests (
              id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sheets_runs (
              id TEXT PRIMARY KEY, revision INTEGER NOT NULL, created REAL NOT NULL,
              state TEXT NOT NULL, error TEXT, destination TEXT NOT NULL, plan TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sheets_checkpoints (
              destination TEXT NOT NULL, job_id TEXT NOT NULL, cells TEXT NOT NULL,
              PRIMARY KEY(destination,job_id));
            CREATE TABLE IF NOT EXISTS sheets_journal (
              run_id TEXT NOT NULL, job_id TEXT NOT NULL, row_number INTEGER NOT NULL,
              cells TEXT NOT NULL, completed REAL, PRIMARY KEY(run_id,job_id));
            CREATE TABLE IF NOT EXISTS sheets_inward (
              id TEXT PRIMARY KEY, destination TEXT NOT NULL, job_id TEXT NOT NULL,
              field TEXT NOT NULL, local_value TEXT NOT NULL, remote_value TEXT NOT NULL,
              state TEXT NOT NULL DEFAULT 'review', created REAL NOT NULL, resolved REAL);
            """)

    def summary(self) -> dict[str, Any]:
        with self.store.connection() as db:
            row = db.execute(
                "SELECT revision,config,tested FROM sheets_config WHERE id=1"
            ).fetchone()
            last_test = db.execute(
                "SELECT status FROM sheets_tests WHERE revision=? ORDER BY id DESC LIMIT 1",
                (row["revision"] if row else 0,),
            ).fetchone()
            return {
                "revision": row["revision"] if row else 0,
                "config": json.loads(row["config"]) if row else None,
                "tested": bool(row and row["tested"] == row["revision"]),
                "last_test": last_test[0] if last_test else None,
                "fields": FIELDS,
                "runs": [
                    dict(r)
                    for r in db.execute(
                        "SELECT id,revision,created,state,error FROM sheets_runs ORDER BY created "
                        "DESC LIMIT 30"
                    )
                ],
                "inward": [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM sheets_inward WHERE state='review' ORDER BY created "
                        "LIMIT 100"
                    )
                ],
            }

    def save(self, body: SheetsInput) -> dict[str, Any]:
        secret = (
            credential_info(body.service_account.get_secret_value())
            if body.service_account
            else None
        )
        with self.store.transaction() as db:
            old = db.execute("SELECT * FROM sheets_config WHERE id=1").fetchone()
            if (old["revision"] if old else 0) != body.expected_revision:
                raise ValueError("Sheets settings changed. Reload before saving.")
            if secret is None and old is None:
                raise ValueError("Paste a Google service-account JSON key first.")
            encrypted = (
                self.connections.cipher.encrypt(json.dumps(secret).encode())
                if secret
                else old["encrypted"]
            )
            config = body.model_dump(exclude={"expected_revision", "service_account"})
            db.execute(
                "INSERT OR REPLACE INTO sheets_config VALUES(1,?,?,?,NULL,0)",
                (body.expected_revision + 1, json.dumps(config), encrypted),
            )
            db.execute(
                "UPDATE sheets_runs SET state='cancelled',error='Configuration changed' "
                "WHERE state IN ('queued','preview','retrying')"
            )
        return self.summary()

    def remove(self, revision: int) -> dict[str, Any]:
        with self.store.transaction() as db:
            row = db.execute("SELECT revision FROM sheets_config WHERE id=1").fetchone()
            if not row or row[0] != revision:
                raise ValueError("Sheets settings changed. Reload before disconnecting.")
            db.execute("DELETE FROM sheets_config")
            db.execute(
                "UPDATE sheets_runs SET state='cancelled',error='Disconnected' WHERE state "
                "IN ('queued','preview','retrying')"
            )
        return self.summary()

    def _connection(
        self, revision: int, *, require_test: bool = True
    ) -> tuple[dict[str, Any], Any]:
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM sheets_config WHERE id=1").fetchone()
        if not row or row["revision"] != revision or (require_test and row["tested"] != revision):
            raise ValueError("Save and successfully test this current Sheets connection first.")
        config = json.loads(row["config"])
        try:
            info = json.loads(self.connections.cipher.decrypt(row["encrypted"]))
        except (InvalidToken, ValueError):
            raise ValueError(
                "Google credential unavailable. Restore the key or replace the credential."
            ) from None
        return config, self.provider_factory(info, config["spreadsheet_id"])

    def test(self, revision: int) -> dict[str, Any]:
        config, provider = self._connection(revision, require_test=False)
        try:
            metadata = provider.metadata()
            tabs = [
                sheet["properties"]["title"]
                for sheet in metadata["sheets"]
                if sheet["properties"].get("gridProperties")
            ]
            if config["tab"] and config["tab"] not in tabs:
                raise ValueError("The selected tab is missing. Choose an existing grid tab.")
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE sheets_config SET tested=? WHERE id=1 AND revision=?",
                    (revision, revision),
                )
                db.execute(
                    "INSERT INTO sheets_tests(revision,status) VALUES(?,'success')", (revision,)
                )
            return {
                "title": metadata["properties"]["title"],
                "tabs": tabs,
                "message": "Read access passed. Sync verifies write access when explicitly queued.",
            }
        except (SheetsFailure, ValueError) as exc:
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE sheets_config SET tested=NULL WHERE id=1 AND revision=?", (revision,)
                )
                db.execute(
                    "INSERT INTO sheets_tests(revision,status) VALUES(?,?)",
                    (revision, "failed" if isinstance(exc, SheetsFailure) else "invalid"),
                )
            raise
        finally:
            provider.close()

    def _facts(self) -> Generator[dict[str, Any], None, None]:
        # A cursor keeps the source inventory bounded in memory and in stable ID order.
        # StreamingResponse awaits next() serially but may use different pool threads.
        # This iterator owns one read-only connection; no other operation shares it.
        with closing(
            sqlite3.connect(
                self.store.path.resolve().as_uri() + "?mode=ro",
                uri=True,
                check_same_thread=False,
                timeout=30,
            )
        ) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            for row in db.execute("SELECT data FROM jobs ORDER BY id"):
                job = Job.model_validate_json(row[0])
                result = stored_view(db, job)["result"]
                notes = db.execute(
                    "SELECT notes FROM job_workspace WHERE job_id=?", (job.id,)
                ).fetchone()
                yield {
                    "job_id": job.id,
                    "company": job.posting.company,
                    "title": job.posting.title,
                    "location": "; ".join(job.posting.locations),
                    "score": result["normalized_fit"] if result else "",
                    "posted_at": job.posting.published_at.isoformat()
                    if job.posting.published_at
                    else "",
                    "first_observed_at": job.first_seen_at.isoformat(),
                    "deadline": job.posting.deadline or "",
                    "apply_url": job.posting.apply_url,
                    "source_status": job.status,
                    "application_status": "applied" if job.applied_at else "not_applied",
                    "notes": notes[0] if notes else "",
                }

    def facts(self) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for record in self._facts():
            if len(output) == MAX_SHEETS_JOBS:
                raise ValueError(
                    "Sheets supports at most 10,000 jobs. Export the complete inventory as CSV."
                )
            output.append(record)
        return output

    def csv(self) -> str:
        return "".join(self.csv_chunks())

    def csv_chunks(self) -> Generator[str, None, None]:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=FIELDS + ["application_status", "notes"])
        writer.writeheader()
        yield output.getvalue()
        with closing(self._facts()) as records:
            for record in records:
                output.seek(0)
                output.truncate()
                # CSV importers may execute formula-like text; quoted CSV alone does not prevent it.
                writer.writerow(
                    {
                        k: (
                            "'" + v
                            if isinstance(v, str)
                            and v.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
                            else v
                        )
                        for k, v in record.items()
                    }
                )
                yield output.getvalue()

    def preview(self, revision: int) -> dict[str, Any]:
        config, provider = self._connection(revision)
        try:
            records = self.facts()
            if not config["tab"]:
                raise ValueError("Choose a tab and save/test before previewing.")
            rows = provider.rows(config["tab"])
            formulas = provider.formulas(config["tab"])
            destination = fingerprint(
                [
                    config["spreadsheet_id"],
                    config["tab"],
                    config["mapping"],
                    config["inward_status"],
                    config["inward_notes"],
                ]
            )
            mapping = config["mapping"]
            id_column = mapping["job_id"]
            ids = {}
            conflicts: list[dict[str, Any]] = []
            for row_number in range(2, len(rows) + 1):
                identifier = cell(rows, row_number, id_column)
                if (row_number, id_column) in formulas:
                    conflicts.append(
                        {
                            "job_id": str(identifier),
                            "reason": "Formula in stable job ID column; remap it",
                        }
                    )
                if identifier:
                    if identifier in ids:
                        conflicts.append(
                            {
                                "job_id": identifier,
                                "reason": "Duplicate stable job ID in destination",
                            }
                        )
                    ids[identifier] = row_number
            changes = []
            next_row = max(2, len(rows) + 1)
            with self.store.connection() as db:
                checkpoints = {
                    r["job_id"]: json.loads(r["cells"])
                    for r in db.execute(
                        "SELECT * FROM sheets_checkpoints WHERE destination=?", (destination,)
                    )
                }
            for record in records:
                identifier = record["job_id"]
                row_number = ids.get(identifier, next_row)
                if row_number > MAX_SHEETS_JOBS + 1:
                    raise ValueError(
                        "Destination exceeds 10,000 job rows. Export the complete inventory "
                        "as CSV or choose a destination with capacity."
                    )
                if identifier not in ids:
                    next_row += 1
                expected = {column: cell(rows, row_number, column) for column in mapping.values()}
                desired = {column: record[field] for field, column in mapping.items()}
                base = checkpoints.get(identifier, {})
                blocked = []
                for column, remote in expected.items():
                    if (row_number, column) in formulas:
                        blocked.append(f"Formula in owned column {column}; remap it")
                    elif (
                        remote != ""
                        and remote != desired[column]
                        and (column not in base or remote != base[column])
                    ):
                        blocked.append(f"Remote edit in owned column {column}")
                if blocked:
                    conflicts.append(
                        {"job_id": identifier, "reason": "; ".join(blocked), "row": row_number}
                    )
                    continue
                changes.append(
                    {
                        "job_id": identifier,
                        "row": row_number,
                        "expected": expected,
                        "desired": desired,
                        "local": record,
                        "new": identifier not in ids,
                    }
                )
            plan = {
                "changes": changes,
                "conflicts": conflicts,
                "source": fingerprint(records),
                "config": config,
                "destination": destination,
            }
            run = uuid.uuid4().hex
            with self.store.transaction() as db:
                db.execute(
                    "INSERT INTO sheets_runs VALUES(?,?,?,'preview',NULL,?,?)",
                    (run, revision, time.time(), destination, json.dumps(plan)),
                )
            return {
                "id": run,
                "rows": len(changes),
                "conflicts": conflicts,
                "changes": changes[:30],
                "truncated": len(changes) > 30,
                "message": "Dry run: no cells changed. Only mapped outward cells will be written.",
            }
        finally:
            provider.close()

    def request(self, run: str) -> None:
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM sheets_runs WHERE id=?", (run,)).fetchone()
            config = db.execute("SELECT revision,tested FROM sheets_config WHERE id=1").fetchone()
            if (
                not row
                or row["state"] != "preview"
                or not config
                or config["revision"] != row["revision"]
                or config["tested"] != row["revision"]
            ):
                raise ValueError("Create a fresh tested preview before syncing.")
            plan = json.loads(row["plan"])
            if plan["conflicts"]:
                raise ValueError(
                    "Resolve destination conflicts or remap columns, then preview again."
                )
            if db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] > MAX_SHEETS_JOBS:
                raise ValueError(
                    "Sheets supports at most 10,000 jobs. Export the complete inventory as CSV."
                )
            db.execute("UPDATE sheets_runs SET state='queued' WHERE id=?", (run,))
            enqueue(db, "sheets_sync", "sheets:" + run, {"id": run}, time.time())

    def schedule(self) -> None:
        with self.store.transaction() as db:
            config = db.execute("SELECT * FROM sheets_config WHERE id=1").fetchone()
            if not config:
                return
            value = json.loads(config["config"])
            if (
                not value["enabled"]
                or config["tested"] != config["revision"]
                or config["next_due"] > time.time()
            ):
                return
            if db.execute(
                "SELECT 1 FROM tasks WHERE kind='sheets_sync' AND status IN ('pending','running')"
            ).fetchone():
                return
            db.execute(
                "UPDATE sheets_config SET next_due=? WHERE id=1",
                (time.time() + value["interval_minutes"] * 60,),
            )
            revision = config["revision"]
        try:
            plan = self.preview(revision)
            if not plan["conflicts"]:
                self.request(plan["id"])
        except (ValueError, SheetsFailure):
            # Preserve provider failure as an inspectable run instead of blocking collection.
            with self.store.transaction() as db:
                db.execute(
                    "INSERT INTO sheets_runs VALUES(?,?,?,'failed',?,?,'{}')",
                    (
                        uuid.uuid4().hex,
                        revision,
                        time.time(),
                        "Scheduled access failed; test the connection",
                        "",
                    ),
                )

    def _inward(
        self, destination: str, item: dict[str, Any], config: dict[str, Any], rows: list[list[Any]]
    ) -> None:
        with self.store.transaction() as db:
            for field, column in (
                ("application_status", config["inward_status"]),
                ("notes", config["inward_notes"]),
            ):
                if not column:
                    continue
                remote = cell(rows, item["row"], column)
                local = item["local"][field]
                if (
                    not isinstance(remote, str)
                    or not remote
                    or remote == local
                    or remote.startswith("=")
                ):
                    continue
                if field == "application_status" and remote not in {"applied", "not_applied"}:
                    continue
                if len(remote) > 10000:
                    continue
                identity = fingerprint([destination, item["job_id"], field, remote, local])
                db.execute(
                    "INSERT OR IGNORE INTO "
                    "sheets_inward(id,destination,job_id,field,local_value,remote_value,created) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (identity, destination, item["job_id"], field, local, remote, time.time()),
                )

    def resolve(self, identity: str, accept: bool) -> dict[str, Any]:
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM sheets_inward WHERE id=? AND state='review'", (identity,)
            ).fetchone()
            if not row:
                raise ValueError("This inward change was already reviewed.")
            job_row = db.execute("SELECT data FROM jobs WHERE id=?", (row["job_id"],)).fetchone()
            job = Job.model_validate_json(job_row[0])
            note = db.execute(
                "SELECT notes FROM job_workspace WHERE job_id=?", (job.id,)
            ).fetchone()
            current = (
                (note[0] if note else "")
                if row["field"] == "notes"
                else ("applied" if job.applied_at else "not_applied")
            )
            if current != row["local_value"]:
                raise ValueError("Local state changed; generate a fresh sync and review.")
            if accept:
                active = db.execute("SELECT config FROM sheets_config WHERE id=1").fetchone()
                if not active:
                    raise ValueError(
                        "This Google connection was disconnected; inward edits are disabled."
                    )
                config = json.loads(active[0])
                destination = fingerprint(
                    [
                        config["spreadsheet_id"],
                        config["tab"],
                        config["mapping"],
                        config["inward_status"],
                        config["inward_notes"],
                    ]
                )
                if destination != row["destination"]:
                    raise ValueError("Inward column mapping changed; sync and review again.")
                if row["field"] == "notes":
                    db.execute(
                        "INSERT OR IGNORE INTO job_workspace(job_id,updated) VALUES(?,?)",
                        (job.id, time.time()),
                    )
                    db.execute(
                        "UPDATE job_workspace SET notes=?,updated=? WHERE job_id=?",
                        (row["remote_value"], time.time(), job.id),
                    )
                else:
                    updated = job.model_copy(
                        update={
                            "applied_at": utcnow() if row["remote_value"] == "applied" else None
                        }
                    )
                    db.execute(
                        "UPDATE jobs SET data=? WHERE id=?", (updated.model_dump_json(), job.id)
                    )
            db.execute(
                "UPDATE sheets_inward SET state=?,resolved=? WHERE id=?",
                ("accepted" if accept else "ignored", time.time(), identity),
            )
        return self.summary()

    def process_next(self) -> bool:
        task = self.queue.claim(["sheets_sync"])
        if not task:
            return False
        run = task.payload["id"]
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM sheets_runs WHERE id=?", (run,)).fetchone()
        if not row or row["state"] == "cancelled":
            self.queue.complete(task)
            return True
        provider = None
        try:
            config, provider = self._connection(row["revision"])
            plan = json.loads(row["plan"])
            if fingerprint(self.facts()) != plan["source"]:
                raise ValueError("Job facts changed after preview. Create a fresh preview.")
            with self.queue.heartbeat(task):
                for item in plan["changes"]:
                    with self.store.connection() as db:
                        journal = db.execute(
                            "SELECT * FROM sheets_journal WHERE run_id=? AND job_id=?",
                            (run, item["job_id"]),
                        ).fetchone()
                    if journal and journal["completed"]:
                        continue
                    rows = provider.rows(config["tab"])
                    formulas = provider.formulas(config["tab"])
                    if any((item["row"], column) in formulas for column in item["desired"]):
                        raise ValueError("Formula appeared in a mapped cell; remap before syncing.")
                    ids = [
                        number
                        for number in range(2, len(rows) + 1)
                        if cell(rows, number, config["mapping"]["job_id"]) == item["job_id"]
                    ]
                    if len(ids) > 1:
                        raise ValueError("Duplicate job IDs need conflict review.")
                    if ids and ids[0] != item["row"]:
                        raise ValueError("Rows moved after preview. Create a fresh preview.")
                    for column, expected in item["expected"].items():
                        remote = cell(rows, item["row"], column)
                        if remote != expected and not (
                            journal and remote == item["desired"][column]
                        ):
                            raise ValueError(
                                "Remote cell changed after preview. Create a fresh preview."
                            )
                    with self.store.transaction() as db:
                        current = db.execute(
                            "SELECT revision FROM sheets_config WHERE id=1"
                        ).fetchone()
                        owned = db.execute(
                            "SELECT 1 FROM tasks WHERE id=? AND token=? AND status='running'",
                            (task.id, task.token),
                        ).fetchone()
                        if not owned or not current or current[0] != row["revision"]:
                            raise ValueError("Settings changed or worker lease lost.")
                        db.execute(
                            "INSERT OR IGNORE INTO "
                            "sheets_journal(run_id,job_id,row_number,cells) VALUES(?,?,?,?)",
                            (run, item["job_id"], item["row"], json.dumps(item["desired"])),
                        )
                    provider.write(config["tab"], item["row"], item["desired"])
                    check = provider.rows(config["tab"])
                    if any(
                        cell(check, item["row"], column) != value
                        for column, value in item["desired"].items()
                    ):
                        raise ValueError("Write verification changed; review destination.")
                    self._inward(plan["destination"], item, config, check)
                    with self.store.transaction() as db:
                        db.execute(
                            "UPDATE sheets_journal SET completed=? WHERE run_id=? AND job_id=?",
                            (time.time(), run, item["job_id"]),
                        )
                        db.execute(
                            "INSERT OR REPLACE INTO sheets_checkpoints VALUES(?,?,?)",
                            (plan["destination"], item["job_id"], json.dumps(item["desired"])),
                        )
            with self.store.transaction() as db:
                db.execute("UPDATE sheets_runs SET state='complete',error=NULL WHERE id=?", (run,))
            self.queue.complete(task)
        except SheetsFailure as exc:
            retry = exc.status in {"retry", "uncertain"} and task.attempts < 3
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE sheets_runs SET state=?,error=? WHERE id=?",
                    ("retrying" if retry else "failed", str(exc), run),
                )
            if retry:
                self.queue.fail(task, exc.status)
            else:
                self.queue.needs_attention(task, exc.status)
        except ValueError as exc:
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE sheets_runs SET state='conflict',error=? WHERE id=?", (str(exc), run)
                )
            self.queue.needs_attention(task, "Review destination or connection")
        finally:
            if provider:
                provider.close()
        return True
