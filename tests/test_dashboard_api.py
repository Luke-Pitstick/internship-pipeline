from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from internship_pipeline import dashboard_api
from internship_pipeline.dashboard_api import DashboardAPI, DashboardUnavailable
from internship_pipeline.models import Job, Settings, SourceJob, utcnow
from internship_pipeline.storage import SCHEMA

PRIVATE = "PRIVATE_CONTACT_FACT_AND_SECRET_SENTINEL"


def job(job_id: str, title: str = "Software Engineering Intern Summer 2027", **posting) -> Job:
    return Job(
        id=job_id,
        content_hash=job_id,
        posting=SourceJob(
            source="synthetic",
            source_id=job_id,
            board_id="board",
            company="Synthetic Corp",
            title=title,
            apply_url="https://example.test/jobs/" + job_id,
            description=posting.pop("description", "Build software with Python."),
            locations=["United States"],
            timestamp_kind="source_time_ambiguous",
            **posting,
        ),
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
        last_verified_at=utcnow(),
        event="backlog",
    )


@pytest.fixture
def api(tmp_path: Path) -> DashboardAPI:
    settings = Settings(
        database_path=tmp_path / "state.sqlite3",
        artifact_dir=tmp_path / "artifacts",
    )
    settings.artifact_dir.mkdir()
    jobs = [
        job("relevant"),
        job("fulltime", "Software Engineer"),
        job("nonsoftware", "Structural Engineering Intern", description="Python for CAD analysis"),
        job("noskills", description="Build software using Rust."),
        job("wrongcountry", description="Build software with Python.").model_copy(
            update={"posting": job("country").posting.model_copy(update={"locations": ["Canada"]})}
        ),
    ]
    with sqlite3.connect(settings.database_path) as connection:
        connection.executescript(SCHEMA)
        for item in jobs:
            connection.execute(
                "INSERT INTO jobs(id,data,canonical_url,company_key,content_hash,status,"
                "first_seen,last_seen) VALUES(?,?,?,?,?,'open',?,?)",
                (
                    item.id,
                    item.model_dump_json(),
                    item.posting.apply_url,
                    "synthetic",
                    item.content_hash,
                    item.first_seen_at.timestamp(),
                    item.last_seen_at.timestamp(),
                ),
            )
        connection.execute(
            "INSERT INTO targets(id,kind,config,provider,last_success,next_due) "
            "VALUES('board','company',?,'greenhouse',?,?)",
            (PRIVATE, utcnow().timestamp(), utcnow().timestamp() + 300),
        )
        connection.execute(
            "INSERT INTO tasks(kind,key,payload,status,available_at,created,updated,"
            "error) VALUES('tailored_resume','tailored:synthetic',?,'failed',?,?,?,?)",
            (PRIVATE, utcnow().timestamp(), utcnow().timestamp(), utcnow().timestamp(), PRIVATE),
        )
    return DashboardAPI(settings)


def test_jobs_are_read_without_matching_or_exposing_candidate_facts(api: DashboardAPI) -> None:
    before = api.settings.database_path.read_bytes()
    data = api.jobs()
    assert data["scope"] == {
        "raw_collected": 5,
        "screened_open": 4,
        "screened_applied_closed": 0,
        "limit": 25,
        "returned": 4,
    }
    assert len(data["jobs"]) == 4
    item = next(item for item in data["jobs"] if item["id"] == "relevant")
    assert item["application_url"] == "https://example.test/jobs/relevant"
    assert item["locations"] == ["United States"]
    assert item["term"] == ["Summer 2027"]
    assert item["description"] == "Build software with Python."
    assert item["assessment"] == "pending"
    assert item["timestamp_kind"] == "source_time_ambiguous"
    assert item["unknowns"] == []
    assert data["health"]["status"] == "degraded"
    assert data["health"]["queues"] == [{"kind": "tailored_resume", "status": "failed", "count": 1}]
    assert PRIVATE not in json.dumps(data)
    assert api.settings.database_path.read_bytes() == before


def test_missing_database_fails_closed(api: DashboardAPI) -> None:
    api.settings.database_path.unlink()
    with pytest.raises(DashboardUnavailable, match="temporarily unavailable"):
        api.jobs()
    assert not api.settings.database_path.exists()


def test_absent_profile_does_not_block_inventory(api: DashboardAPI) -> None:
    assert len(api.jobs()["jobs"]) == 4


def test_html_description_becomes_plaintext_with_paragraph_breaks() -> None:
    result, truncated = dashboard_api.plain_description(
        "<p>Build <strong>Python</strong> tools &amp; APIs.</p>"
        "<p>Second paragraph.<br>Another line.</p>"
        "<script>PRIVATE_SCRIPT</script><style>PRIVATE_STYLE</style>"
    )
    assert result == "Build Python tools & APIs.\n\nSecond paragraph.\nAnother line."
    assert not truncated
    assert "PRIVATE" not in result
    result, truncated = dashboard_api.plain_description("x" * 40000)
    assert len(result) == 30000
    assert truncated


def test_mark_applied_is_idempotent_and_invalidates_cached_jobs(api: DashboardAPI) -> None:
    assert (
        next(item for item in api.jobs()["jobs"] if item["id"] == "relevant")["applied_at"] is None
    )
    first = api.mark_applied("relevant")
    assert first is not None
    assert first["status"] == "applied"
    assert api.mark_applied("relevant") == first
    current = next(item for item in api.jobs()["jobs"] if item["id"] == "relevant")
    assert current["applied_at"] == first["applied_at"]
    assert current["application_status"] == "applied"
    with sqlite3.connect(api.settings.database_path) as connection:
        stored = Job.model_validate_json(
            connection.execute("SELECT data FROM jobs WHERE id='relevant'").fetchone()[0]
        )
    assert stored.applied_at is not None
    assert stored.applied_at.isoformat() == first["applied_at"]
    assert api.mark_applied("unknown") is None
    assert api.mark_applied("../relevant") is None


def test_applied_jobs_remain_visible_after_source_closes(api: DashboardAPI) -> None:
    api.mark_applied("relevant")
    with sqlite3.connect(api.settings.database_path) as connection:
        data = json.loads(
            connection.execute("SELECT data FROM jobs WHERE id='relevant'").fetchone()[0]
        )
        data["status"] = "closed"
        connection.execute(
            "UPDATE jobs SET status='closed',data=? WHERE id='relevant'", (json.dumps(data),)
        )
    data = api.jobs()
    assert next(item for item in data["jobs"] if item["id"] == "relevant")["status"] == "closed"
    assert (
        next(item for item in data["jobs"] if item["id"] == "relevant")["application_status"]
        == "applied"
    )
    assert data["scope"]["screened_applied_closed"] == 1
    assert data["scope"]["screened_open"] == 3


def test_mark_applied_does_not_create_missing_database(api: DashboardAPI) -> None:
    api.settings.database_path.unlink()
    with pytest.raises(DashboardUnavailable):
        api.mark_applied("relevant")
    assert not api.settings.database_path.exists()


def test_job_scope_is_reused_and_changed_content_is_reclassified(api, monkeypatch):
    from internship_pipeline import job_workspace

    classify = job_workspace.is_internship
    calls = []

    def counted(title, description):
        calls.append(title)
        return classify(title, description)

    monkeypatch.setattr(job_workspace, "is_internship", counted)
    assert api.jobs()["pagination"]["total"] == 4
    assert len(calls) == 5  # COUNT and page selection share the classification.
    api.jobs(view="Needs review")
    api.jobs(sort="company")
    assert len(calls) == 5

    with sqlite3.connect(api.settings.database_path) as db:
        item = Job.model_validate_json(
            db.execute("SELECT data FROM jobs WHERE id='fulltime'").fetchone()[0]
        )
        item.posting.title = "Software Intern"
        item.content_hash = "changed-content"
        db.execute(
            "UPDATE jobs SET data=?,content_hash=? WHERE id=?",
            (item.model_dump_json(), item.content_hash, item.id),
        )
    assert api.jobs()["pagination"]["total"] == 5
    assert len(calls) == 6


def test_job_scope_cache_evicts_old_content(monkeypatch):
    from internship_pipeline import job_workspace

    calls = []

    def classify(title, description):
        calls.append(title)
        return title == "Intern"

    monkeypatch.setattr(job_workspace, "is_internship", classify)
    scope = job_workspace.InternshipScope(capacity=2)
    assert scope.classify("one", "Intern", "")
    assert not scope.classify("two", "Engineer", "")
    assert scope.classify("one", "Intern", "")
    assert scope.classify("three", "Intern", "")
    assert len(calls) == 3
    assert not scope.classify("two", "Engineer", "")
    assert len(calls) == 4
