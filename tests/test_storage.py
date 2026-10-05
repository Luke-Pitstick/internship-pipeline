from datetime import UTC, datetime, timedelta
from pathlib import Path

from internship_pipeline.models import FetchResult, MatchResult, SourceJob
from internship_pipeline.storage import Store

NOW = datetime(2026, 10, 5, tzinfo=UTC)


def posting(source_id: str = "one", **updates: object) -> SourceJob:
    raw = {
        "source": "ashby",
        "source_id": source_id,
        "board_id": "acme",
        "company": "Acme",
        "title": "Software Engineering Intern",
        "apply_url": f"https://jobs.example.com/{source_id}",
        "description": "Software engineering internship using Python.",
    }
    raw.update(updates)
    return SourceJob.model_validate(raw)


def setup_store(path: Path) -> Store:
    store = Store(path)
    store.register_target("acme", "company", "{}", "ashby")
    return store


def test_baseline_and_repeated_snapshot_are_not_new_alerts(tmp_path: Path) -> None:
    store = setup_store(tmp_path / "db.sqlite")
    backlog = store.ingest("acme", FetchResult(jobs=[posting()]), "p1", NOW)
    assert backlog[0].event == "backlog"
    assert store.health()["tasks"] == {}
    store.ingest("acme", FetchResult(jobs=[posting()]), "p1", NOW + timedelta(minutes=5))
    assert len(store.list_jobs()) == 1
    assert store.health()["tasks"] == {}
    store.ingest("acme", FetchResult(jobs=[posting(), posting("two")]), "p1", NOW)
    assert store.health()["tasks"] == {"pending": 1}
    assert Store(store.path).get_job(backlog[0].id).first_seen_at == NOW


def test_cross_source_identity_deduplicates_but_same_title_does_not(tmp_path: Path) -> None:
    store = setup_store(tmp_path / "db.sqlite")
    store.ingest("acme", FetchResult(), "p1", NOW)
    store.ingest("acme", FetchResult(jobs=[posting()]), "p1", NOW)
    store.register_target("search", "search", "{}", "indeed")
    store.ingest("search", FetchResult(), "p1", NOW)
    store.ingest(
        "search",
        FetchResult(
            jobs=[
                posting(
                    "external",
                    source="jobspy",
                    apply_url="https://jobs.example.com/one?utm_source=board",
                )
            ]
        ),
        "p1",
        NOW,
    )
    assert len(store.list_jobs()) == 1
    store.ingest("acme", FetchResult(jobs=[posting(), posting("two")]), "p1", NOW)
    assert len(store.list_jobs()) == 2
    assert store.health()["tasks"] == {"pending": 2}


def test_partial_and_failed_fetches_do_not_close_jobs(tmp_path: Path) -> None:
    store = setup_store(tmp_path / "db.sqlite")
    job = store.ingest("acme", FetchResult(jobs=[posting()]), "p1", NOW)[0]
    for _ in range(3):
        store.ingest("acme", FetchResult(complete=False, error="Timeout"), "p1", NOW)
    assert store.get_job(job.id).status == "open"
    store.ingest("acme", FetchResult(), "p1", NOW)
    assert store.get_job(job.id).status == "open"
    store.ingest("acme", FetchResult(), "p1", NOW)
    assert store.get_job(job.id).status == "closed"


def test_search_window_cannot_establish_closure(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    store.register_target("search", "search", "{}", "indeed")
    job = store.ingest("search", FetchResult(jobs=[posting()]), "p1", NOW)[0]
    for _ in range(3):
        store.ingest("search", FetchResult(), "p1", NOW)
    assert store.get_job(job.id).status == "open"


def test_description_edit_is_not_a_new_opening(tmp_path: Path) -> None:
    store = setup_store(tmp_path / "db.sqlite")
    store.ingest("acme", FetchResult(), "p1", NOW)
    job = store.ingest("acme", FetchResult(jobs=[posting()]), "p1", NOW)[0]
    store.ingest("acme", FetchResult(jobs=[posting(description="New detail")]), "p1", NOW)
    assert store.get_job(job.id).posting.description == "New detail"
    assert store.health()["tasks"] == {"pending": 1}


def test_match_and_downstream_tasks_are_idempotent(tmp_path: Path) -> None:
    store = setup_store(tmp_path / "db.sqlite")
    job = store.ingest("acme", FetchResult(jobs=[posting()]), "p1", NOW)[0]
    match = MatchResult(fit="possible", eligible=None)
    store.save_match(job, match, "p1", ["telegram-id"])
    store.save_match(job, match, "p1", ["telegram-id"])
    assert store.health()["tasks"] == {"pending": 2}
    assert store.get_job(job.id).applied_at is None
    store.mark_applied(job.id)
    assert store.get_job(job.id).applied_at is not None


def test_backup_is_restorable(tmp_path: Path) -> None:
    store = setup_store(tmp_path / "db.sqlite")
    job = store.ingest("acme", FetchResult(jobs=[posting()]), "p1", NOW)[0]
    backup = tmp_path / "backup.sqlite"
    store.backup(backup)
    assert Store(backup).get_job(job.id) == job
