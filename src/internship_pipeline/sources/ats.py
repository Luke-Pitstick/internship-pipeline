"""Direct boards through ats-scrapers 0.3.0's async API."""

from __future__ import annotations

import asyncio
from datetime import UTC
from typing import Any

from internship_pipeline.models import Company, FetchResult, SourceJob
from internship_pipeline.normalization import canonical_url
from internship_pipeline.sources.errors import ProviderError, failure_result

# Audited afetch implementations fetch one uncapped full-board JSON response.
COMPLETE_PROVIDERS = frozenset({"ashby", "greenhouse", "lever"})


class _ValidatedFetcher:
    """Delegate transport to the library while validating full-board payloads."""

    def __init__(self, fetcher: Any, provider: str):
        self.fetcher = fetcher
        self.provider = provider

    async def __aenter__(self):
        await self.fetcher.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.fetcher.__aexit__(*args)

    async def get_json(self, url: str, **kwargs):
        response = await self.fetcher.request("GET", url, handled={429, *range(500, 600)}, **kwargs)
        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderError(
                response.status_code,
                response.headers.get("Retry-After") or response.headers.get("retry-after"),
            )
        payload = response.json()
        rows = (
            payload
            if self.provider == "lever"
            else (payload.get("jobs") if isinstance(payload, dict) else None)
        )
        if not isinstance(rows, list):
            raise ValueError("Full-board response is missing its jobs list")
        return payload


def _build_scraper(company: Company, timeout: float):
    from ats_scrapers import get_scraper_for_url

    scraper = get_scraper_for_url(company.careers_url, timeout=timeout, include_descriptions=True)
    provider = scraper.ats.value
    if company.provider != "auto" and company.provider != provider:
        raise ValueError(f"Configured provider {company.provider!r} resolves to {provider!r}")
    if provider in COMPLETE_PROVIDERS:
        factory = scraper.make_fetcher
        scraper.make_fetcher = lambda **kwargs: _ValidatedFetcher(
            factory(retries=1, **kwargs), provider
        )
    return scraper


def normalize_job(row: Any, company: Company, provider: str) -> SourceJob:
    source_url = canonical_url(str(row.url))
    source_id = str(row.ats_id).strip() if row.ats_id else source_url
    if not row.title.strip():
        raise ValueError("Posting is missing a title")
    raw = row.raw or {}
    locations = [row.location] if row.location else []
    locations.extend(raw.get("secondary_locations") or [])
    posted_at = row.posted_at
    if posted_at is not None and posted_at.tzinfo is None:
        # Lever's installed parser uses local time for epoch milliseconds.
        posted_at = posted_at.astimezone(UTC)
    timestamp_kind = "unknown"
    if posted_at is not None:
        timestamp_kind = "source_time_ambiguous" if provider == "greenhouse" else "published"
    compensation = row.salary_summary
    if not compensation and (row.salary_min is not None or row.salary_max is not None):
        compensation = " ".join(
            str(part)
            for part in (
                row.salary_currency,
                row.salary_min,
                "–",
                row.salary_max,
                row.salary_period,
            )
            if part is not None
        )
    return SourceJob(
        source=provider,
        source_id=source_id,
        board_id=company.id,
        company=company.name,
        title=row.title.strip(),
        apply_url=canonical_url(str(row.apply_url or row.url)),
        source_url=source_url,
        description=row.description or "",
        locations=list(dict.fromkeys(str(location) for location in locations if location)),
        employment_type=row.employment_type,
        requisition_id=row.requisition_id,
        published_at=posted_at,
        timestamp_kind=timestamp_kind,
        compensation=compensation,
        deadline=str(row.application_deadline) if row.application_deadline else None,
    )


async def fetch_company(company: Company, timeout: float = 30) -> FetchResult:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if not company.enabled:
        return FetchResult(complete=False, error="Company is disabled")
    try:
        canonical_url(company.careers_url)
        scraper = _build_scraper(company, timeout)
        async with asyncio.timeout(timeout):
            rows = await scraper.afetch()
        provider = scraper.ats.value
    except Exception as exc:
        return failure_result(exc)
    jobs = []
    errors = []
    identities = set()
    for row in rows:
        try:
            job = normalize_job(row, company, provider)
            if job.source_id in identities:
                raise ValueError(f"Repeated posting identity {job.source_id}")
            identities.add(job.source_id)
            jobs.append(job)
        except Exception as exc:
            errors.append(f"Invalid posting: {type(exc).__name__}: {exc}")
    if provider not in COMPLETE_PROVIDERS:
        errors.append(f"{provider}: library exposes no verified snapshot completeness metadata")
    return FetchResult(jobs=jobs, complete=not errors, error="; ".join(errors) or None)


async def fetch_companies(companies: list[Company], timeout: float = 30, concurrency: int = 4):
    """Yield completed boards immediately, bounding concurrent logical fetches."""
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch(company):
        async with semaphore:
            return company, await fetch_company(company, timeout)

    tasks = [asyncio.create_task(fetch(company)) for company in companies]
    try:
        for task in asyncio.as_completed(tasks):
            yield await task
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
