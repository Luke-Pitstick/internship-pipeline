"""Provider failure metadata retained at the collection boundary."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from internship_pipeline.models import FetchResult


class ProviderError(Exception):
    def __init__(self, status: int, retry_after: str | None = None):
        super().__init__(f"Provider returned HTTP {status}")
        self.status = status
        self.retry_after = retry_after


def retry_delay(value: str | None, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
        return max(0.0, seconds) if math.isfinite(seconds) else None
    except ValueError:
        try:
            instant = parsedate_to_datetime(value)
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=UTC)
            return max(0.0, (instant - (now or datetime.now(UTC))).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None


def failure_result(exc: Exception) -> FetchResult:
    delay = retry_delay(getattr(exc, "retry_after", None))
    response = getattr(exc, "response", None)
    if response is not None:
        delay = retry_delay(response.headers.get("Retry-After"))
    if delay is None and (getattr(exc, "status", None) == 429 or re.search(r"\b429\b", str(exc))):
        # Explicit local cooldown, never presented as a server-provided header.
        delay = 60.0
    return FetchResult(
        complete=False, error=f"{type(exc).__name__}: {exc}", retry_after_seconds=delay
    )
