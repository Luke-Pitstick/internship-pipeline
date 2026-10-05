"""SQLite state for observations, work, and delivery, using short transactions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from internship_pipeline.models import (
    FetchResult,
    Job,
    MatchResult,
    ResumeArtifact,
    utcnow,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS targets (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, config TEXT NOT NULL, provider TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1, baselined INTEGER NOT NULL DEFAULT 0,
    next_due REAL NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0,
    last_success REAL, last_attempt REAL, failures INTEGER NOT NULL DEFAULT 0,
    error TEXT, complete INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, data TEXT NOT NULL, canonical_url TEXT NOT NULL,
    company_key TEXT NOT NULL, requisition_id TEXT, content_hash TEXT NOT NULL,
    status TEXT NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_url ON jobs(canonical_url, company_key);
CREATE INDEX IF NOT EXISTS jobs_requisition ON jobs(company_key, requisition_id);
CREATE TABLE IF NOT EXISTS observations (
    source TEXT NOT NULL, board_id TEXT NOT NULL, source_id TEXT NOT NULL,
    target_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id),
    last_seen REAL NOT NULL, misses INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(source, board_id, source_id)
);
CREATE TABLE IF NOT EXISTS matches (
    job_id TEXT NOT NULL REFERENCES jobs(id), content_hash TEXT NOT NULL,
    profile_revision TEXT NOT NULL, result TEXT NOT NULL, created REAL NOT NULL,
    PRIMARY KEY(job_id, content_hash, profile_revision)
);
CREATE TABLE IF NOT EXISTS artifacts (
    key TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL,
    lease_until REAL, token TEXT, error TEXT, created REAL NOT NULL, updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS task_claim ON tasks(kind, status, available_at);
CREATE TABLE IF NOT EXISTS deliveries (
    key TEXT PRIMARY KEY, job_id TEXT NOT NULL, kind TEXT NOT NULL,
    destination_id TEXT NOT NULL, delivered_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS providers (
    id TEXT PRIMARY KEY, next_allowed REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS candidates (
    url TEXT PRIMARY KEY, company TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    error TEXT, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, job_id TEXT,
    at REAL NOT NULL, details TEXT NOT NULL DEFAULT '{}'
);
"""


def enqueue(
    connection: sqlite3.Connection,
    kind: str,
    key: str,
    payload: dict[str, Any],
    now: float,
) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO tasks(kind,key,payload,available_at,created,updated) "
        "VALUES(?,?,?,?,?,?)",
        (kind, key, json.dumps(payload), now, now, now),
    )


def row_job(row: sqlite3.Row) -> Job:
    return Job.model_validate_json(row["data"])


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def register_target(
        self, target_id: str, kind: str, config: str, provider: str, enabled: bool = True
    ) -> None:
        with self.transaction() as connection:
            old = connection.execute(
                "SELECT config FROM targets WHERE id=?", (target_id,)
            ).fetchone()
            if old is not None and old["config"] != config:
                # A changed board/query starts a new baseline, without deleting job history.
                connection.execute("UPDATE targets SET baselined=0 WHERE id=?", (target_id,))
            connection.execute(
                "INSERT INTO targets(id,kind,config,provider,enabled) VALUES(?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET config=excluded.config, "
                "provider=excluded.provider, enabled=excluded.enabled",
                (target_id, kind, config, provider, int(enabled)),
            )

    def targets(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM targets ORDER BY id")]

    def claim_target(
        self, target_id: str, now: float, lease_seconds: float, force: bool = False
    ) -> bool:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM targets WHERE id=?", (target_id,)).fetchone()
            if row is None or not row["enabled"] or row["lease_until"] > now:
                return False
            if not force and row["next_due"] > now:
                return False
            connection.execute(
                "UPDATE targets SET lease_until=?,last_attempt=? WHERE id=?",
                (now + lease_seconds, now, target_id),
            )
            return True

    def reserve_provider(self, provider: str, now: float, spacing: float = 1) -> bool:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT next_allowed FROM providers WHERE id=?", (provider,)
            ).fetchone()
            if row and row["next_allowed"] > now:
                return False
            connection.execute(
                "INSERT INTO providers(id,next_allowed) VALUES(?,?) "
                "ON CONFLICT(id) DO UPDATE SET next_allowed=excluded.next_allowed",
                (provider, now + spacing),
            )
            return True

    def cooldown_provider(self, provider: str, until: float) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO providers(id,next_allowed) VALUES(?,?) ON CONFLICT(id) "
                "DO UPDATE SET next_allowed=MAX(providers.next_allowed,excluded.next_allowed)",
                (provider, until),
            )

    def finish_target(
        self, target_id: str, next_due: float, result: FetchResult, now: float
    ) -> None:
        healthy = result.error is None and result.complete
        with self.transaction() as connection:
            connection.execute(
                "UPDATE targets SET next_due=?,lease_until=0,complete=?,error=?, "
                "failures=CASE WHEN ? THEN 0 ELSE failures+1 END, "
                "last_success=CASE WHEN ? THEN ? ELSE last_success END WHERE id=?",
                (
                    next_due,
                    int(result.complete),
                    result.error
                    if result.error
                    else (None if result.complete else "Incomplete fetch"),
                    healthy,
                    healthy,
                    now,
                    target_id,
                ),
            )

    def ingest(
        self,
        target_id: str,
        result: FetchResult,
        profile_revision: str,
        now: datetime | None = None,
    ) -> list[Job]:
        from internship_pipeline.normalization import canonical_url, content_hash

        now = now or utcnow()
        timestamp = now.timestamp()
        new_jobs: list[Job] = []
        seen: set[tuple[str, str, str]] = set()
        with self.transaction() as connection:
            target = connection.execute("SELECT * FROM targets WHERE id=?", (target_id,)).fetchone()
            if target is None:
                raise ValueError("Target must be registered before ingestion")
            for posting in result.jobs:
                identity = (posting.source, posting.board_id, posting.source_id)
                seen.add(identity)
                url = canonical_url(posting.apply_url)
                company_key = " ".join(posting.company.casefold().split())
                observation = connection.execute(
                    "SELECT job_id FROM observations WHERE source=? AND board_id=? AND source_id=?",
                    identity,
                ).fetchone()
                row = None
                if observation:
                    row = connection.execute(
                        "SELECT * FROM jobs WHERE id=?", (observation["job_id"],)
                    ).fetchone()
                if row is None:
                    row = connection.execute(
                        "SELECT * FROM jobs WHERE canonical_url=? AND company_key=?",
                        (url, company_key),
                    ).fetchone()
                if row is None and posting.requisition_id:
                    row = connection.execute(
                        "SELECT * FROM jobs WHERE company_key=? AND requisition_id=?",
                        (company_key, posting.requisition_id),
                    ).fetchone()
                digest = content_hash(posting)
                if row is None:
                    job_id = hashlib.sha256("\x00".join(identity).encode()).hexdigest()[:24]
                    job = Job(
                        id=job_id,
                        posting=posting,
                        content_hash=digest,
                        first_seen_at=now,
                        last_seen_at=now,
                        last_verified_at=now,
                        event="new" if target["baselined"] else "backlog",
                    )
                    connection.execute(
                        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            job.id,
                            job.model_dump_json(),
                            url,
                            company_key,
                            posting.requisition_id,
                            digest,
                            "open",
                            timestamp,
                            timestamp,
                        ),
                    )
                    new_jobs.append(job)
                    if job.event == "new":
                        enqueue(
                            connection,
                            "match",
                            f"match:{job.id}:{digest}:{profile_revision}",
                            {"job_id": job.id, "profile_revision": profile_revision},
                            timestamp,
                        )
                else:
                    job = row_job(row)
                    reopened = job.status == "closed"
                    # Preserve a direct company's richer evidence when an aggregator rediscovers it.
                    replace_posting = posting.source != "jobspy" or job.posting.source == "jobspy"
                    updates: dict[str, Any] = {
                        "last_seen_at": now,
                        "last_verified_at": now,
                        "status": "open",
                    }
                    if replace_posting:
                        updates.update(posting=posting, content_hash=digest)
                    if reopened:
                        updates["event"] = "reopened"
                    job = job.model_copy(update=updates)
                    connection.execute(
                        "UPDATE jobs SET data=?,status='open',last_seen=?,content_hash=? "
                        "WHERE id=?",
                        (job.model_dump_json(), timestamp, job.content_hash, job.id),
                    )
                    if reopened and target["baselined"]:
                        enqueue(
                            connection,
                            "match",
                            f"reopen:{job.id}:{timestamp}:{profile_revision}",
                            {"job_id": job.id, "profile_revision": profile_revision},
                            timestamp,
                        )
                connection.execute(
                    "INSERT INTO observations VALUES(?,?,?,?,?,?,0) "
                    "ON CONFLICT(source,board_id,source_id) DO UPDATE SET "
                    "last_seen=excluded.last_seen,misses=0",
                    (*identity, target_id, job.id, timestamp),
                )
            if result.complete and result.error is None:
                # Search windows are not full inventories and can never prove closure.
                if target["kind"] == "company":
                    observations = connection.execute(
                        "SELECT * FROM observations WHERE target_id=?", (target_id,)
                    ).fetchall()
                    for observed in observations:
                        identity = (observed["source"], observed["board_id"], observed["source_id"])
                        if identity in seen:
                            continue
                        connection.execute(
                            "UPDATE observations SET misses=misses+1 "
                            "WHERE source=? AND board_id=? AND source_id=?",
                            identity,
                        )
                        if observed["misses"] + 1 >= 2:
                            existing = connection.execute(
                                "SELECT * FROM jobs WHERE id=?", (observed["job_id"],)
                            ).fetchone()
                            job = row_job(existing)
                            job = job.model_copy(update={"status": "closed"})
                            connection.execute(
                                "UPDATE jobs SET status='closed',data=? WHERE id=?",
                                (job.model_dump_json(), job.id),
                            )
                connection.execute("UPDATE targets SET baselined=1 WHERE id=?", (target_id,))
        return new_jobs

    def get_job(self, job_id: str) -> Job:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            return row_job(row)

    def list_jobs(self, backlog_only: bool = False) -> list[Job]:
        with self.connection() as connection:
            jobs = [
                row_job(row) for row in connection.execute("SELECT * FROM jobs ORDER BY first_seen")
            ]
        return [job for job in jobs if not backlog_only or job.event == "backlog"]

    def review_backlog(self, profile_revision: str) -> int:
        jobs = self.list_jobs(backlog_only=True)
        with self.transaction() as connection:
            for job in jobs:
                if job.status == "open":
                    enqueue(
                        connection,
                        "match",
                        f"match:{job.id}:{job.content_hash}:{profile_revision}",
                        {"job_id": job.id, "profile_revision": profile_revision},
                        utcnow().timestamp(),
                    )
        return len(jobs)

    def save_match(
        self, job: Job, match: MatchResult, profile_revision: str, destination_ids: list[str]
    ) -> None:
        now = utcnow().timestamp()
        with self.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO matches VALUES(?,?,?,?,?)",
                (job.id, job.content_hash, profile_revision, match.model_dump_json(), now),
            )
            if match.accepted and job.status == "open":
                revision = f"{job.content_hash}:{profile_revision}"
                for destination in destination_ids:
                    enqueue(
                        connection,
                        "delivery",
                        f"opening:{job.id}:{destination}",
                        {
                            "job_id": job.id,
                            "kind": "opening",
                            "destination_id": destination,
                            "match": match.model_dump(mode="json"),
                        },
                        now,
                    )
                enqueue(
                    connection,
                    "resume",
                    f"resume:{job.id}:{revision}",
                    {
                        "job_id": job.id,
                        "match": match.model_dump(mode="json"),
                        "profile_revision": profile_revision,
                        "content_hash": job.content_hash,
                    },
                    now,
                )
            connection.execute(
                "INSERT INTO events(kind,job_id,at,details) VALUES('matched',?,?,?)",
                (job.id, now, json.dumps({"fit": match.fit})),
            )

    def save_artifact(self, artifact: ResumeArtifact, destination_ids: list[str]) -> None:
        now = utcnow().timestamp()
        with self.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO artifacts VALUES(?,?,?)",
                (artifact.key, artifact.job_id, artifact.model_dump_json()),
            )
            for destination in destination_ids:
                enqueue(
                    connection,
                    "delivery",
                    f"resume:{artifact.key}:{destination}",
                    {
                        "job_id": artifact.job_id,
                        "kind": "resume",
                        "destination_id": destination,
                        "artifact_key": artifact.key,
                    },
                    now,
                )
            connection.execute(
                "INSERT INTO events(kind,job_id,at) VALUES('pdf_ready',?,?)", (artifact.job_id, now)
            )

    def get_artifact(self, key: str) -> ResumeArtifact:
        with self.connection() as connection:
            row = connection.execute("SELECT data FROM artifacts WHERE key=?", (key,)).fetchone()
            if row is None:
                raise KeyError(key)
            return ResumeArtifact.model_validate_json(row["data"])

    def delivered(self, key: str) -> bool:
        with self.connection() as connection:
            return (
                connection.execute("SELECT 1 FROM deliveries WHERE key=?", (key,)).fetchone()
                is not None
            )

    def record_delivery(self, key: str, job_id: str, kind: str, destination_id: str) -> None:
        now = utcnow().timestamp()
        with self.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,?)",
                (key, job_id, kind, destination_id, now),
            )
            connection.execute(
                "INSERT INTO events(kind,job_id,at) VALUES(?,?,?)",
                (f"delivered_{kind}", job_id, now),
            )

    def mark_applied(self, job_id: str) -> None:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            job = row_job(row).model_copy(update={"applied_at": utcnow()})
            connection.execute("UPDATE jobs SET data=? WHERE id=?", (job.model_dump_json(), job_id))

    def health(self) -> dict[str, Any]:
        now = utcnow().timestamp()
        with self.connection() as connection:
            counts = {
                row["status"]: row["n"]
                for row in connection.execute("SELECT status,COUNT(*) n FROM tasks GROUP BY status")
            }
            oldest = connection.execute(
                "SELECT MIN(created) AS oldest FROM tasks WHERE status IN ('pending','running')"
            ).fetchone()["oldest"]
            job_count = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        targets = self.targets()
        return {
            "jobs": job_count,
            "tasks": counts,
            "oldest_work_age_seconds": None if oldest is None else round(now - oldest),
            "targets": [
                {
                    key: row[key]
                    for key in (
                        "id",
                        "kind",
                        "provider",
                        "enabled",
                        "next_due",
                        "last_success",
                        "failures",
                        "error",
                    )
                }
                for row in targets
            ],
            "overdue_targets": sum(
                row["enabled"] and row["next_due"] < now - 60 for row in targets
            ),
        }

    def backup(self, destination: Path) -> None:
        if destination.resolve() == self.path.resolve():
            raise ValueError("Backup destination must differ from the live database")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as source, sqlite3.connect(destination) as target:
            source.backup(target)
