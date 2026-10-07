"""Explicit draft automation, independent of collection, ranking and delivery."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal

from pydantic import Field

from internship_pipeline.assessments import stored_view
from internship_pipeline.models import Job, Record, utcnow
from internship_pipeline.resumes.master import MasterConflict
from internship_pipeline.storage import row_job


class GenerationPolicy(Record):
    enabled: bool = False
    minimum_fit: float = Field(default=75, ge=0, le=100, allow_inf_nan=False)
    recommendation: Literal["recommended", "recommended_or_review"] = "recommended"
    eligibility: Literal["confirmed", "confirmed_or_unknown"] = "confirmed"


class SaveGenerationPolicy(GenerationPolicy):
    expected_revision: int = Field(ge=0, strict=True)


class AutomationDenied(RuntimeError):
    pass


def initialize(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS generation_policy "
        "(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, "
        "data TEXT NOT NULL, saved_at TEXT NOT NULL)"
    )


def read_policy(db: sqlite3.Connection) -> tuple[int, GenerationPolicy]:
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    row = (
        db.execute("SELECT revision,data FROM generation_policy WHERE id=1").fetchone()
        if "generation_policy" in tables
        else None
    )
    return (
        (row[0], GenerationPolicy.model_validate_json(row[1])) if row else (0, GenerationPolicy())
    )


def qualifies(db: sqlite3.Connection, job: Job, policy: GenerationPolicy) -> bool:
    if job.status != "open" or job.applied_at is not None:
        return False
    result = stored_view(db, job)["result"]
    if result is None or result["normalized_fit"] < policy.minimum_fit:
        return False
    if policy.recommendation == "recommended" and result["recommendation"] != "recommended":
        return False
    if result["eligible"] is False:
        return False
    return policy.eligibility != "confirmed" or result["eligible"] is True


def allows_automatic(db: sqlite3.Connection, job_id: str) -> bool:
    _, policy = read_policy(db)
    row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return bool(policy.enabled and row and qualifies(db, row_job(row), policy))


def task_allowed(db: sqlite3.Connection, row: sqlite3.Row) -> bool:
    payload = json.loads(row["payload"])
    if payload.get("origin") != "automatic":
        return True
    draft = db.execute(
        "SELECT job_id FROM tailored_resumes WHERE key=?", (payload["key"],)
    ).fetchone()
    return bool(draft and allows_automatic(db, draft[0]))


class GenerationPolicies:
    def __init__(self, tailored: Any):
        self.tailored = tailored
        self.store = tailored.store
        with self.store.transaction() as db:
            initialize(db)

    def view(self, proposed: GenerationPolicy | None = None) -> dict[str, Any]:
        with self.store.connection() as db:
            revision, saved = read_policy(db)
            policy = proposed or saved
            jobs = [row_job(row) for row in db.execute("SELECT * FROM jobs WHERE status='open'")]
            qualifying = [job.id for job in jobs if qualifies(db, job, policy)]
        return {
            "revision": revision,
            "policy": saved.model_dump(),
            "preview": {"qualifying_count": len(qualifying), "open_count": len(jobs)},
            "explanation": "These rules only create drafts. Search inclusion and alerts have "
            "separate rules. Fit measures rubric alignment, not interview probability. "
            "Unknown eligibility requires review; generation never establishes eligibility "
            "or rejects a job.",
        }

    def save(self, body: SaveGenerationPolicy) -> dict[str, Any]:
        policy = GenerationPolicy.model_validate(body.model_dump(exclude={"expected_revision"}))
        with self.store.transaction() as db:
            revision, _ = read_policy(db)
            if body.expected_revision != revision:
                raise MasterConflict("Generation settings changed. Reload before saving.")
            db.execute(
                "INSERT OR REPLACE INTO generation_policy VALUES(1,?,?,?)",
                (revision + 1, policy.model_dump_json(), utcnow().isoformat()),
            )
            # Cancel only unstarted automatic work; manual requests remain available.
            for row in db.execute(
                "SELECT * FROM tasks WHERE kind='tailored_resume' AND status='pending'"
            ).fetchall():
                if not task_allowed(db, row):
                    db.execute(
                        "UPDATE tasks SET status='cancelled',error='Automation disabled "
                        "or job no longer qualifies',updated=? WHERE id=?",
                        (utcnow().timestamp(), row["id"]),
                    )
        self.reconcile()
        return self.view()

    def reconcile(self) -> int:
        with self.store.connection() as db:
            _, policy = read_policy(db)
            if not policy.enabled:
                return 0
            jobs = [row_job(row) for row in db.execute("SELECT * FROM jobs WHERE status='open'")]
            ids = [job.id for job in jobs if qualifies(db, job, policy)]
        count = 0
        for job_id in ids:
            try:
                _, _, snapshot, revision = self.tailored.identity(job_id)
                self.tailored.request(job_id, snapshot.revision, revision, automatic=True)
                count += 1
            except (ValueError, KeyError, OSError, AutomationDenied):
                # Unready profile/model does not block collection or manual setup.
                continue
        return count
