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


@pytest.mark.parametrize("name", [None, "Example"])
def test_directory_api_candidates_remain_disabled_until_validation(monkeypatch, name):
    module = pytest.importorskip("ats_scrapers")
    import pandas as pd

    class Client:
        def __init__(self, *, http_client, prefer_parquet):
            assert prefer_parquet is False

        def companies(self):
            return pd.DataFrame(
                [
                    dict(
                        ats="ashby",
                        name="Example",
                        slug="example",
                        url="https://jobs.ashbyhq.com/example",
                    ),
                    dict(
                        ats="unknown",
                        name="Unsupported",
                        slug="unknown",
                        url="https://example.com/careers",
                    ),
                ]
            )

        def find_company(self, name, *, limit):
            assert name == "Example"
            return self.companies().head(limit)

        def close(self):
            pass

    monkeypatch.setattr(module, "Client", Client)
    candidates = discovery.discover_companies(name=name, limit=2)
    assert len(candidates) == 1 and not candidates[0].enabled
    assert candidates[0].id == "ashby:example"
