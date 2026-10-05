import json
from pathlib import Path

from internship_pipeline.demo import DemoGenerator, run_demo
from internship_pipeline.models import (
    CandidateProfile,
    ExperienceFact,
    FetchResult,
    Settings,
    SourceJob,
)
from internship_pipeline.pipeline import Pipeline
from internship_pipeline.storage import Store


def configured_pipeline(tmp_path: Path) -> tuple[Pipeline, DemoGenerator]:
    settings = Settings(
        database_path=tmp_path / "db.sqlite",
        artifact_dir=tmp_path / "artifacts",
        recording_notifications_path=tmp_path / "messages.jsonl",
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
    generator = DemoGenerator(settings.artifact_dir)
    return Pipeline(settings, profile, store, resume_service=generator), generator


def test_complete_pipeline_and_repeat_are_idempotent(tmp_path: Path) -> None:
    pipeline, generator = configured_pipeline(tmp_path)
    assert pipeline.drain() == 4
    assert pipeline.drain() == 0
    messages = [json.loads(line) for line in (tmp_path / "messages.jsonl").read_text().splitlines()]
    assert len(messages) == 2
    assert messages[0]["attachment"] is None
    assert Path(messages[1]["attachment"]).is_file()
    assert generator.calls == 1
    assert pipeline.store.list_jobs()[0].applied_at is None


def test_failed_generation_keeps_opening_and_retries_without_resending_it(tmp_path: Path) -> None:
    pipeline, generator = configured_pipeline(tmp_path)
    original = generator.generate

    def fail_once(*args, **kwargs):
        generator.generate = original
        raise TimeoutError()

    generator.generate = fail_once
    pipeline.drain()
    assert len((tmp_path / "messages.jsonl").read_text().splitlines()) == 1
    with pipeline.store.transaction() as connection:
        connection.execute("UPDATE tasks SET available_at=0 WHERE status='pending'")
    pipeline.drain()
    assert len((tmp_path / "messages.jsonl").read_text().splitlines()) == 2
    assert generator.calls == 1


def test_failed_delivery_reuses_pdf_without_rerunning_generation(tmp_path: Path) -> None:
    pipeline, generator = configured_pipeline(tmp_path)
    calls = []

    def notify(url, title, body, attachment):
        calls.append(attachment)
        return attachment is None or len(calls) > 2

    pipeline.destinations = {"test": "test://synthetic"}
    pipeline.notifier = notify
    pipeline.drain()
    assert generator.calls == 1
    with pipeline.store.transaction() as connection:
        connection.execute("UPDATE tasks SET available_at=0 WHERE status='pending'")
    pipeline.drain()
    assert generator.calls == 1
    assert len(calls) == 3
    assert pipeline.store.health()["tasks"] == {"done": 4}


def test_current_closed_state_suppresses_pending_work(tmp_path: Path) -> None:
    pipeline, generator = configured_pipeline(tmp_path)
    pipeline.store.ingest("acme", FetchResult(), pipeline.profile.revision)
    pipeline.store.ingest("acme", FetchResult(), pipeline.profile.revision)
    pipeline.drain()
    assert generator.calls == 0
    assert not (tmp_path / "messages.jsonl").exists()


def test_demo_is_explicitly_synthetic(tmp_path: Path) -> None:
    report = run_demo(tmp_path)
    assert "synthetic offline" in report["mode"]
    assert report["recorded_messages"] == 2
    assert report["generation_calls"] == 1
    assert report["repeat_scan_added_messages"] == 0


def test_failed_opening_holds_generation_without_consuming_retries(tmp_path: Path) -> None:
    pipeline, generator = configured_pipeline(tmp_path)
    pipeline.destinations = {"test": "test://synthetic"}
    pipeline.notifier = lambda *_: False
    pipeline.drain()
    assert generator.calls == 0
    with pipeline.store.connection() as connection:
        resume = connection.execute(
            "SELECT attempts,status FROM tasks WHERE kind='resume'"
        ).fetchone()
        assert dict(resume) == {"attempts": 0, "status": "pending"}
    pipeline.notifier = lambda *_: True
    with pipeline.store.transaction() as connection:
        connection.execute("UPDATE tasks SET available_at=0 WHERE status='pending'")
    pipeline.drain()
    assert generator.calls == 1
    assert pipeline.store.health()["tasks"] == {"done": 4}


def test_terminal_generation_failure_sends_actionable_notice(tmp_path: Path) -> None:
    pipeline, generator = configured_pipeline(tmp_path)
    pipeline.settings.max_attempts = 1
    pipeline.queue.max_attempts = 1

    def fail(*_):
        raise TimeoutError()

    generator.generate = fail
    pipeline.drain()
    messages = [json.loads(line) for line in (tmp_path / "messages.jsonl").read_text().splitlines()]
    assert len(messages) == 2
    assert "needs attention" in messages[1]["title"]
    assert "apply manually" in messages[1]["body"]
    assert messages[1]["attachment"] is None
    assert pipeline.store.health()["failed_tasks"][0]["error"] == "TimeoutError"


def test_verified_reopening_gets_new_alert_and_pdf(tmp_path: Path) -> None:
    pipeline, _ = configured_pipeline(tmp_path)
    pipeline.drain()
    job = pipeline.store.list_jobs()[0]
    pipeline.store.ingest("acme", FetchResult(), pipeline.profile.revision)
    pipeline.store.ingest("acme", FetchResult(), pipeline.profile.revision)
    pipeline.store.ingest("acme", FetchResult(jobs=[job.posting]), pipeline.profile.revision)
    pipeline.drain()
    messages = [json.loads(line) for line in (tmp_path / "messages.jsonl").read_text().splitlines()]
    assert len(messages) == 4
    assert "reopen" in messages[2]["title"].lower()
