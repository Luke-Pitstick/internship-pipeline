"""Bounded daily board validation runs outside the fast collector process."""

from __future__ import annotations

import asyncio

from internship_pipeline.models import Settings, utcnow
from internship_pipeline.storage import Store


async def refresh_discovery(store: Store, settings: Settings, force: bool = False) -> int:
    from internship_pipeline.collection import register_targets
    from internship_pipeline.discovery import validate_company
    from internship_pipeline.scheduler import provider_key

    if not store.claim_discovery(utcnow().timestamp(), force):
        return 0
    added = 0
    existing = {row["id"] for row in store.targets()}
    for candidate in store.candidate_companies():
        if f"company:{candidate.id}" in existing:
            store.finish_candidate(candidate, "monitored")
            continue
        provider = provider_key(candidate)
        # Discovery shares persistent cooldowns with the collector and yields to them.
        if not store.reserve_provider(provider, utcnow().timestamp(), spacing=2):
            continue
        validation = await validate_company(candidate, settings.request_timeout_seconds)
        if validation.verified:
            company = validation.company.model_copy(update={"enabled": True})
            register_targets(store, [company], [])
            store.finish_candidate(candidate, "monitored")
            existing.add(f"company:{company.id}")
            added += 1
        else:
            store.finish_candidate(
                candidate,
                "failed" if validation.supported else "unsupported",
                "BoardValidationFailed" if validation.supported else "UnsupportedProvider",
            )
        await asyncio.sleep(2)
    return added
