from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from internship_pipeline import dashboard_api
from internship_pipeline.dashboard_api import DashboardAPI, DashboardUnavailable
from internship_pipeline.models import Job, ResumeArtifact, Settings, SourceJob, utcnow
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
            "error) VALUES('resume','resume:synthetic',?,'failed',?,?,?,?)",
            (PRIVATE, utcnow().timestamp(), utcnow().timestamp(), utcnow().timestamp(), PRIVATE),
        )
    return DashboardAPI(settings)


def register_pdf(
    api: DashboardAPI,
    path: Path,
    job_id: str = "relevant",
    key: str = "artifact",
    engine: str = "legacy-resume-matcher",
) -> None:
    artifact = ResumeArtifact(
        key=key,
        job_id=job_id,
        pdf_path=path,
        resume_id=PRIVATE,
        change_summary=[PRIVATE],
        review_warnings=[PRIVATE],
        engine=engine,
    )
    with sqlite3.connect(api.settings.database_path) as connection:
        connection.execute(
            "INSERT INTO artifacts VALUES(?,?,?)", (key, job_id, artifact.model_dump_json())
        )


def test_jobs_are_read_without_matching_or_exposing_candidate_facts(api: DashboardAPI) -> None:
    before = api.settings.database_path.read_bytes()
    data = api.jobs()
    assert data["scope"] == {
        "raw_collected": 5,
        "screened_open": 5,
        "screened_applied_closed": 0,
        "limit": 1000,
        "returned": 5,
    }
    assert len(data["jobs"]) == 5
    item = next(item for item in data["jobs"] if item["id"] == "relevant")
    assert item["application_url"] == "https://example.test/jobs/relevant"
    assert item["locations"] == ["United States"]
    assert item["term"] == ["Summer 2027"]
    assert item["description"] == "Build software with Python."
    assert item["assessment"] == "pending"
    assert item["timestamp_kind"] == "source_time_ambiguous"
    assert item["unknowns"] == []
    assert item["resume"]["available"] is False
    assert data["health"]["status"] == "degraded"
    assert data["health"]["queues"] == [{"kind": "resume", "status": "failed", "count": 1}]
    assert PRIVATE not in json.dumps(data)
    assert api.settings.database_path.read_bytes() == before


@pytest.mark.parametrize(
    ("engine", "status"),
    [
        ("legacy-resume-matcher", "legacy_preview_requires_review"),
        ("original-latex", "draft_requires_review"),
    ],
)
def test_existing_pdf_status_identifies_engine_and_download_is_db_backed(
    api: DashboardAPI, engine: str, status: str
) -> None:
    pdf = b"%PDF-1.7\nsynthetic PDF bytes"
    path = api.settings.artifact_dir / "private-name.pdf"
    path.write_bytes(pdf)
    register_pdf(api, path, engine=engine)
    metadata = next(item for item in api.jobs()["jobs"] if item["id"] == "relevant")["resume"]
    assert metadata["available"] is True
    assert metadata["download_path"] == "/api/resumes/relevant"
    assert metadata["status"] == status
    assert metadata["engine"] == engine
    assert metadata["review_warnings"] == [
        "Additional stored review warnings need private review of the PDF."
    ]
    assert api.resume("relevant") == pdf
    assert PRIVATE not in json.dumps(metadata)
    assert "private-name.pdf" not in json.dumps(metadata)
    assert api.resume("../private-name.pdf") is None
    assert api.resume("%2e%2e%2fprivate-name.pdf") is None
    assert api.resume("unknown") is None


def test_saved_artifacts_without_engine_are_labeled_legacy(api: DashboardAPI) -> None:
    path = api.settings.artifact_dir / "resume.pdf"
    path.write_bytes(b"%PDF-1.7\nsynthetic")
    register_pdf(api, path)
    with sqlite3.connect(api.settings.database_path) as connection:
        payload = json.loads(
            connection.execute("SELECT data FROM artifacts WHERE key='artifact'").fetchone()[0]
        )
        payload.pop("engine")
        connection.execute(
            "UPDATE artifacts SET data=? WHERE key='artifact'", (json.dumps(payload),)
        )
    resume = next(item for item in api.jobs()["jobs"] if item["id"] == "relevant")["resume"]
    assert resume["engine"] == "legacy-resume-matcher"
    assert resume["status"] == "legacy_preview_requires_review"


@pytest.mark.parametrize("unsafe", ["outside", "symlink", "invalid", "missing", "directory"])
def test_unavailable_or_unsafe_artifacts_cannot_be_downloaded(
    api: DashboardAPI, unsafe: str
) -> None:
    root = api.settings.artifact_dir
    path = root / "resume.pdf"
    if unsafe == "outside":
        path = root.parent / "outside.pdf"
        path.write_bytes(b"%PDF-1.7")
    elif unsafe == "symlink":
        target = root.parent / "outside.pdf"
        target.write_bytes(b"%PDF-1.7")
        path.symlink_to(target)
    elif unsafe == "invalid":
        path.write_text("Not a PDF")
    elif unsafe == "directory":
        path.mkdir()
    register_pdf(api, path)
    assert api.resume("relevant") is None
    assert (
        next(item for item in api.jobs()["jobs"] if item["id"] == "relevant")["resume"]["available"]
        is False
    )


def test_missing_database_fails_closed(api: DashboardAPI) -> None:
    api.settings.database_path.unlink()
    with pytest.raises(DashboardUnavailable, match="temporarily unavailable"):
        api.jobs()
    assert not api.settings.database_path.exists()


def test_absent_profile_does_not_block_inventory(api: DashboardAPI) -> None:
    assert len(api.jobs()["jobs"]) == 5


def test_resume_pause_is_truthful(api: DashboardAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESUME_GENERATION_PAUSED", "1")
    data = api.jobs()
    assert data["health"]["resume_generation_paused"] is True
    assert data["jobs"][0]["resume"]["status"] == "awaiting_latex_source"


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


def test_review_warnings_preserve_known_validation_messages_without_private_text() -> None:
    warning = "Semantic grounding is unverified; review rewritten claims against factual experience"
    artifact = ResumeArtifact(
        key="test",
        job_id="job",
        pdf_path=Path("test.pdf"),
        resume_id="resume",
        review_warnings=[warning, PRIVATE],
    )
    result = dashboard_api.review_warnings(artifact)
    assert warning in result
    assert PRIVATE not in json.dumps(result)


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
    assert data["scope"]["screened_open"] == 4


def test_mark_applied_does_not_create_missing_database(api: DashboardAPI) -> None:
    api.settings.database_path.unlink()
    with pytest.raises(DashboardUnavailable):
        api.mark_applied("relevant")
    assert not api.settings.database_path.exists()
