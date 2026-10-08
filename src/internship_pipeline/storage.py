"""SQLite state for observations and work, using short transactions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from internship_pipeline.models import (
    Company,
    FetchResult,
    Job,
    MatchResult,
    utcnow,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS targets (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, config TEXT NOT NULL, provider TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1, baselined INTEGER NOT NULL DEFAULT 0,
    next_due REAL NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0,
    last_success REAL, last_attempt REAL, failures INTEGER NOT NULL DEFAULT 0,
    error TEXT, complete INTEGER NOT NULL DEFAULT 0,
    collection_owner TEXT NOT NULL DEFAULT 'registry'
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
CREATE TABLE IF NOT EXISTS assessments (
    identity TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
    result TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS assessment_attempts (
    id INTEGER PRIMARY KEY, identity TEXT NOT NULL, job_id TEXT NOT NULL,
    started REAL NOT NULL, completed REAL, status TEXT NOT NULL,
    reserved_tokens INTEGER NOT NULL, input_tokens INTEGER, output_tokens INTEGER
);
CREATE INDEX IF NOT EXISTS assessment_attempt_identity ON assessment_attempts(identity);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL,
    lease_until REAL, token TEXT, error TEXT, created REAL NOT NULL, updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS task_claim ON tasks(kind, status, available_at);
CREATE TABLE IF NOT EXISTS providers (
    id TEXT PRIMARY KEY, next_allowed REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS candidates (
    url TEXT PRIMARY KEY, company TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    error TEXT, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS maintenance (
    name TEXT PRIMARY KEY, next_due REAL NOT NULL DEFAULT 0
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
        self,
        target_id: str,
        kind: str,
        config: str,
        provider: str,
        enabled: bool = True,
        *,
        collection_owner: str = "registry",
    ) -> None:
        with self.transaction() as connection:
            old = connection.execute(
                "SELECT config FROM targets WHERE id=?", (target_id,)
            ).fetchone()
            if old is not None and old["config"] != config:
                # A changed board/query starts a new baseline, without deleting job history.
                connection.execute("UPDATE targets SET baselined=0 WHERE id=?", (target_id,))
            connection.execute(
                "INSERT INTO targets(id,kind,config,provider,enabled,collection_owner) "
                "VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET config=excluded.config, "
                "provider=excluded.provider, enabled=excluded.enabled, "
                "collection_owner=excluded.collection_owner",
                (target_id, kind, config, provider, int(enabled), collection_owner),
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

    def provider_ready_at(self, provider: str) -> float:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT next_allowed FROM providers WHERE id=?", (provider,)
            ).fetchone()
            return float(row["next_allowed"]) if row else 0

    def defer_target(self, target_id: str, until: float) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE targets SET next_due=?,lease_until=0 WHERE id=?", (until, target_id)
            )

    def finish_target(
        self, target_id: str, next_due: float, result: FetchResult, now: float
    ) -> None:
        healthy = (result.error is None and result.complete) or result.coverage_limited
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
        checkpoint: Callable[[sqlite3.Connection], None] | None = None,
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
                        "SELECT * FROM jobs WHERE canonical_url=? AND company_key=? "
                        "AND (requisition_id IS NULL OR ? IS NULL OR requisition_id=?)",
                        (url, company_key, posting.requisition_id, posting.requisition_id),
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
                    # Preserve a direct company's richer evidence when an aggregator rediscovers it.
                    replace_posting = not posting.source.startswith("jobspy") or (
                        job.posting.source.startswith("jobspy")
                    )
                    reopened = job.status == "closed" and replace_posting
                    changed = replace_posting and digest != job.content_hash
                    updates: dict[str, Any] = {
                        "last_seen_at": now,
                    }
                    if replace_posting:
                        updates.update(
                            posting=posting,
                            content_hash=digest,
                            last_verified_at=now,
                            status="open",
                        )
                    if reopened:
                        updates["event"] = "reopened"
                        updates["opening_revision"] = job.opening_revision + 1
                    job = job.model_copy(update=updates)
                    connection.execute(
                        "UPDATE jobs SET data=?,status=?,last_seen=?,content_hash=?, "
                        "canonical_url=?,requisition_id=? "
                        "WHERE id=?",
                        (
                            job.model_dump_json(),
                            job.status,
                            timestamp,
                            job.content_hash,
                            canonical_url(job.posting.apply_url),
                            job.posting.requisition_id,
                            job.id,
                        ),
                    )
                    if reopened and target["baselined"]:
                        enqueue(
                            connection,
                            "match",
                            f"reopen:{job.id}:{timestamp}:{profile_revision}",
                            {"job_id": job.id, "profile_revision": profile_revision},
                            timestamp,
                        )
                    elif changed and target["baselined"] and job.event != "backlog":
                        enqueue(
                            connection,
                            "match",
                            f"match:{job.id}:{job.content_hash}:{profile_revision}",
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
                            # Only full direct-board inventories prove absence. Every direct
                            # alias must independently accumulate that evidence.
                            present = connection.execute(
                                "SELECT 1 FROM observations o JOIN targets t ON t.id=o.target_id "
                                "WHERE o.job_id=? AND o.source NOT LIKE 'jobspy%' "
                                "AND (t.kind!='company' OR o.misses<2) LIMIT 1",
                                (observed["job_id"],),
                            ).fetchone()
                            if present is not None:
                                continue
                            existing = connection.execute(
                                "SELECT * FROM jobs WHERE id=?", (observed["job_id"],)
                            ).fetchone()
                            job = row_job(existing)
                            job = job.model_copy(update={"status": "closed"})
                            connection.execute(
                                "UPDATE jobs SET status='closed',data=? WHERE id=?",
                                (job.model_dump_json(), job.id),
                            )
            # A partial inventory can establish the observed baseline without proving absences.
            # Later additions are first observations, never claims of publication time.
            if result.jobs or (result.complete and result.error is None):
                connection.execute("UPDATE targets SET baselined=1 WHERE id=?", (target_id,))
            if checkpoint:
                checkpoint(connection)
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
        self,
        job: Job,
        match: MatchResult,
        profile_revision: str,
        *,
        settings_revision: int | None = None,
    ) -> None:
        now = utcnow().timestamp()
        with self.transaction() as connection:
            if (
                settings_revision is not None
                and connection.execute(
                    "SELECT COALESCE(MAX(revision),0) FROM profile_settings_revisions"
                ).fetchone()[0]
                != settings_revision
            ):
                return
            connection.execute(
                "INSERT OR REPLACE INTO matches VALUES(?,?,?,?,?)",
                (job.id, job.content_hash, profile_revision, match.model_dump_json(), now),
            )
            connection.execute(
                "INSERT INTO events(kind,job_id,at,details) VALUES('matched',?,?,?)",
                (job.id, now, json.dumps({"fit": match.fit})),
            )

    def get_match(self, job: Job, profile_revision: str) -> MatchResult | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT result FROM matches WHERE job_id=? AND content_hash=? "
                "AND profile_revision=?",
                (job.id, job.content_hash, profile_revision),
            ).fetchone()
            return MatchResult.model_validate_json(row[0]) if row else None

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
            failed = [
                dict(row)
                for row in connection.execute(
                    "SELECT id,kind,error,attempts,updated FROM tasks WHERE status='failed' "
                    "ORDER BY updated DESC LIMIT 50"
                )
            ]
            candidates = {
                row["status"]: row["n"]
                for row in connection.execute(
                    "SELECT status,COUNT(*) n FROM candidates GROUP BY status"
                )
            }
        targets = self.targets()
        return {
            "jobs": job_count,
            "tasks": counts,
            "failed_tasks": failed,
            "discovery_candidates": candidates,
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
                        "complete",
                    )
                }
                for row in targets
            ],
            "overdue_targets": sum(
                row["enabled"] and row["next_due"] < now - 60 for row in targets
            ),
        }

    def add_candidates(self, companies: list[Company]) -> int:
        with self.transaction() as connection:
            added = 0
            for company in companies:
                added += connection.execute(
                    "INSERT OR IGNORE INTO candidates(url,company,created) VALUES(?,?,?)",
                    (company.careers_url, company.model_dump_json(), utcnow().timestamp()),
                ).rowcount
            return added

    def candidate_companies(self, limit: int = 200) -> list[Company]:
        with self.connection() as connection:
            return [
                Company.model_validate_json(row[0])
                for row in connection.execute(
                    "SELECT company FROM candidates WHERE status IN ('pending','failed') "
                    "ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END,created LIMIT ?",
                    (limit,),
                )
            ]

    def finish_candidate(self, company: Company, status: str, error: str | None = None) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE candidates SET status=?,error=?,created=? WHERE url=?",
                (status, error, utcnow().timestamp(), company.careers_url),
            )

    def claim_discovery(self, now: float, force: bool = False) -> bool:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT next_due FROM maintenance WHERE name='discovery'"
            ).fetchone()
            if row and row[0] > now and not force:
                return False
            # A crash retries on the next day; already validated candidates retain their state.
            connection.execute(
                "INSERT INTO maintenance VALUES('discovery',?) ON CONFLICT(name) "
                "DO UPDATE SET next_due=excluded.next_due",
                (now + 86400,),
            )
            return True
