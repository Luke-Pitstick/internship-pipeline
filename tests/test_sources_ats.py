import asyncio
import json
from types import SimpleNamespace

import pytest

from internship_pipeline.models import Company
from internship_pipeline.sources import ats
from internship_pipeline.sources.errors import ProviderError, retry_delay


def company(id="example", provider="auto"):
    return Company(
        id=id, name="Example", careers_url=f"https://jobs.ashbyhq.com/{id}", provider=provider
    )


def row(id="1"):
    return SimpleNamespace(
        url=f"https://jobs.ashbyhq.com/example/{id}",
        ats_id=id,
        title="Intern",
        raw={"secondary_locations": ["Remote"]},
        location="Denver",
        posted_at=None,
        salary_summary=None,
        salary_min=None,
        salary_max=None,
        salary_currency=None,
        salary_period=None,
        apply_url=None,
        description="Requirements",
        employment_type="INTERN",
        requisition_id=None,
        application_deadline=None,
    )


def test_real_library_contract_handles_full_ashby_board(monkeypatch):
    pytest.importorskip("ats_scrapers")
    from ats_scrapers.fetch import Fetcher, FetchResponse

    payload = {
        "jobs": [
            {
                "id": "stable",
                "title": "Intern",
                "jobUrl": "https://jobs.ashbyhq.com/example/stable",
                "location": "Denver",
                "descriptionPlain": "Build things",
                "publishedAt": "2026-01-01T00:00:00Z",
            }
        ]
    }

    async def perform(self, *args, **kwargs):
        return FetchResponse(200, json.dumps(payload), {}, "test")

    monkeypatch.setattr(Fetcher, "_perform", perform)
    result = asyncio.run(ats.fetch_company(company()))
    assert result.complete and result.error is None
    assert result.jobs[0].source_id == "stable"
    assert result.jobs[0].description == "Build things"
    assert result.jobs[0].timestamp_kind == "published"


def test_malformed_success_never_becomes_empty_complete_board(monkeypatch):
    pytest.importorskip("ats_scrapers")
    from ats_scrapers.fetch import Fetcher, FetchResponse

    async def perform(self, *args, **kwargs):
        return FetchResponse(200, '{"error":"maintenance"}', {}, "test")

    monkeypatch.setattr(Fetcher, "_perform", perform)
    result = asyncio.run(ats.fetch_company(company()))
    assert not result.complete and "missing its jobs list" in result.error


def test_rate_limit_metadata_survives_library_error_mapping(monkeypatch):
    pytest.importorskip("ats_scrapers")
    from ats_scrapers.fetch import Fetcher, FetchResponse

    async def perform(self, *args, **kwargs):
        return FetchResponse(429, "", {"Retry-After": "120"}, "test")

    monkeypatch.setattr(Fetcher, "_perform", perform)
    result = asyncio.run(ats.fetch_company(company()))
    assert not result.complete and result.retry_after_seconds == 120


def test_invalid_rows_preserve_successful_jobs_but_mark_snapshot_incomplete(monkeypatch):
    class Scraper:
        ats = SimpleNamespace(value="ashby")

        async def afetch(self):
            return [row(), row()]

    monkeypatch.setattr(ats, "_build_scraper", lambda *args: Scraper())
    result = asyncio.run(ats.fetch_company(company()))
    assert len(result.jobs) == 1 and not result.complete
    assert "Repeated posting identity" in result.error


def test_hanging_async_board_is_bounded(monkeypatch):
    class Scraper:
        async def afetch(self):
            await asyncio.sleep(30)

    monkeypatch.setattr(ats, "_build_scraper", lambda *args: Scraper())
    result = asyncio.run(ats.fetch_company(company(), timeout=0.01))
    assert not result.complete and "TimeoutError" in result.error


def test_finished_boards_are_yielded_without_waiting_for_slow_board(monkeypatch):
    async def fetch(company, timeout):
        await asyncio.sleep(0.02 if company.id == "slow" else 0)
        if company.id == "broken":
            from internship_pipeline.models import FetchResult

            return FetchResult(complete=False, error="failed")
        from internship_pipeline.models import FetchResult

        return FetchResult()

    monkeypatch.setattr(ats, "fetch_company", fetch)

    async def collect():
        return [
            (c.id, r.complete)
            async for c, r in ats.fetch_companies(
                [company("slow"), company("broken"), company("fast")], concurrency=3
            )
        ]

    results = asyncio.run(collect())
    assert results[-1][0] == "slow"
    assert ("broken", False) in results and ("fast", True) in results


def test_retry_after_http_date():
    from datetime import UTC, datetime

    assert retry_delay("Thu, 01 Jan 2026 00:02:00 GMT", datetime(2026, 1, 1, tzinfo=UTC)) == 120
    assert retry_delay("nonsense") is None
    assert str(ProviderError(429)) == "Provider returned HTTP 429"


def test_apply_endpoint_is_retained_for_delivery():
    posting = row()
    posting.apply_url = "https://jobs.ashbyhq.com/example/1/application?utm_source=x"
    assert ats.normalize_job(posting, company(), "ashby").apply_url == posting.apply_url


def test_unaudited_healthy_provider_reports_coverage_without_transport_failure(monkeypatch):
    class Scraper:
        ats = SimpleNamespace(value="workday")

        async def afetch(self):
            return [row()]

    monkeypatch.setattr(ats, "_build_scraper", lambda *args: Scraper())
    result = asyncio.run(ats.fetch_company(company()))
    assert not result.complete and result.coverage_limited and len(result.jobs) == 1
