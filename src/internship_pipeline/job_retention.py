"""Discard untracked non-internships while preserving owner work and usage accounting."""

from __future__ import annotations

import json

from internship_pipeline.internships import is_internship
from internship_pipeline.models import FetchResult
from internship_pipeline.storage import Store


def discard_non_internships(store: Store, *, dry_run: bool = False) -> dict[str, int]:
    """Run at startup before workers, or explicitly through the maintenance command."""
    with store.transaction() as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        protected: set[str] = set()
        if "job_workspace" in tables:
            protected.update(
                row[0]
                for row in db.execute(
                    "SELECT job_id FROM job_workspace WHERE "
                    "saved=1 OR dismissed=1 OR decision IS NOT NULL OR notes<>''"
                )
            )
        for table in (
            "job_decision_history",
            "tailored_resumes",
            "email_members",
            "sheets_checkpoints",
            "sheets_journal",
            "sheets_inward",
        ):
            if table in tables:
                protected.update(row[0] for row in db.execute(f"SELECT job_id FROM {table}"))
        protected.update(
            row[0]
            for row in db.execute(
                "SELECT json_extract(payload,'$.job_id') FROM tasks WHERE status='running'"
            )
        )
        db.execute("CREATE TEMP TABLE discarded_jobs (id TEXT PRIMARY KEY)")
        counts = {"discarded": 0, "preserved": 0}
        for row in db.execute("SELECT id,data FROM jobs"):
            data = json.loads(row["data"])
            posting = data["posting"]
            if is_internship(posting["title"], posting.get("description")):
                continue
            if row["id"] in protected or data.get("applied_at"):
                counts["preserved"] += 1
            else:
                counts["discarded"] += 1
                db.execute("INSERT INTO discarded_jobs VALUES(?)", (row["id"],))
        if dry_run:
            return counts

        for table in (
            "observations",
            "matches",
            "assessments",
            "events",
            "job_workspace",
            "job_decision_history",
            "search_run_jobs",
        ):
            if table in tables:
                db.execute(f"DELETE FROM {table} WHERE job_id IN (SELECT id FROM discarded_jobs)")
        db.execute(
            "DELETE FROM tasks WHERE json_extract(payload,'$.job_id') "
            "IN (SELECT id FROM discarded_jobs)"
        )
        # Attempts and run reservations retain token/call accounting, not posting text.
        db.execute("DELETE FROM jobs WHERE id IN (SELECT id FROM discarded_jobs)")
        if "search_runs" in tables:
            # An interrupted collection can also contain descriptions in its checkpoint.
            for row in db.execute("SELECT id,result FROM search_runs WHERE result IS NOT NULL"):
                result = FetchResult.model_validate_json(row["result"])
                retained = [p for p in result.jobs if is_internship(p.title, p.description)]
                if len(retained) != len(result.jobs):
                    db.execute(
                        "UPDATE search_runs SET result=? WHERE id=?",
                        (result.model_copy(update={"jobs": retained}).model_dump_json(), row["id"]),
                    )
        return counts
