from datetime import UTC, datetime, timedelta

import pytest

from internship_pipeline.models import Company, SearchQuery, Settings
from internship_pipeline.scheduler import (
    ProviderBudget,
    interval_for,
    is_due,
    next_due,
    overdue_seconds,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_priority_standard_and_search_cadences():
    settings = Settings()
    company = Company(id="a", name="A", careers_url="https://example.com")
    assert interval_for(company, settings) == 900
    assert interval_for(company.model_copy(update={"priority": True}), settings) == 300
    assert interval_for(SearchQuery(id="a", search_term="intern"), settings) == 3600


def test_backoff_and_jitter_never_shorten_retry_after():
    assert next_due(NOW, 300, failures=2) == NOW + timedelta(seconds=1200)
    assert next_due(NOW, 300, retry_after_seconds=900, random_value=0) == NOW + timedelta(
        seconds=900
    )
    assert next_due(NOW, 300, random_value=1) == NOW + timedelta(seconds=330)
    assert next_due(NOW, 300, failures=100, jitter_fraction=0) == NOW + timedelta(hours=6)


def test_provider_rate_limit_does_not_slow_other_providers():
    affected = ProviderBudget(3, 60)
    healthy = ProviderBudget(3, 60)
    affected.cooldown(NOW, 120)
    assert not affected.admit(NOW)
    assert healthy.admit(NOW)
    assert affected.defer_until(NOW) == NOW + timedelta(seconds=120)
    assert affected.admit(NOW + timedelta(seconds=120))


def test_budget_reserves_pagination_and_details_cost():
    budget = ProviderBudget(5, 60)
    assert budget.admit(NOW, cost=4)
    assert not budget.admit(NOW, cost=2)
    assert budget.admit(NOW)
    assert budget.defer_until(NOW) == NOW + timedelta(seconds=60)
    assert budget.admit(NOW + timedelta(seconds=60), cost=5)


def test_due_and_overdue():
    assert is_due(None, NOW) and is_due(NOW, NOW)
    assert not is_due(NOW + timedelta(seconds=1), NOW)
    assert overdue_seconds(NOW - timedelta(seconds=10), NOW) == 10
    with pytest.raises(ValueError):
        next_due(NOW, -1)
