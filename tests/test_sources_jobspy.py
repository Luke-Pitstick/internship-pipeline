import logging
import sys
import time
from datetime import date
from types import SimpleNamespace

import pytest

from internship_pipeline.models import SearchQuery
from internship_pipeline.sources import jobspy, jobspy_worker


def query(**updates):
    return SearchQuery(
        id="intern-denver", search_term="software intern", results_wanted=2
    ).model_copy(update=updates)


def row(id="1"):
    return dict(
        id=id,
        site="indeed",
        title="Intern",
        company="Example",
        job_url=f"https://indeed.com/viewjob?jk={id}",
        job_url_direct=f"https://example.com/jobs?id={id}",
        location="Denver",
        description="Build systems",
        date_posted=date(2026, 1, 1),
    )


def install_fake(monkeypatch, rows, log_message=None):
    logger = logging.getLogger("JobSpy:Indeed")
    logger.setLevel(logging.ERROR)

    def scrape_jobs(**kwargs):
        assert kwargs["fetch_description"] is True
        assert kwargs["hours_old"] == 72
        if log_message:
            logger.error(log_message)
        return SimpleNamespace(to_dict=lambda orient: rows)

    monkeypatch.setitem(sys.modules, "jobspy", SimpleNamespace(scrape_jobs=scrape_jobs))


def test_normalization_uses_direct_url_and_retains_aggregator_date():
    normalized = jobspy.normalize_row(row(), query())
    assert normalized.apply_url == "https://example.com/jobs?id=1"
    assert normalized.timestamp_kind == "aggregator_date"
    assert normalized.source_id == "1" and normalized.source == "jobspy:indeed"
    assert normalized.published_at.date() == date(2026, 1, 1)
    assert jobspy.normalize_row(dict(row(), description=float("nan")), query()).description == ""


def test_cap_marks_search_incomplete_and_preserves_rows(monkeypatch):
    install_fake(monkeypatch, [row("1"), row("2")])
    result = jobspy_worker.collect(query())
    assert len(result.jobs) == 2 and not result.complete and "partition" in result.error
    assert result.coverage_limited


def test_silent_library_rate_limit_logging_is_collected(monkeypatch):
    install_fake(monkeypatch, [row()], "Indeed response status code 429")
    result = jobspy_worker.collect(query())
    assert len(result.jobs) == 1 and not result.complete and result.retry_after_seconds == 60
    assert not result.coverage_limited


def test_uncapped_success_and_empty_coverage(monkeypatch):
    install_fake(monkeypatch, [row()])
    assert jobspy_worker.collect(query()).complete
    install_fake(monkeypatch, [])
    assert not jobspy_worker.collect(query()).complete


def test_hanging_process_is_killed_at_wall_clock_deadline(monkeypatch):
    monkeypatch.setattr(
        jobspy, "_worker_command", lambda: [sys.executable, "-c", "import time; time.sleep(60)"]
    )
    start = time.monotonic()
    result = jobspy.fetch_search(query(), timeout=0.05)
    assert time.monotonic() - start < 3
    assert not result.complete and "was killed" in result.error


def test_invalid_process_output_and_unsupported_site(monkeypatch):
    monkeypatch.setattr(
        jobspy, "_worker_command", lambda: [sys.executable, "-c", "print('broken')"]
    )
    assert not jobspy.fetch_search(query()).complete
    assert "unsupported" in jobspy.fetch_search(query(sites=["fabricated"])).error


@pytest.mark.parametrize("employer", [None, float("nan"), "", "  "])
def test_optional_missing_employer_retains_valid_rows_as_partial_coverage(monkeypatch, employer):
    install_fake(monkeypatch, [row("valid"), dict(row("missing"), company=employer)])
    result = jobspy_worker.collect(query(results_wanted=10))
    assert [job.source_id for job in result.jobs] == ["valid"]
    assert not result.complete and result.coverage_limited
    assert "Skipped 1 postings with missing employer names" in result.error
    assert result.retry_after_seconds is None


def test_result_cap_counts_raw_rows_including_skipped_optional_metadata(monkeypatch):
    install_fake(monkeypatch, [row("valid"), dict(row("missing"), company=None)])
    result = jobspy_worker.collect(query(results_wanted=2))
    assert len(result.jobs) == 1
    assert not result.complete and result.coverage_limited
    assert "missing employer" in result.error and "Result cap reached for indeed" in result.error


@pytest.mark.parametrize("updates", [{"title": None}, {"site": "linkedin"}])
def test_missing_required_identity_is_a_failure_and_preserves_other_rows(monkeypatch, updates):
    install_fake(monkeypatch, [row("valid"), dict(row("bad"), **updates)])
    result = jobspy_worker.collect(query(results_wanted=10))
    assert [job.source_id for job in result.jobs] == ["valid"]
    assert not result.complete and not result.coverage_limited
    assert "Invalid search posting" in result.error


def test_rate_limit_remains_a_failure_even_with_missing_employer_rows(monkeypatch):
    install_fake(
        monkeypatch,
        [row("valid"), dict(row("missing"), company=None)],
        "Indeed response status code 429",
    )
    result = jobspy_worker.collect(query(results_wanted=10))
    assert len(result.jobs) == 1 and not result.complete and not result.coverage_limited
    assert result.retry_after_seconds == 60
