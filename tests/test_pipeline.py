from pathlib import Path

from internship_pipeline.models import (
    CandidateProfile,
    ExperienceFact,
    FetchResult,
    Job,
    MatchResult,
    Settings,
    SourceJob,
)
from internship_pipeline.pipeline import Pipeline
from internship_pipeline.storage import Store


def synthetic_match(job: Job, profile: CandidateProfile, settings: Settings) -> MatchResult:
    return MatchResult(fit="possible", eligible=True, fact_ids=[fact.id for fact in profile.facts])


def configured_pipeline(tmp_path: Path) -> Pipeline:
    settings = Settings(
        database_path=tmp_path / "db.sqlite",
        artifact_dir=tmp_path / "artifacts",
    )
    profile = CandidateProfile(
        facts=[ExperienceFact(id="python", text="Built a Python project.", skills=["Python"])]
    )
    store = Store(settings.database_path)
    store.register_target("acme", "company", "{}", "ashby")
    store.ingest("acme", FetchResult(), profile.revision)
    store.ingest(
        "acme",
        FetchResult(
            jobs=[
                SourceJob(
                    source="ashby",
                    source_id="one",
                    board_id="acme",
                    company="Acme",
                    title="Software Engineering Intern",
                    description="Python software engineering internship.",
                    apply_url="https://example.invalid/apply/one",
                    employment_type="Intern",
                )
            ]
        ),
        profile.revision,
    )
    return Pipeline(settings, profile, store, matcher=synthetic_match)


def test_matching_is_idempotent_and_never_queues_integrations(tmp_path: Path) -> None:
    pipeline = configured_pipeline(tmp_path)
    assert pipeline.drain() == 1
    assert pipeline.drain() == 0
    job = pipeline.store.list_jobs()[0]
    assert pipeline.store.get_match(job, pipeline.profile.revision).accepted
    with pipeline.store.connection() as db:
        assert [row[0] for row in db.execute("SELECT kind FROM tasks")] == ["match"]
    assert job.applied_at is None


def test_failed_match_retries_without_any_integration(tmp_path: Path) -> None:
    pipeline = configured_pipeline(tmp_path)

    def unavailable(*_) -> MatchResult:
        raise TimeoutError("synthetic secret")

    pipeline.matcher = unavailable
    assert pipeline.drain() == 1
    with pipeline.store.transaction() as db:
        row = db.execute("SELECT status,error FROM tasks").fetchone()
        assert tuple(row) == ("pending", "TimeoutError")
        db.execute("UPDATE tasks SET available_at=0 WHERE status='pending'")
    pipeline.matcher = synthetic_match
    assert pipeline.drain() == 1
    assert pipeline.store.health()["tasks"] == {"done": 1}


def test_closed_or_applied_job_suppresses_pending_matching(tmp_path: Path) -> None:
    pipeline = configured_pipeline(tmp_path)
    pipeline.store.ingest("acme", FetchResult(), pipeline.profile.revision)
    pipeline.store.ingest("acme", FetchResult(), pipeline.profile.revision)
    pipeline.drain()
    job = pipeline.store.list_jobs()[0]
    assert pipeline.store.get_match(job, pipeline.profile.revision) is None
    pipeline.store.ingest("acme", FetchResult(jobs=[job.posting]), pipeline.profile.revision)
    pipeline.store.mark_applied(job.id)
    pipeline.drain()
    assert pipeline.store.get_match(job, pipeline.profile.revision) is None


def test_verified_reopening_queues_only_matching(tmp_path: Path) -> None:
    pipeline = configured_pipeline(tmp_path)
    pipeline.drain()
    job = pipeline.store.list_jobs()[0]
    pipeline.store.ingest("acme", FetchResult(), pipeline.profile.revision)
    pipeline.store.ingest("acme", FetchResult(), pipeline.profile.revision)
    pipeline.store.ingest("acme", FetchResult(jobs=[job.posting]), pipeline.profile.revision)
    assert pipeline.drain() == 1
    with pipeline.store.connection() as db:
        assert [row[0] for row in db.execute("SELECT kind FROM tasks")] == ["match", "match"]
    assert pipeline.store.get_job(job.id).event == "reopened"


def test_only_current_worker_roles_and_commands_are_exposed() -> None:
    from internship_pipeline.cli import parser
    from internship_pipeline.supervisor import ROLES

    assert "delivery" not in ROLES
    assert {"email-delivery", "sheets-sync", "tailored-resumes"}.issubset(ROLES)
    for role in ROLES:
        assert parser().parse_args(["worker", role, "--once"]).role == role
