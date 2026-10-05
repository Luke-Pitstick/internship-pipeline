import asyncio
import json
from pathlib import Path

from internship_pipeline.collection import register_targets
from internship_pipeline.discovery import BoardValidation
from internship_pipeline.maintenance import refresh_discovery
from internship_pipeline.models import Company, FetchResult, SearchQuery, Settings
from internship_pipeline.storage import Store


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
    targets = store.targets()
    assert len(targets) == 1 and targets[0]["baselined"] == 0
    assert targets[0]["enabled"] == 1
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
