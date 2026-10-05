"""Pure cadence calculations and independent provider request budgets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from internship_pipeline.models import Company, SearchQuery, Settings


def interval_for(target: Company | SearchQuery, settings: Settings) -> float:
    if isinstance(target, SearchQuery):
        return float(settings.search_interval_seconds)
    return float(
        settings.priority_interval_seconds
        if target.priority
        else settings.standard_interval_seconds
    )


def next_due(
    now: datetime,
    interval_seconds: float,
    failures: int = 0,
    retry_after_seconds: float | None = None,
    jitter_fraction: float = 0.1,
    random_value: float = 0.5,
) -> datetime:
    """Schedule bounded exponential backoff; never shorten server cooldowns."""
    if interval_seconds <= 0 or failures < 0:
        raise ValueError("interval must be positive and failures nonnegative")
    if not 0 <= jitter_fraction <= 1 or not 0 <= random_value <= 1:
        raise ValueError("jitter_fraction and random_value must be between zero and one")
    base = min(interval_seconds * 2 ** min(failures, 16), max(interval_seconds, 21600))
    delay = base * (1 + jitter_fraction * (2 * random_value - 1))
    if retry_after_seconds is not None:
        delay = max(delay, retry_after_seconds)
    return now + timedelta(seconds=delay)


def is_due(due_at: datetime | None, now: datetime) -> bool:
    return due_at is None or due_at <= now


def overdue_seconds(due_at: datetime | None, now: datetime) -> float:
    return max(0.0, (now - due_at).total_seconds()) if due_at else 0.0


def provider_key(company: Company) -> str:
    """Group shared provider APIs across company-specific portal subdomains."""
    if company.provider != "auto":
        return company.provider
    try:
        from ats_scrapers import resolve_careers_url

        resolved = resolve_careers_url(company.careers_url)
        if resolved is not None:
            return resolved.ats.value
    except ImportError:
        pass
    return urlsplit(company.careers_url).hostname or company.id


@dataclass
class ProviderBudget:
    """An explicit request-cost window; use one independent instance per provider.

    Budget cost must include caller estimates for detail fetches and pagination.
    The selected library exposes no per-request observer, so this cannot promise
    exact wire request counts. Persist window_start/used/cooldown_until if needed.
    """

    max_requests: int
    window_seconds: float
    window_start: datetime | None = None
    used: int = 0
    cooldown_until: datetime | None = None

    def __post_init__(self) -> None:
        if self.max_requests < 1 or self.window_seconds <= 0 or self.used < 0:
            raise ValueError("Invalid provider budget")

    def _roll_window(self, now: datetime) -> None:
        if self.window_start is None or now >= self.window_start + timedelta(
            seconds=self.window_seconds
        ):
            self.window_start = now
            self.used = 0

    def admit(self, now: datetime, cost: int = 1) -> bool:
        if cost < 1:
            raise ValueError("cost must be positive")
        self._roll_window(now)
        if self.cooldown_until is not None and now < self.cooldown_until:
            return False
        if self.used + cost > self.max_requests:
            return False
        self.used += cost
        return True

    def defer_until(self, now: datetime, cost: int = 1) -> datetime:
        if not 1 <= cost <= self.max_requests:
            raise ValueError("cost must fit the provider budget")
        self._roll_window(now)
        due = now
        if self.used + cost > self.max_requests and self.window_start is not None:
            due = self.window_start + timedelta(seconds=self.window_seconds)
        return max(due, self.cooldown_until) if self.cooldown_until else due

    def cooldown(self, now: datetime, retry_after: float) -> None:
        until = now + timedelta(seconds=max(0, retry_after))
        self.cooldown_until = max(until, self.cooldown_until) if self.cooldown_until else until
