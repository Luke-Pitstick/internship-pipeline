"""Company candidates from the selected library's directory and verified URLs."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from internship_pipeline.models import Company, FetchResult, SourceJob
from internship_pipeline.normalization import canonical_url
from internship_pipeline.sources.ats import COMPLETE_PROVIDERS, fetch_company


@dataclass(frozen=True)
class BoardValidation:
    company: Company
    supported: bool
    verified: bool = False
    provider: str | None = None
    result: FetchResult | None = None
    error: str | None = None


def resolve_board(company: Company) -> BoardValidation:
    """Resolve support using installed URL resolution and the actual registry."""
    try:
        from ats_scrapers import get_scraper_for_url

        canonical_url(company.careers_url)
        scraper = get_scraper_for_url(company.careers_url)
        provider = scraper.ats.value
        if company.provider not in {"auto", provider}:
            raise ValueError("Configured provider does not match URL resolution")
        return BoardValidation(company, True, provider=provider)
    except Exception as exc:
        return BoardValidation(company, False, error=f"{type(exc).__name__}: {exc}")


async def validate_company(company: Company, timeout: float = 30) -> BoardValidation:
    resolved = resolve_board(company)
    if not resolved.supported:
        return resolved
    result = await fetch_company(company.model_copy(update={"enabled": True}), timeout)
    return BoardValidation(
        company=company.model_copy(update={"provider": resolved.provider}),
        supported=True,
        verified=result.complete and result.error is None,
        provider=resolved.provider,
        result=result,
        error=result.error,
    )


def discover_companies(
    name: str | None = None, limit: int = 200, timeout: float = 30
) -> list[Company]:
    """Fetch directory candidates; callers validate and baseline before enabling.

    Directory presence proves neither internship relevance nor a working board.
    This synchronous daily task belongs outside the fast polling event loop.
    """
    if limit < 1 or timeout <= 0:
        raise ValueError("limit and timeout must be positive")
    import httpx
    from ats_scrapers import Client

    with httpx.Client(timeout=timeout) as transport:
        client = Client(http_client=transport, prefer_parquet=False)
        try:
            frame = client.companies()
            required_columns = {"ats", "name", "slug", "url"}
            if not required_columns.issubset(frame.columns):
                raise ValueError("ATS directory is missing required ats/name/slug/url columns")
            # The live directory is grouped by provider. Its first 200 rows can
            # all be unresolvable ADP boards, so limit accepted candidates only.
            if name:
                frame = client.find_company(name, limit=len(frame))
            rows = frame.to_dict(orient="records")
        finally:
            client.close()
    companies: dict[str, Company] = {}
    for row in rows:
        try:
            provider, slug = str(row["ats"]), str(row["slug"])
            company = Company(
                id=f"{provider}:{slug}",
                name=str(row["name"]),
                careers_url=canonical_url(str(row["url"])),
                provider=provider,
                enabled=False,
            )
            if resolve_board(company).supported:
                companies[company.id] = company
                if len(companies) >= limit:
                    break
        except (KeyError, ValueError, TypeError):
            continue
    return list(companies.values())


def candidates_from_jobs(jobs: list[SourceJob]) -> list[Company]:
    """Recognize real employer ATS URLs; never fabricate a board from its name."""
    from ats_scrapers import resolve_careers_url

    companies: dict[str, Company] = {}
    for job in jobs:
        for url in (job.apply_url, job.source_url):
            resolved = resolve_careers_url(url)
            if resolved is None or resolved.ats.value not in COMPLETE_PROVIDERS:
                continue
            parts = urlsplit(canonical_url(url))
            board_url = urlunsplit((parts.scheme, parts.netloc, f"/{resolved.slug}", "", ""))
            company = Company(
                id=f"{resolved.ats.value}:{resolved.slug}",
                name=job.company,
                careers_url=board_url,
                provider=resolved.ats.value,
                enabled=False,
            )
            companies[company.id] = company
    return list(companies.values())
