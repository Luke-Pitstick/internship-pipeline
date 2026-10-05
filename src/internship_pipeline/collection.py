"""Polling orchestration; no model inference or notification delivery occurs here."""

from __future__ import annotations

import asyncio
import random
from typing import Any

from internship_pipeline.models import (
    CandidateProfile,
    Company,
    FetchResult,
    SearchQuery,
    Settings,
    utcnow,
)
from internship_pipeline.scheduler import provider_key
from internship_pipeline.storage import Store


def register_targets(store: Store, companies: list[Company], queries: list[SearchQuery]) -> None:
    for company in companies:
        store.register_target(
            f"company:{company.id}",
            "company",
            company.model_dump_json(),
            provider_key(company),
            company.enabled,
        )
    for query in queries:
        store.register_target(
            f"search:{query.id}",
            "search",
            query.model_dump_json(),
            "jobspy:" + ",".join(sorted(query.sites)),
        )


async def collect_due(
    store: Store, profile: CandidateProfile, settings: Settings, force: bool = False
) -> int:
    from internship_pipeline.scheduler import interval_for, next_due
    from internship_pipeline.sources.ats import fetch_company
    from internship_pipeline.sources.jobspy import fetch_search

    semaphore = asyncio.Semaphore(4)
    provider_locks: dict[str, asyncio.Lock] = {}

    async def collect(target: dict[str, Any]) -> int:
        target_id, provider = str(target["id"]), str(target["provider"])
        provider_lock = provider_locks.setdefault(provider, asyncio.Lock())
        async with semaphore, provider_lock:
            now = utcnow()
            if not force and float(target["next_due"]) > now.timestamp():
                return 0
            if not store.claim_target(
                target_id, now.timestamp(), settings.request_timeout_seconds + 90, force
            ):
                return 0
            # One adapter per provider at a time; internal adapter pagination remains library-owned.
            while not store.reserve_provider(provider, utcnow().timestamp(), spacing=1):
                ready_at = store.provider_ready_at(provider)
                if ready_at - utcnow().timestamp() > 2:
                    store.defer_target(target_id, ready_at)
                    return 0
                await asyncio.sleep(0.2)
            try:
                if target["kind"] == "company":
                    company = Company.model_validate_json(str(target["config"]))
                    spec: Company | SearchQuery = company
                    result = await fetch_company(company, settings.request_timeout_seconds)
                else:
                    spec = SearchQuery.model_validate_json(str(target["config"]))
                    result = await asyncio.to_thread(
                        fetch_search, spec, settings.request_timeout_seconds + 30
                    )
            except Exception as exc:
                result = FetchResult(complete=False, error=type(exc).__name__)
                if target["kind"] == "company":
                    spec = Company.model_validate_json(str(target["config"]))
                else:
                    spec = SearchQuery.model_validate_json(str(target["config"]))
            finished = utcnow()
            jobs = store.ingest(target_id, result, profile.revision, finished)
            failures = int(target["failures"]) + 1 if result.error or not result.complete else 0
            due = next_due(
                finished,
                interval_for(spec, settings),
                failures=failures,
                retry_after_seconds=result.retry_after_seconds,
                random_value=random.random(),
            )
            if result.retry_after_seconds:
                store.cooldown_provider(provider, finished.timestamp() + result.retry_after_seconds)
            store.finish_target(target_id, due.timestamp(), result, finished.timestamp())
            return len(jobs)

    targets = store.targets()
    results = await asyncio.gather(*(collect(target) for target in targets))
    return sum(results)
