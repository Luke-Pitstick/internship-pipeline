"""Executable boundary for blocking JobSpy. Never imported by core startup."""

from __future__ import annotations

import contextlib
import io
import logging
import sys

from internship_pipeline.models import FetchResult, SearchQuery
from internship_pipeline.sources.errors import failure_result
from internship_pipeline.sources.jobspy import MissingEmployerError, normalize_row


class _Errors(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def collect(query: SearchQuery) -> FetchResult:
    # Library configures its own non-propagating loggers. Attach after importing.
    from jobspy import scrape_jobs

    errors = _Errors()
    loggers = [
        logger
        for name, logger in logging.Logger.manager.loggerDict.items()
        if isinstance(logger, logging.Logger) and "jobspy" in name.lower()
    ]
    for logger in loggers:
        logger.addHandler(errors)
    jobs = []
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            frame = scrape_jobs(
                site_name=query.sites,
                search_term=query.search_term,
                google_search_term=query.search_term if "google" in query.sites else None,
                location=query.location or None,
                country_indeed=query.country,
                hours_old=query.hours_old,
                results_wanted=query.results_wanted,
                description_format="markdown",
                fetch_description=True,
                verbose=0,
            )
        rows = frame.to_dict(orient="records")
        counts = dict.fromkeys(query.sites, 0)
        missing_employers = 0
        for row in rows:
            site = row.get("site")
            if isinstance(site, str) and site in counts:
                # Provider caps include rows omitted because metadata is missing.
                counts[site] += 1
            try:
                job = normalize_row(row, query)
                jobs.append(job)
            except MissingEmployerError:
                missing_employers += 1
            except Exception as exc:
                errors.messages.append(f"Invalid search posting: {exc}")
        actual_failure = bool(errors.messages)
        if missing_employers:
            errors.messages.append(
                f"Skipped {missing_employers} postings with missing employer names; "
                "coverage is partial"
            )
        capped = [site for site, count in counts.items() if count >= query.results_wanted]
        if capped:
            errors.messages.append(
                f"Result cap reached for {', '.join(capped)}; partition the query"
            )
        # Empty results can mean exhaustion, blocking or unsupported site filters.
        if not rows:
            errors.messages.append("Empty search response; coverage cannot be verified")
        text = "; ".join(dict.fromkeys(errors.messages)) or None
        return FetchResult(
            jobs=jobs,
            complete=text is None,
            error=text,
            retry_after_seconds=60 if text and "429" in text else None,
            coverage_limited=text is not None and not actual_failure,
        )
    except Exception as exc:
        result = failure_result(exc)
        result.jobs = jobs
        return result
    finally:
        for logger in loggers:
            logger.removeHandler(errors)


def main() -> None:
    try:
        query = SearchQuery.model_validate_json(sys.stdin.read())
        result = collect(query)
    except Exception as exc:
        result = failure_result(exc)
    sys.stdout.write(result.model_dump_json())


if __name__ == "__main__":
    main()
