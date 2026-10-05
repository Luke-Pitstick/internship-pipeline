"""JobSpy searches in killable child processes, independent of ATS polling."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, date, datetime
from typing import Any

from internship_pipeline.models import FetchResult, SearchQuery, SourceJob
from internship_pipeline.normalization import canonical_url

SUPPORTED_SITES = frozenset(
    {"indeed", "linkedin", "zip_recruiter", "glassdoor", "google", "bayt", "naukri", "bdjobs"}
)


class MissingEmployerError(ValueError):
    """JobSpy allows absent employer names; the posting's identity is incomplete."""


def _text(value: Any) -> str:
    if value is None:
        return ""
    # DataFrame cells include float NaN and pandas.NA; do not stringify missing data.
    try:
        if value != value:
            return ""
    except (ValueError, TypeError):
        return ""
    return str(value).strip()


def normalize_row(row: dict[str, Any], query: SearchQuery) -> SourceJob:
    site = _text(row.get("site"))
    url = canonical_url(_text(row.get("job_url")))
    direct = _text(row.get("job_url_direct"))
    apply_url = direct or _text(row.get("job_url"))
    canonical_url(apply_url)
    title = _text(row.get("title"))
    company = _text(row.get("company"))
    if not title:
        raise ValueError("Search result title is missing")
    if site not in query.sites:
        raise ValueError("Search result site is missing or was not requested")
    if not company:
        raise MissingEmployerError("Search result employer name is missing")
    posted = row.get("date_posted")
    posted_at = None
    if isinstance(posted, datetime):
        posted_at = posted.replace(tzinfo=UTC) if posted.tzinfo is None else posted
    elif isinstance(posted, date):
        posted_at = datetime.combine(posted, datetime.min.time(), tzinfo=UTC)
    elif _text(posted):
        try:
            posted_at = datetime.fromisoformat(_text(posted).replace("Z", "+00:00"))
            if posted_at.tzinfo is None:
                posted_at = posted_at.replace(tzinfo=UTC)
        except ValueError:
            pass
    compensation = (
        " ".join(
            filter(
                None,
                [
                    _text(row.get(key))
                    for key in ("currency", "min_amount", "max_amount", "interval")
                ],
            )
        )
        or None
    )
    return SourceJob(
        source=f"jobspy:{site}",
        source_id=_text(row.get("id")) or url,
        board_id=query.id,
        company=company,
        title=title,
        # JobSpy's direct URL is source-provided, not independently employer-verified.
        apply_url=apply_url,
        source_url=url,
        description=_text(row.get("description")),
        locations=[_text(row.get("location"))] if _text(row.get("location")) else [],
        employment_type=_text(row.get("job_type")) or None,
        published_at=posted_at,
        timestamp_kind="aggregator_date" if posted_at else "unknown",
        compensation=compensation,
    )


def _worker_command() -> list[str]:
    return [sys.executable, "-m", "internship_pipeline.sources.jobspy_worker"]


def fetch_search(query: SearchQuery, timeout: float = 60) -> FetchResult:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if not query.sites or any(site not in SUPPORTED_SITES for site in query.sites):
        return FetchResult(complete=False, error="Search requests unsupported or empty sites")
    try:
        process = subprocess.run(
            _worker_command(),
            input=query.model_dump_json(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return FetchResult(
            complete=False, error=f"JobSpy process exceeded {timeout:g}s and was killed"
        )
    except OSError as exc:
        return FetchResult(complete=False, error=f"JobSpy process start failed: {exc}")
    if process.returncode:
        return FetchResult(
            complete=False, error=f"JobSpy process exited with status {process.returncode}"
        )
    try:
        return FetchResult.model_validate(json.loads(process.stdout))
    except (ValueError, TypeError) as exc:
        return FetchResult(complete=False, error=f"Invalid JobSpy worker response: {exc}")
