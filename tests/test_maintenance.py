import asyncio
import json
from pathlib import Path

import pytest

from internship_pipeline.collection import register_targets
from internship_pipeline.discovery import BoardValidation
from internship_pipeline.maintenance import refresh_discovery
from internship_pipeline.models import Company, FetchResult, SearchQuery, Settings
from internship_pipeline.search_runs import SearchRuns
from internship_pipeline.storage import Store


@pytest.fixture(autouse=True)
def no_directory_network(monkeypatch):
    monkeypatch.setattr("internship_pipeline.discovery.discover_companies", lambda **kwargs: [])


def test_daily_discovery_enables_only_verified_boards_and_preserves_baseline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = Store(tmp_path / "db.sqlite")
    companies = [
        Company(
            id=name,
            name=name,
            careers_url=f"https://jobs.ashbyhq.com/{name}",
            provider="ashby",
            enabled=False,
        )
        for name in ["good", "bad"]
    ]
    store.add_candidates(companies)

    async def validate(company, timeout):
        return BoardValidation(company, supported=True, verified=company.id == "good")

    async def no_sleep(_):
        return None

    monkeypatch.setattr("internship_pipeline.discovery.validate_company", validate)
    monkeypatch.setattr("internship_pipeline.maintenance.asyncio.sleep", no_sleep)
    monkeypatch.setattr(store, "reserve_provider", lambda *_args, **_kwargs: True)
    assert asyncio.run(refresh_discovery(store, Settings())) == 1
    sources = SearchRuns(store).settings()["searches"]
    assert len(sources) == 1 and sources[0]["source"] == "ashby"
    assert not sources[0]["paused"]
    assert sources[0]["daily_at"] is not None
    assert sources[0]["next_run"] is not None
    assert asyncio.run(refresh_discovery(Store(store.path), Settings())) == 0
    assert store.health()["discovery_candidates"] == {"failed": 1, "monitored": 1}


def test_multisite_queries_share_per_site_provider_cooldowns(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    register_targets(
        store,
        [],
        [
            SearchQuery(id="swe", search_term="software intern", sites=["indeed", "linkedin"]),
            SearchQuery(id="ml", search_term="machine learning intern", sites=["indeed"]),
        ],
    )
    targets = store.targets()
    assert sorted(t["provider"] for t in targets) == [
        "jobspy:indeed",
        "jobspy:indeed",
        "jobspy:linkedin",
    ]
    assert all(len(json.loads(t["config"])["sites"]) == 1 for t in targets)


def test_coverage_limit_does_not_accumulate_provider_failures(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    store.register_target("capped", "search", "{}", "indeed")
    for i in range(8):
        store.finish_target(
            "capped",
            i + 10,
            FetchResult(
                complete=False,
                coverage_limited=True,
                error="Result cap reached",
            ),
            i,
        )
    target = store.targets()[0]
    assert target["failures"] == 0
    assert target["last_success"] == 7
    assert target["complete"] == 0
    assert target["error"] == "Result cap reached"


def test_directory_refresh_is_automatic_durable_and_deduplicated(tmp_path, monkeypatch):
    from internship_pipeline.maintenance import discovery_status

    calls = []
    company = Company(
        id="ashby:example",
        name="Example",
        provider="ashby",
        careers_url="https://jobs.ashbyhq.com/example",
    )

    def directory(**kwargs):
        assert kwargs["limit"] is None
        calls.append(1)
        return [company]

    async def validate(company, timeout):
        return BoardValidation(company, supported=True, verified=True)

    async def no_sleep(_):
        pass

    monkeypatch.setattr("internship_pipeline.discovery.discover_companies", directory)
    monkeypatch.setattr("internship_pipeline.discovery.validate_company", validate)
    monkeypatch.setattr("internship_pipeline.maintenance.asyncio.sleep", no_sleep)
    store = Store(tmp_path / "db.sqlite")
    assert asyncio.run(refresh_discovery(store, Settings())) == 1
    assert discovery_status(store)["monitored"] == 1
    assert asyncio.run(refresh_discovery(Store(store.path), Settings(), force=True)) == 0
    assert calls == [1]
    assert len(SearchRuns(store).settings()["searches"]) == 1
    # A deleted or paused source is not silently recreated from monitored candidates.
    with store.transaction() as db:
        db.execute("DELETE FROM saved_searches")
        db.execute("DELETE FROM maintenance")
    assert asyncio.run(refresh_discovery(store, Settings())) == 0
    assert SearchRuns(store).settings()["searches"] == []


def test_discovery_respects_stop_before_and_during_validation(tmp_path, monkeypatch):
    store = Store(tmp_path / "db.sqlite")
    runs = SearchRuns(store)
    runs.stop_ingestion()

    def no_request(**kwargs):
        raise AssertionError("Stopped discovery must not access directory")

    monkeypatch.setattr("internship_pipeline.discovery.discover_companies", no_request)
    assert asyncio.run(refresh_discovery(store, Settings())) == 0
    company = Company(
        id="ashby:test", name="Test", provider="ashby", careers_url="https://jobs.ashbyhq.com/test"
    )
    store.add_candidates([company])
    with store.transaction() as db:
        db.execute("UPDATE job_ingestion SET stopped=0")
    monkeypatch.setattr("internship_pipeline.discovery.discover_companies", lambda **kwargs: [])

    async def stop_during_validation(company, timeout):
        runs.stop_ingestion()
        return BoardValidation(company, supported=True, verified=True)

    monkeypatch.setattr("internship_pipeline.discovery.validate_company", stop_during_validation)
    assert asyncio.run(refresh_discovery(store, Settings())) == 0
    assert runs.settings()["searches"] == []
    assert store.health()["discovery_candidates"] == {"pending": 1}


def test_directory_failure_keeps_candidates_and_retries(tmp_path, monkeypatch):
    from internship_pipeline.maintenance import discovery_status

    store = Store(tmp_path / "db.sqlite")

    def unavailable(**kwargs):
        raise OSError("network error with sensitive details")

    monkeypatch.setattr("internship_pipeline.discovery.discover_companies", unavailable)
    assert asyncio.run(refresh_discovery(store, Settings())) == 0
    status = discovery_status(store)
    assert status["directory_error"] == "Directory unavailable; retrying automatically."
    with store.connection() as db:
        assert (
            db.execute("SELECT next_due FROM maintenance WHERE name='source_directory'").fetchone()[
                0
            ]
            > status["directory_checked_at"]
        )


def test_discovery_preserves_paused_existing_board_and_supports_dotted_tokens(tmp_path):
    from internship_pipeline.maintenance import _save_board
    from internship_pipeline.search_runs import Pause, SourceSave

    store = Store(tmp_path / "db.sqlite")
    runs = SearchRuns(store)
    runs.save(SourceSave(name="My board", source="ashby", board="example.ai", expected_revision=0))
    row = runs.settings()["searches"][0]
    runs.pause(row["id"], Pause(expected_revision=row["revision"], paused=True))
    company = Company(
        id="ashby:example.ai",
        name="Example",
        provider="ashby",
        careers_url="https://jobs.ashbyhq.com/example.ai",
    )
    store.add_candidates([company])
    assert not _save_board(store, company)
    assert len(runs.settings()["searches"]) == 1
    assert runs.settings()["searches"][0]["paused"]
