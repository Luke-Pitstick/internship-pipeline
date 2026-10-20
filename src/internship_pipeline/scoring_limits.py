"""Owner-controlled rolling scoring budgets, independent of model identities."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from pydantic import Field

from internship_pipeline.models import Record
from internship_pipeline.storage import Store


class ScoringLimits(Record):
    hourly_calls: int = Field(default=60, ge=1, le=1_000_000, strict=True)
    daily_calls: int = Field(default=200, ge=1, le=1_000_000, strict=True)
    daily_tokens: int = Field(default=5_000_000, ge=1, le=1_000_000_000_000, strict=True)


class SaveScoringLimits(ScoringLimits):
    expected_revision: int = Field(ge=0, strict=True)


class ScoringLimitsConflict(ValueError):
    pass


def read_limits(db: sqlite3.Connection) -> tuple[int, ScoringLimits]:
    row = db.execute("SELECT revision,data FROM scoring_limits WHERE id=1").fetchone()
    return (row[0], ScoringLimits.model_validate_json(row[1])) if row else (0, ScoringLimits())


class ScoringSettings:
    def __init__(self, store: Store):
        self.store = store

    def view(self) -> dict[str, Any]:
        now = time.time()
        with self.store.connection() as db:
            revision, limits = read_limits(db)
            hourly = db.execute(
                "SELECT COUNT(*) FROM assessment_attempts WHERE started>?", (now - 3600,)
            ).fetchone()[0]
            daily = db.execute(
                "SELECT COUNT(*),COALESCE(SUM(CASE WHEN input_tokens IS NULL "
                "OR output_tokens IS NULL THEN reserved_tokens "
                "ELSE input_tokens+output_tokens END),0) "
                "FROM assessment_attempts WHERE started>?",
                (now - 86400,),
            ).fetchone()
            paused = db.execute(
                "SELECT COUNT(DISTINCT json_extract(payload,'$.job_id')),MIN(available_at) "
                "FROM tasks WHERE kind='match' AND status='pending' "
                "AND error='evaluation_budget_exhausted'"
            ).fetchone()
        return {
            "revision": revision,
            "limits": limits.model_dump(),
            "usage": {"hourly_calls": hourly, "daily_calls": daily[0], "daily_tokens": daily[1]},
            "paused_jobs": paused[0],
            "resumes_at": paused[1],
        }

    def save(self, body: SaveScoringLimits) -> dict[str, Any]:
        limits = ScoringLimits.model_validate(body.model_dump(exclude={"expected_revision"}))
        with self.store.transaction() as db:
            revision, _ = read_limits(db)
            if body.expected_revision != revision:
                raise ScoringLimitsConflict("Scoring limits changed. Reload before saving.")
            db.execute(
                "INSERT OR REPLACE INTO scoring_limits VALUES(1,?,?)",
                (revision + 1, limits.model_dump_json()),
            )
            # Wake budget waits only. The worker rechecks all limits before provider I/O.
            now = time.time()
            db.execute(
                "UPDATE tasks SET available_at=?,updated=?,error=NULL "
                "WHERE kind='match' AND status='pending' "
                "AND error='evaluation_budget_exhausted'",
                (now, now),
            )
        return self.view()
