"""Atomic per-run model admission; unknown usage retains its reservation."""

from __future__ import annotations

import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS run_reservations (
 id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, job_id TEXT NOT NULL,
 operation TEXT NOT NULL, reserved_tokens INTEGER NOT NULL,
 started REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 input_tokens INTEGER, output_tokens INTEGER);
"""


class RunLimitError(RuntimeError):
    pass


def latest_run(db: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='saved_searches'").fetchone():
        return None
    row: sqlite3.Row | None = db.execute(
        "SELECT r.* FROM search_runs r JOIN search_run_jobs j ON j.run_id=r.id "
        "WHERE j.job_id=? ORDER BY r.created DESC,r.id DESC LIMIT 1",
        (job_id,),
    ).fetchone()
    return row


def run_admission(db: sqlite3.Connection, job_id: str) -> bool:
    row = latest_run(db, job_id)
    if row is None:
        return True
    if row["cancelled"]:
        return False
    return (
        bool(row["review_backlog"])
        or not db.execute(
            "SELECT 1 FROM jobs WHERE id=? AND json_extract(data,'$.event')='backlog'", (job_id,)
        ).fetchone()
    )


def reserve(
    db: sqlite3.Connection, job_id: str, operation: str, reserved_tokens: int
) -> int | None:
    row = latest_run(db, job_id)
    if row is None:
        return None
    if row["cancelled"]:
        raise RunLimitError("run_cancelled")
    if not run_admission(db, job_id):
        raise RunLimitError("backlog_review_required")
    calls, tokens = db.execute(
        "SELECT COUNT(*),COALESCE(SUM(MAX(reserved_tokens,COALESCE(input_tokens,0)+"
        "COALESCE(output_tokens,0))),0) FROM run_reservations WHERE run_id=?",
        (row["id"],),
    ).fetchone()
    existing = db.execute(
        "SELECT 1 FROM run_reservations WHERE run_id=? AND job_id=?", (row["id"], job_id)
    ).fetchone()
    jobs = db.execute(
        "SELECT COUNT(DISTINCT job_id) FROM run_reservations WHERE run_id=?", (row["id"],)
    ).fetchone()[0]
    code = (
        "run_work_limit"
        if not existing and jobs >= row["max_jobs"]
        else "run_call_limit"
        if calls >= row["max_calls"]
        else "run_token_limit"
        if tokens + reserved_tokens > row["max_tokens"]
        else None
    )
    if code:
        raise RunLimitError(code)
    return db.execute(
        "INSERT INTO run_reservations(run_id,job_id,operation,reserved_tokens,started) "
        "VALUES(?,?,?,?,?)",
        (row["id"], job_id, operation, reserved_tokens, time.time()),
    ).lastrowid


def finish(
    db: sqlite3.Connection,
    reservation: int | None,
    status: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> None:
    if reservation is not None:
        db.execute(
            "UPDATE run_reservations SET status=?,input_tokens=?,output_tokens=? WHERE id=?",
            (status, input_tokens, output_tokens, reservation),
        )
