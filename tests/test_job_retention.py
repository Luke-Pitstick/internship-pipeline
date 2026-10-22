from __future__ import annotations

import json

import pytest
from test_storage import NOW, posting, setup_store

from internship_pipeline.job_retention import discard_non_internships
from internship_pipeline.job_workspace import initialize, update
from internship_pipeline.models import FetchResult


def test_ingestion_discards_non_internships_before_observations_and_tasks(tmp_path):
    store = setup_store(tmp_path / "state.sqlite3")
    store.ingest("acme", FetchResult(), "p1", NOW)
    result = FetchResult(
        jobs=[
            posting("fulltime", title="Senior Engineer", description="Permanent full-time role."),
            posting("intern"),
        ]
    )
    assert [job.posting.source_id for job in store.ingest("acme", result, "p1", NOW)] == ["intern"]
    store.ingest("acme", result, "p1", NOW)
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    # Discarding is not a permanent blacklist: a corrected posting can qualify later.
    assert len(store.ingest("acme", FetchResult(jobs=[posting("fulltime")]), "p1", NOW)) == 1


def test_cleanup_preserves_owner_work_and_usage_but_removes_job_dependencies(tmp_path, monkeypatch):
    store = setup_store(tmp_path / "state.sqlite3")
    store.ingest("acme", FetchResult(), "p1", NOW)
    with monkeypatch.context() as patch:
        patch.setattr("internship_pipeline.internships.is_internship", lambda *args: True)
        jobs = store.ingest(
            "acme",
            FetchResult(
                jobs=[
                    posting(name, title="Engineer", description="Permanent role.")
                    for name in ("discard", "saved", "applied", "notes", "working", "resume")
                ]
            ),
            "p1",
            NOW,
        )
    by_source = {job.posting.source_id: job for job in jobs}
    initialize(store.path)
    update(store.path, by_source["saved"].id, {"saved": True})
    update(store.path, by_source["notes"].id, {"notes": "Follow up"})
    store.mark_applied(by_source["applied"].id)
    discard_id = by_source["discard"].id
    with store.transaction() as db:
        db.execute(
            "UPDATE tasks SET status='running' WHERE json_extract(payload,'$.job_id')=?",
            (by_source["working"].id,),
        )
        db.execute("CREATE TABLE tailored_resumes (job_id TEXT)")
        db.execute("INSERT INTO tailored_resumes VALUES(?)", (by_source["resume"].id,))
        db.execute("INSERT INTO assessments VALUES('assessment',?,'{}',0)", (discard_id,))
        db.execute(
            "INSERT INTO assessment_attempts(identity,job_id,started,status,reserved_tokens) "
            "VALUES('assessment',?,0,'success',100)",
            (discard_id,),
        )
        db.execute("CREATE TABLE search_runs (id TEXT PRIMARY KEY, result TEXT)")
        db.execute(
            "INSERT INTO search_runs VALUES('run',?)",
            (
                FetchResult(
                    jobs=[
                        posting("bad", title="Engineer", description="Full-time"),
                        posting("good"),
                    ]
                ).model_dump_json(),
            ),
        )
        db.execute("CREATE TABLE search_run_jobs (run_id TEXT,job_id TEXT REFERENCES jobs(id))")
        db.execute("INSERT INTO search_run_jobs VALUES('run',?)", (discard_id,))
    assert discard_non_internships(store, dry_run=True) == {"discarded": 1, "preserved": 5}
    assert store.get_job(discard_id) is not None
    assert discard_non_internships(store) == {"discarded": 1, "preserved": 5}
    with pytest.raises(KeyError):
        store.get_job(discard_id)
    with store.connection() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        for table in ("observations", "assessments", "search_run_jobs"):
            assert (
                db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE job_id=?", (discard_id,)
                ).fetchone()[0]
                == 0
            )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM tasks WHERE json_extract(payload,'$.job_id')=?", (discard_id,)
            ).fetchone()[0]
            == 0
        )
        assert db.execute("SELECT reserved_tokens FROM assessment_attempts").fetchone()[0] == 100
        checkpoint = json.loads(db.execute("SELECT result FROM search_runs").fetchone()[0])
        assert [p["source_id"] for p in checkpoint["jobs"]] == ["good"]
    assert discard_non_internships(store) == {"discarded": 0, "preserved": 5}
