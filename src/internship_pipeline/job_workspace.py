"""Owner review state and authoritative bounded SQLite job queries."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any

from internship_pipeline.assessments import current_revisions, resolved_model, rubric_revision

VIEWS = {"All", "Recommendations", "Needs review", "Saved", "Applied", "Rejected"}
SORTS = {
    "postedAt": "julianday(json_extract(j.data,'$.posting.published_at'))",
    "firstObservedAt": "j.first_seen",
    "company": "NULLIF(trim(json_extract(j.data,'$.posting.company')),'') COLLATE NOCASE",
    "title": "NULLIF(trim(json_extract(j.data,'$.posting.title')),'') COLLATE NOCASE",
    "location": "NULLIF(trim((SELECT group_concat(value, ', ') FROM "
    "json_each(j.data,'$.posting.locations'))),'') COLLATE NOCASE",
    "deadline": "julianday(json_extract(j.data,'$.posting.deadline'))",
    "score": "json_extract(a.result,'$.normalized_fit')",
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS job_workspace (
 job_id TEXT PRIMARY KEY REFERENCES jobs(id), notes TEXT NOT NULL DEFAULT '',
 saved INTEGER NOT NULL DEFAULT 0, dismissed INTEGER NOT NULL DEFAULT 0,
 decision TEXT, reason TEXT NOT NULL DEFAULT '', updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS job_decision_history (
 id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
 decision TEXT, reason TEXT NOT NULL, assessment_identity TEXT, at REAL NOT NULL
);
"""


def initialize(path: Any) -> None:
    if not path.exists():
        return
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)


def state(db: sqlite3.Connection, job_id: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT notes,saved,dismissed,decision,reason,updated FROM job_workspace WHERE job_id=?",
        (job_id,),
    ).fetchone()
    result = (
        dict(row)
        if row
        else {
            "notes": "",
            "saved": False,
            "dismissed": False,
            "decision": None,
            "reason": "",
            "updated": None,
        }
    )
    result["saved"] = bool(result["saved"])
    result["dismissed"] = bool(result["dismissed"])
    result["history"] = [
        dict(r)
        for r in db.execute(
            "SELECT decision,reason,assessment_identity,at FROM "
            "job_decision_history WHERE job_id=? ORDER BY id DESC LIMIT 100",
            (job_id,),
        )
    ]
    return result


def update(path: Any, job_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"notes", "saved", "dismissed", "decision", "reason"}
    if not body or set(body) - allowed:
        raise ValueError("Choose notes, saved, dismissed, or a decision override")
    for key in ("saved", "dismissed"):
        if key in body and type(body[key]) is not bool:
            raise ValueError(f"{key} must be a boolean")
    for key, limit in (("notes", 10000), ("reason", 2000)):
        if key in body and (not isinstance(body[key], str) or len(body[key]) > limit):
            raise ValueError(f"{key} must be text of at most {limit} characters")
    if "reason" in body and "decision" not in body:
        raise ValueError("A reason must accompany a recorded decision")
    if "decision" in body and body["decision"] not in {None, "recommended", "review", "rejected"}:
        raise ValueError("Invalid decision override")
    if "decision" in body and not body.get("reason", "").strip():
        raise ValueError("A reason is required to record or clear an override")
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        now = time.time()
        db.execute("INSERT OR IGNORE INTO job_workspace(job_id,updated) VALUES(?,?)", (job_id, now))
        for key, value in body.items():
            db.execute(
                f"UPDATE job_workspace SET {key}=?,updated=? WHERE job_id=?", (value, now, job_id)
            )
        if "decision" in body:
            from internship_pipeline.assessments import current_identity
            from internship_pipeline.models import Job

            identity = current_identity(db, Job.model_validate_json(row[0]))
            db.execute(
                "INSERT INTO "
                "job_decision_history(job_id,decision,reason,assessment_identity,at) "
                "VALUES(?,?,?,?,?)",
                (job_id, body["decision"], body["reason"], identity, now),
            )
        return state(db, job_id)


def page(
    db: sqlite3.Connection,
    *,
    number: int,
    size: int,
    search: str,
    view: str,
    sort: str,
    direction: str,
) -> tuple[list[str], int, int]:
    if (
        number < 1
        or size not in {25, 50, 100}
        or len(search) > 200
        or view not in VIEWS
        or sort not in SORTS
        or direction not in {"asc", "desc"}
    ):
        raise ValueError("Invalid jobs query")
    profile, model = current_revisions(db)
    effective, rubric = resolved_model(db, model), rubric_revision()

    def fingerprint(job_id: str, content_hash: str, opening: int) -> str:
        return hashlib.sha256(
            json.dumps([job_id, content_hash, opening, profile, model, effective, rubric]).encode()
        ).hexdigest()

    db.create_function("assessment_identity", 3, fingerprint, deterministic=True)
    joined = (
        " FROM jobs j LEFT JOIN job_workspace w ON w.job_id=j.id LEFT JOIN "
        "assessments a ON "
        "a.identity=assessment_identity(j.id,j.content_hash,COALESCE(json_extract(j.data,'$.opening_revision'),0))"
    )
    applied = "json_extract(j.data,'$.applied_at') IS NOT NULL"
    decision = "COALESCE(w.decision,json_extract(a.result,'$.recommendation'),'review')"
    filters = ["1=1"]
    params: list[Any] = []
    if search:
        filters.append(
            "instr(lower(json_extract(j.data,'$.posting.title') || ' ' || "
            "json_extract(j.data,'$.posting.company') || ' ' || "
            "json_extract(j.data,'$.posting.locations')),lower(?))>0"
        )
        params.append(search)
    if view == "Applied":
        filters.append(applied)
    elif view == "Saved":
        filters.append("w.saved=1")
    elif view == "Rejected":
        filters.append(f"(w.dismissed=1 OR {decision}='rejected')")
    elif view in {"Recommendations", "Needs review"}:
        filters.extend(
            ["j.status='open'", f"NOT ({applied})", "COALESCE(w.dismissed,0)=0", f"{decision}=?"]
        )
        params.append("recommended" if view == "Recommendations" else "review")
    where = " WHERE " + " AND ".join(filters)
    total = db.execute("SELECT COUNT(*)" + joined + where, params).fetchone()[0]
    number = min(number, max(1, (total + size - 1) // size))
    field = SORTS[sort]
    ids = [
        r[0]
        for r in db.execute(
            "SELECT j.id"
            + joined
            + where
            + f" ORDER BY ({field}) IS NULL, {field} {direction}, j.id ASC LIMIT ? OFFSET ?",
            [*params, size, (number - 1) * size],
        )
    ]
    return ids, total, number
