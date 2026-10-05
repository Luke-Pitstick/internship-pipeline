import asyncio

import pytest

from internship_pipeline import discovery
from internship_pipeline.models import Company, FetchResult, SourceJob


def test_real_installed_registry_recognizes_support_without_network():
    pytest.importorskip("ats_scrapers")
    company = Company(id="example", name="Example", careers_url="https://jobs.ashbyhq.com/example")
    result = discovery.resolve_board(company)
    assert result.supported and result.provider == "ashby" and not result.verified
    unsupported = company.model_copy(update={"careers_url": "https://example.com/careers"})
    assert not discovery.resolve_board(unsupported).supported
    assert not discovery.resolve_board(company.model_copy(update={"provider": "lever"})).supported


def test_validation_requires_complete_success_before_enabling(monkeypatch):
    pytest.importorskip("ats_scrapers")
    company = Company(
        id="example", name="Example", careers_url="https://jobs.ashbyhq.com/example", enabled=False
    )

    async def failed(company, timeout):
        assert company.enabled
        return FetchResult(complete=False, error="incomplete")

    monkeypatch.setattr(discovery, "fetch_company", failed)
    result = asyncio.run(discovery.validate_company(company))
    assert result.supported and not result.verified and result.error == "incomplete"

    async def good(company, timeout):
        return FetchResult()

    monkeypatch.setattr(discovery, "fetch_company", good)
    assert asyncio.run(discovery.validate_company(company)).verified


def test_aggregator_candidate_requires_a_real_supported_employer_url():
    pytest.importorskip("ats_scrapers")
    job = SourceJob(
        source="jobspy:indeed",
        source_id="1",
        board_id="query",
        company="Example",
        title="Intern",
        apply_url="https://jobs.ashbyhq.com/example/req/application",
        source_url="https://indeed.com/viewjob?jk=1",
        description="Build things",
    )
    candidates = discovery.candidates_from_jobs([job, job])
    assert len(candidates) == 1
    assert candidates[0].careers_url == "https://jobs.ashbyhq.com/example"
    assert not candidates[0].enabled and not candidates[0].priority
    assert (
        discovery.candidates_from_jobs([job.model_copy(update={"apply_url": job.source_url})]) == []
    )
