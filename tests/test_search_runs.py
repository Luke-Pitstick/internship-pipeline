from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from internship_pipeline.collection import collect_due, register_targets
from internship_pipeline.models import CandidateProfile, Company, FetchResult, Settings, SourceJob
from internship_pipeline.run_limits import RunLimitError, finish, reserve
from internship_pipeline.search_runs import (
    Pause,
    Revision,
    SearchRuns,
    SourceConfig,
    SourceSave,
    next_due,
)
from internship_pipeline.storage import Store


@pytest.mark.parametrize("source", ["greenhouse", "lever", "ashby", "jobspy"])
@pytest.mark.parametrize("state", ["paused", "deleted", "outside_schedule"])
def test_registry_collector_never_owns_saved_sources(tmp_path, monkeypatch, source, state):
    changes = {"source": source, "daily_at": None, "max_jobs": 0, "max_calls": 0, "max_tokens": 0}
    if source == "jobspy":
        changes.update(search_term="Python internship", board="")
    store = Store(tmp_path / "jobs.sqlite3")
    runs = SearchRuns(store)
    saved = runs.save(
        SourceSave(name="Synthetic", expected_revision=0, **({"board": "example"} | changes))
    )["searches"][0]
    calls = []

    def result(target):
        calls.append(target.id)
        number = str(len(calls))
        return FetchResult(
            jobs=[
                posting().model_copy(
                    update={
                        "source": "jobspy:indeed" if source == "jobspy" else source,
                        "source_id": number,
                        "board_id": target.id,
                        "apply_url": f"https://example.test/{target.id}/{number}",
                    }
                )
            ]
        )

    async def fetch(target, timeout):
        return result(target)

    monkeypatch.setattr("internship_pipeline.sources.ats.fetch_company", fetch)
    monkeypatch.setattr("internship_pipeline.sources.jobspy.fetch_search", lambda q, t: result(q))
    run = runs.start(saved["id"])["run"]
    settings = Settings(database_path=store.path)
    assert asyncio.run(runs.process_next(settings))
    assert len(calls) == 1
    job = store.list_jobs()[0]
    with store.transaction() as db:
        with pytest.raises(RunLimitError, match="run_work_limit"):
            reserve(db, job.id, "assessment", 999999)
        assert (
            db.execute("SELECT run_id FROM search_run_jobs WHERE job_id=?", (job.id,)).fetchone()[0]
            == run["id"]
        )
        db.execute("UPDATE providers SET next_allowed=0")
    if state == "paused":
        runs.pause(saved["id"], Pause(expected_revision=1, paused=True))
    elif state == "deleted":
        runs.delete(saved["id"], Revision(expected_revision=1))
    assert asyncio.run(collect_due(store, CandidateProfile(), settings, force=True)) == 0
    assert len(calls) == 1
    assert len(store.list_jobs()) == 1
    company = Company(
        id="operator",
        name="Operator",
        provider="lever",
        careers_url="https://jobs.lever.co/operator",
    )
    register_targets(store, [company], [])
    assert asyncio.run(collect_due(store, CandidateProfile(), settings, force=True)) == 1
    assert calls == [calls[0], "operator"]


@pytest.mark.parametrize(
    "budget,code",
    [
        ("max_jobs", "run_work_limit"),
        ("max_calls", "run_call_limit"),
        ("max_tokens", "run_token_limit"),
    ],
)
def test_saved_source_preserves_each_zero_budget(tmp_path, monkeypatch, budget, code):
    store, runs, saved = setup(tmp_path, **{budget: 0})

    async def fetch(*args):
        return FetchResult(jobs=[posting()])

    monkeypatch.setattr("internship_pipeline.sources.ats.fetch_company", fetch)
    run = runs.start(saved["id"])["run"]
    assert asyncio.run(runs.process_next(Settings(database_path=store.path)))
    job = store.list_jobs()[0]
    restarted = SearchRuns(Store(store.path))
    assert restarted.history()["runs"][0]["id"] == run["id"]
    with store.transaction() as db:
        with pytest.raises(RunLimitError, match=code):
            reserve(db, job.id, "assessment", 1)


def setup(tmp_path, **changes):
    store = Store(tmp_path / "jobs.sqlite3")
    runs = SearchRuns(store)
    saved = runs.save(
        SourceSave(name="Synthetic", board="example", expected_revision=0, **changes)
    )["searches"][0]
    return store, runs, saved


def posting(number="1"):
    return SourceJob(
        source="greenhouse",
        source_id=number,
        board_id="browser-greenhouse-example",
        company="Synthetic",
        title="Python internship",
        description="Python internship",
        apply_url=f"https://example.test/{number}",
    )


def test_multiple_sources_validation_snapshot_and_overlap(tmp_path):
    store, runs, saved = setup(tmp_path)
    for source in ["greenhouse", "lever", "ashby"]:
        assert (
            SourceConfig(name="Board", source=source, board="example").target("id").provider
            == source
        )
    for token in ["../etc", "https://example.test", "example?query", ""]:
        with pytest.raises(ValidationError):
            SourceConfig(name="Synthetic", board=token)
    with pytest.raises(ValidationError):
        SourceConfig(name="Broad", source="jobspy", search_term="intern", sites=["bad"])
    other = runs.save(
        SourceSave(name="Broad", source="jobspy", search_term="intern", expected_revision=0)
    )["searches"][1]
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: runs.start(saved["id"])["run"]["id"], range(4)))
    assert len(set(ids)) == 1
    assert runs.start(other["id"])["run"]["id"] != ids[0]
    assert len(SearchRuns(Store(store.path)).history()["runs"]) == 2
    with pytest.raises(ValueError):
        runs.save(
            SourceSave(id=saved["id"], name="Changed", board="different", expected_revision=0)
        )


def test_schedule_timezone_pause_no_overlap_and_dst(tmp_path):
    store, runs, saved = setup(tmp_path, daily_at="09:00", timezone="America/Denver")
    now = datetime(2026, 10, 6, 15, 1, tzinfo=UTC).timestamp()
    with store.transaction() as db:
        db.execute("UPDATE saved_searches SET next_due=?", (now - 1,))
    assert runs.schedule(now) == 1
    assert runs.schedule(now) == 0
    assert len(runs.history()["runs"]) == 1
    runs.pause(saved["id"], Pause(expected_revision=1, paused=True))
    with pytest.raises(ValueError, match="Resume"):
        runs.start(saved["id"])
    assert runs.schedule(now + 86400) == 0
    runs.pause(saved["id"], Pause(expected_revision=2, paused=False))
    conf = SourceConfig(name="DST", board="x", daily_at="02:30", timezone="America/Denver")
    due = next_due(conf, datetime(2026, 3, 8, 7, tzinfo=UTC).timestamp())
    assert datetime.fromtimestamp(due, UTC).day == 9
    conf = conf.model_copy(update={"daily_at": "01:30"})
    first = next_due(conf, datetime(2026, 11, 1, 6, tzinfo=UTC).timestamp())
    assert next_due(conf, first + 1) - first > 86400


def test_collection_backlog_dedup_admission_and_cancel(tmp_path, monkeypatch):
    store, runs, saved = setup(tmp_path, max_jobs=1, max_calls=2, max_tokens=100)

    async def fetch(*args):
        return FetchResult(jobs=[posting(), posting("2")])

    monkeypatch.setattr("internship_pipeline.sources.ats.fetch_company", fetch)
    run = runs.start(saved["id"])["run"]
    settings = Settings(database_path=store.path)
    assert asyncio.run(runs.process_next(settings))
    assert runs.view()["run"]["collected"] == 2
    assert runs.view()["run"]["stage"] == "awaiting_model_configuration"
    job = store.list_jobs()[0]
    with store.transaction() as db:
        one = reserve(db, job.id, "assessment", 50)
        finish(db, one, "success", 10, 10)
        with pytest.raises(RunLimitError, match="run_work_limit"):
            reserve(db, store.list_jobs()[1].id, "assessment", 10)
        reserve(db, job.id, "draft", 50)
        with pytest.raises(RunLimitError, match="run_call_limit"):
            reserve(db, job.id, "assessment", 1)
    assert runs.view()["run"]["usage"]["reserved_tokens"] == 100
    runs.cancel(run["id"])
    with store.transaction() as db:
        with pytest.raises(RunLimitError, match="run_cancelled"):
            reserve(db, job.id, "draft", 1)
    assert runs.view()["run"]["stage"] == "cancelled"
    with store.transaction() as db:
        db.execute("UPDATE providers SET next_allowed=0")
    runs.start(saved["id"])
    asyncio.run(runs.process_next(settings))
    assert len(store.list_jobs()) == 2


def test_token_limit_unknown_usage_and_atomic_concurrency(tmp_path, monkeypatch):
    store, runs, saved = setup(tmp_path, max_tokens=50, max_calls=10)

    async def fetch(*args):
        return FetchResult(jobs=[posting()])

    monkeypatch.setattr("internship_pipeline.sources.ats.fetch_company", fetch)
    runs.start(saved["id"])
    asyncio.run(runs.process_next(Settings(database_path=store.path)))
    job = store.list_jobs()[0]

    def call(_):
        try:
            with store.transaction() as db:
                return reserve(db, job.id, "assessment", 30)
        except RunLimitError:
            return "limit"

    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(call, range(4)))
    assert result.count("limit") == 3
    with store.transaction() as db:
        finish(db, next(r for r in result if r != "limit"), "timeout", None, None)
    assert runs.view()["run"]["usage"]["reserved_tokens"] == 30


def test_atomic_fetch_checkpoint_resume_and_source_error_redaction(tmp_path, monkeypatch):
    store, runs, saved = setup(tmp_path)
    count = 0

    async def fetch(*args):
        nonlocal count
        count += 1
        return FetchResult(jobs=[posting()])

    monkeypatch.setattr("internship_pipeline.sources.ats.fetch_company", fetch)
    original = store.ingest

    def crash(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(store, "ingest", crash)
    runs.start(saved["id"])
    with pytest.raises(OSError):
        asyncio.run(runs.process_next(Settings(database_path=store.path)))
    assert runs.view()["run"]["stage"] == "fetched"
    assert not store.list_jobs()
    monkeypatch.setattr(store, "ingest", original)
    with store.transaction() as db:
        db.execute("UPDATE tasks SET lease_until=0")
    asyncio.run(runs.process_next(Settings(database_path=store.path)))
    assert count == 1

    async def failed(*args):
        return FetchResult(complete=False, error="secret-token private payload")

    monkeypatch.setattr("internship_pipeline.sources.ats.fetch_company", failed)
    with store.transaction() as db:
        db.execute("UPDATE providers SET next_allowed=0")
    runs.start(saved["id"])
    asyncio.run(runs.process_next(Settings(database_path=store.path)))
    assert runs.view()["run"]["source_error"] == "source_request_failed"
    assert store.list_jobs()[0].status == "open"


def test_broad_source_uses_connector_and_does_not_close_inventory(tmp_path, monkeypatch):
    store = Store(tmp_path / "jobs.sqlite3")
    runs = SearchRuns(store)
    saved = runs.save(
        SourceSave(
            name="Broad",
            source="jobspy",
            search_term="Python internship",
            location="Denver",
            expected_revision=0,
            results_wanted=10,
        )
    )["searches"][0]

    def fetch(query, timeout):
        assert query.location == "Denver" and query.results_wanted == 10
        return FetchResult(
            jobs=[posting().model_copy(update={"source": "jobspy:indeed", "board_id": query.id})],
            complete=False,
            coverage_limited=True,
        )

    monkeypatch.setattr("internship_pipeline.sources.jobspy.fetch_search", fetch)
    runs.start(saved["id"])
    assert asyncio.run(runs.process_next(Settings(database_path=store.path)))
    assert runs.view()["run"]["collected"] == 1
    assert store.list_jobs()[0].applied_at is None


def test_search_country_choices_are_supported_and_invalid_countries_fail(tmp_path):
    _, searches, _ = setup(tmp_path)
    choices = searches.settings()["countries"]
    assert {"value": "USA", "code": "US"} in choices
    for choice in choices:
        assert len(choice["code"]) == 2
        SourceConfig(name="Country", source="jobspy", search_term="intern", country=choice["value"])
    with pytest.raises(ValueError, match="Choose a supported search country"):
        SourceConfig(name="Invalid", source="jobspy", search_term="intern", country="Atlantis")


def test_first_inventory_is_automatically_admitted_and_scheduled(tmp_path, monkeypatch):
    store, runs, saved = setup(tmp_path)

    async def fetch(*args):
        return FetchResult(jobs=[posting()])

    monkeypatch.setattr("internship_pipeline.sources.ats.fetch_company", fetch)
    assert saved["next_run"] is not None
    assert asyncio.run(runs.process_next(Settings(database_path=store.path)))
    job = store.list_jobs()[0]
    assert job.event == "backlog"
    with store.transaction() as db:
        assert reserve(db, job.id, "assessment", 1) is not None
    assert runs.view()["run"]["stage"] != "awaiting_backlog_review"


def test_continuous_collection_starts_other_sources_before_slow_fetch_finishes(
    tmp_path, monkeypatch
):
    import threading

    store, runs, _ = setup(tmp_path)
    for source in ["lever", "ashby"]:
        runs.save(SourceSave(name=source, source=source, board="example", expected_revision=0))
    active = 0
    peak = 0
    started = set()
    stop = threading.Event()

    async def fetch(target, timeout):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        started.add(target.provider)
        # Every provider must start before any provider is allowed to finish.
        for _ in range(50):
            if len(started) == 3:
                break
            await asyncio.sleep(0.01)
        assert len(started) == 3
        active -= 1
        if active == 0:
            stop.set()
        return FetchResult()

    monkeypatch.setattr("internship_pipeline.sources.ats.fetch_company", fetch)
    asyncio.run(runs.collect(Settings(database_path=store.path), stop))
    assert peak == 3
    assert len(runs.history()["runs"]) == 3
    assert all(run["stage"] == "complete" for run in runs.history()["runs"])


def test_completed_usage_releases_unused_reservation_but_keeps_actual_budget(tmp_path, monkeypatch):
    store, runs, saved = setup(tmp_path, max_tokens=50, max_calls=10)

    async def fetch(*args):
        return FetchResult(jobs=[posting()])

    monkeypatch.setattr("internship_pipeline.sources.ats.fetch_company", fetch)
    runs.start(saved["id"])
    asyncio.run(runs.process_next(Settings(database_path=store.path)))
    job = store.list_jobs()[0]
    with store.transaction() as db:
        first = reserve(db, job.id, "assessment", 40)
        finish(db, first, "success", 10, 10)
        reserve(db, job.id, "draft", 30)
        with pytest.raises(RunLimitError, match="run_token_limit"):
            reserve(db, job.id, "draft", 1)


def test_site_backoff_does_not_block_other_sites(tmp_path, monkeypatch):
    import time

    store = Store(tmp_path / "jobs.sqlite3")
    runs = SearchRuns(store)
    for site in ["indeed", "linkedin"]:
        saved = runs.save(
            SourceSave(
                name=site,
                source="jobspy",
                search_term="internship",
                sites=[site],
                expected_revision=0,
            )
        )["searches"][-1]
        runs.start(saved["id"])
    store.reserve_provider("jobspy:indeed", time.time(), spacing=600)
    called = []

    def fetch(query, timeout):
        called.extend(query.sites)
        return FetchResult()

    monkeypatch.setattr("internship_pipeline.sources.jobspy.fetch_search", fetch)
    settings = Settings(database_path=store.path)
    assert not asyncio.run(runs.process_next(settings))
    assert asyncio.run(runs.process_next(settings))
    assert called == ["linkedin"]
    history = runs.history()
    assert history["summary"]["queued"] == 1
    assert history["summary"]["collecting"] == 0


def test_overlapping_searches_report_unique_inventory_and_filter_history(tmp_path, monkeypatch):
    store, runs, saved = setup(tmp_path)

    async def fetch(*args):
        return FetchResult(jobs=[posting()])

    monkeypatch.setattr("internship_pipeline.sources.ats.fetch_company", fetch)
    settings = Settings(database_path=store.path)
    for _ in range(2):
        with store.transaction() as db:
            db.execute("UPDATE providers SET next_allowed=0")
        runs.start(saved["id"])
        assert asyncio.run(runs.process_next(settings))
    assert runs.history()["summary"]["collected"] == 1
    assert len(runs.history(saved["id"])["runs"]) == 2
    assert runs.history("0" * 32)["runs"] == []


@pytest.mark.parametrize("transition", ["cancel", "stop_ingestion", "new_lease"])
def test_obsolete_fetch_rolls_back_without_stopping_collection(tmp_path, monkeypatch, transition):
    store, runs, saved = setup(tmp_path)
    run = runs.start(saved["id"])["run"]

    async def fetch(*args):
        return FetchResult(jobs=[posting()])

    monkeypatch.setattr("internship_pipeline.sources.ats.fetch_company", fetch)
    original = store.ingest

    def supersede(*args, **kwargs):
        if transition == "cancel":
            runs.cancel(run["id"])
        elif transition == "stop_ingestion":
            runs.stop_ingestion()
        else:
            with store.transaction() as db:
                db.execute("UPDATE tasks SET token='new-owner' WHERE kind='collection_run'")
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "ingest", supersede)
    settings = Settings(database_path=store.path)
    assert not asyncio.run(runs.process_next(settings))
    assert not store.list_jobs()  # Ingestion and its observations must roll back together.
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
        task = db.execute("SELECT status,token FROM tasks WHERE kind='collection_run'").fetchone()
        if transition in {"cancel", "stop_ingestion"}:
            assert task["status"] == "done"
        else:
            assert task["status"] == "running" and task["token"] == "new-owner"
    # The same collection service can process subsequent work after the cancelled task.
    monkeypatch.setattr(store, "ingest", original)
    with store.transaction() as db:
        db.execute("UPDATE providers SET next_allowed=0")
        db.execute("UPDATE tasks SET lease_until=0 WHERE kind='collection_run'")
    if transition == "cancel":
        runs.start(saved["id"])
    elif transition == "stop_ingestion":
        runs.start_ingestion()
    assert asyncio.run(runs.process_next(settings))
    assert len(store.list_jobs()) == 1


def test_ingestion_stop_persists_and_start_preserves_source_pauses(tmp_path):
    store, runs, saved = setup(tmp_path, daily_at="09:00")
    other = runs.save(SourceSave(name="Paused", board="paused", expected_revision=0))["searches"][1]
    runs.pause(other["id"], Pause(expected_revision=1, paused=True))
    first = runs.start(saved["id"])["run"]
    runs.start_ingestion()
    assert len(runs.history()["runs"]) == 1  # Reuse active work instead of overlapping.
    assert runs.stop_ingestion()["active_runs"] == 0
    assert runs.view(first["id"])["run"]["stage"] == "cancelled"
    restarted = SearchRuns(Store(store.path))
    assert restarted.ingestion_status()["stopped"]
    assert restarted.ingestion_status()["next_run"] is None
    assert restarted.schedule(9999999999) == 0
    with pytest.raises(ValueError, match="ingestion is stopped"):
        restarted.start(saved["id"])
    # New sources and edits cannot bypass the global stop.
    restarted.save(SourceSave(name="New source", board="new", expected_revision=0))
    assert restarted.schedule(9999999999) == 0
    assert restarted.start_ingestion()["active_runs"] == 2
    sources = restarted.settings()["searches"]
    assert next(s for s in sources if s["id"] == other["id"])["paused"]
    assert not restarted.ingestion_status()["stopped"]
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM tasks WHERE status='pending'").fetchone()[0] == 2


def test_ingestion_requires_enabled_sources_and_preserves_saved_work(tmp_path, monkeypatch):
    store, runs, saved = setup(tmp_path)

    async def fetch(*args):
        return FetchResult(jobs=[posting()])

    monkeypatch.setattr("internship_pipeline.sources.ats.fetch_company", fetch)
    run = runs.start(saved["id"])["run"]
    assert asyncio.run(runs.process_next(Settings(database_path=store.path)))
    before = runs.view(run["id"])
    runs.stop_ingestion()
    assert runs.view(run["id"]) == before
    assert len(store.list_jobs()) == 1
    runs.pause(saved["id"], Pause(expected_revision=1, paused=True))
    with pytest.raises(ValueError, match="Add or resume"):
        runs.start_ingestion()
    assert runs.ingestion_status()["stopped"]


def test_stop_during_source_request_discards_result(tmp_path, monkeypatch):
    store, runs, saved = setup(tmp_path)
    runs.start(saved["id"])

    async def fetch(*args):
        runs.stop_ingestion()
        return FetchResult(jobs=[posting()])

    monkeypatch.setattr("internship_pipeline.sources.ats.fetch_company", fetch)
    assert not asyncio.run(runs.process_next(Settings(database_path=store.path)))
    assert not store.list_jobs()
    assert not asyncio.run(runs.process_next(Settings(database_path=store.path)))
    assert runs.history()["summary"]["ingestion_stopped"]


def test_failed_collection_does_not_block_ingestion_restart(tmp_path):
    store, runs, saved = setup(tmp_path)
    run = runs.start(saved["id"])["run"]
    with store.transaction() as db:
        db.execute("UPDATE tasks SET status='failed' WHERE kind='collection_run'")
    assert runs.ingestion_status()["active_runs"] == 0
    assert runs.start_ingestion()["active_runs"] == 1
    assert runs.view(run["id"])["run"]["stage"] == "needs_attention"


def test_saved_job_search_discovers_employer_boards_automatically(tmp_path, monkeypatch):
    store = Store(tmp_path / "jobs.sqlite3")
    runs = SearchRuns(store)
    source = runs.save(
        SourceSave(name="Search", source="jobspy", search_term="internship", expected_revision=0)
    )["searches"][0]

    def fetch(query, timeout):
        return FetchResult(
            jobs=[
                posting().model_copy(
                    update={
                        "source": "jobspy:indeed",
                        "board_id": query.id,
                        "apply_url": "https://jobs.ashbyhq.com/example.ai/job-1",
                        "source_url": "https://indeed.com/viewjob?jk=1",
                    }
                )
            ]
        )

    monkeypatch.setattr("internship_pipeline.sources.jobspy.fetch_search", fetch)
    runs.start(source["id"])
    assert asyncio.run(runs.process_next(Settings(database_path=store.path)))
    candidates = store.candidate_companies()
    assert len(candidates) == 1
    assert candidates[0].careers_url == "https://jobs.ashbyhq.com/example.ai"


def test_non_internships_are_removed_before_durable_fetch_checkpoint(tmp_path, monkeypatch):
    store, runs, saved = setup(tmp_path)

    async def fetch(*args):
        return FetchResult(
            jobs=[
                posting(),
                posting("fulltime").model_copy(
                    update={
                        "title": "Senior Engineer",
                        "description": "Permanent full-time position.",
                    }
                ),
            ]
        )

    monkeypatch.setattr("internship_pipeline.sources.ats.fetch_company", fetch)
    run = runs.start(saved["id"])["run"]
    original_ingest = store.ingest

    def inspect_checkpoint(*args, **kwargs):
        with store.connection() as db:
            stored = FetchResult.model_validate_json(
                db.execute("SELECT result FROM search_runs WHERE id=?", (run["id"],)).fetchone()[0]
            )
        assert len(stored.jobs) == 1
        assert stored.jobs[0].source_id == posting().source_id
        return original_ingest(*args, **kwargs)

    monkeypatch.setattr(store, "ingest", inspect_checkpoint)
    assert asyncio.run(runs.process_next(Settings(database_path=store.path)))
    assert len(store.list_jobs()) == 1
    assert runs.view()["run"]["collected"] == 1
