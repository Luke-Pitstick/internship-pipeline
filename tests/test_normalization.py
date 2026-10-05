from datetime import UTC, datetime

import pytest

from internship_pipeline.models import SourceJob
from internship_pipeline.normalization import canonical_url, content_hash


def posting(**updates):
    return SourceJob(
        source="greenhouse",
        source_id="1",
        board_id="example",
        company="Example",
        title="Intern",
        apply_url="https://example.com/jobs?job=1",
        description="Build systems",
    ).model_copy(update=updates)


def test_url_removes_tracking_and_normalizes_host_only():
    assert canonical_url(" HTTPS://Example.COM:443/Job/?job=1&utm_source=x&gh_src=y#apply ") == (
        "https://example.com/Job/?job=1#apply"
    )


def test_url_preserves_requisition_query_and_route_semantics():
    original = "https://example.com/Jobs/?id=1&id=2&empty=&token=a%2Fb+z&source=internal#/job/1"
    assert canonical_url(original) == original
    assert canonical_url("https://example.com/Jobs?id=1") != canonical_url(
        "https://example.com/jobs?id=2"
    )


@pytest.mark.parametrize("url", ["", "/jobs/1", "javascript:alert(1)", "https://u:p@x.com"])
def test_invalid_or_credential_urls_are_rejected(url):
    with pytest.raises(ValueError):
        canonical_url(url)


def test_content_hash_ignores_source_clocks_and_tracking():
    base = posting()
    duplicate = posting(
        source="indeed",
        source_id="other",
        board_id="search",
        source_url="https://indeed.com/1",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        timestamp_kind="published",
        apply_url="https://example.com/jobs?job=1&utm_medium=feed",
    )
    assert content_hash(base) == content_hash(duplicate)
    assert content_hash(base) != content_hash(posting(description="Build databases"))
    assert content_hash(base) != content_hash(posting(apply_url="https://example.com/jobs?job=2"))


@pytest.mark.parametrize(
    "host,suffix",
    [
        ("jobs.lever.co", "apply"),
        ("jobs.eu.lever.co", "apply"),
        ("jobs.ashbyhq.com", "application"),
    ],
)
def test_known_application_endpoints_share_opportunity_identity(host, suffix):
    assert canonical_url(f"https://{host}/company/req/{suffix}?id=1") == (
        f"https://{host}/company/req?id=1"
    )
    assert canonical_url(f"https://{host}/company/other/{suffix}") != canonical_url(
        f"https://{host}/company/req/{suffix}"
    )


def test_application_suffixes_remain_distinct_on_generic_or_nested_routes():
    assert canonical_url("https://example.com/company/req/apply") == (
        "https://example.com/company/req/apply"
    )
    assert canonical_url("https://jobs.lever.co/company/req/nested/apply") == (
        "https://jobs.lever.co/company/req/nested/apply"
    )
    assert canonical_url("https://jobs.ashbyhq.com/company/application") == (
        "https://jobs.ashbyhq.com/company/application"
    )
