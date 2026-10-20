"""Recurring directory discovery; verified boards use the normal saved-source worker."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import uuid
from typing import Any
from urllib.parse import urlsplit

from internship_pipeline.models import Company, Settings, utcnow
from internship_pipeline.storage import Store


def discovery_status(store: Store) -> dict[str, Any]:
    with store.connection() as db:
        counts = dict(db.execute("SELECT status,COUNT(*) FROM candidates GROUP BY status"))
        event = db.execute(
            "SELECT at,details FROM events WHERE kind='source_directory' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    details = json.loads(event["details"]) if event else {}
    return {
        "pending": counts.get("pending", 0),
        "monitored": counts.get("monitored", 0),
        "failed": counts.get("failed", 0),
        "unsupported": counts.get("unsupported", 0),
        "directory_checked_at": event["at"] if event else None,
        "directory_error": details.get("error"),
    }


def _stopped(store: Store) -> bool:
    with store.connection() as db:
        return bool(db.execute("SELECT stopped FROM job_ingestion WHERE id=1").fetchone()[0])


async def _refresh_directory(store: Store, settings: Settings) -> None:
    from internship_pipeline.discovery import discover_companies

    now = utcnow().timestamp()
    with store.transaction() as db:
        due = db.execute(
            "SELECT next_due FROM maintenance WHERE name='source_directory'"
        ).fetchone()
        if due and due[0] > now:
            return
        db.execute(
            "INSERT INTO maintenance VALUES('source_directory',?) "
            "ON CONFLICT(name) DO UPDATE SET next_due=excluded.next_due",
            (now + 600,),
        )
    error = None
    try:
        companies = await asyncio.to_thread(
            discover_companies, limit=None, timeout=settings.request_timeout_seconds
        )
        # Mix the provider-sorted directory so early batches cover all providers.
        companies.sort(key=lambda c: hashlib.sha256(c.careers_url.encode()).digest())
        if _stopped(store):
            with store.transaction() as db:
                db.execute("DELETE FROM maintenance WHERE name='source_directory'")
            return
        store.add_candidates(companies)
    except Exception:
        error = "Directory unavailable; retrying automatically."
    with store.transaction() as db:
        db.execute(
            "UPDATE maintenance SET next_due=? WHERE name='source_directory'",
            (utcnow().timestamp() + (600 if error else 86400),),
        )
        db.execute(
            "INSERT INTO events(kind,at,details) VALUES('source_directory',?,?)",
            (now, json.dumps({"error": error})),
        )


def _save_board(store: Store, company: Company) -> bool:
    from ats_scrapers import resolve_careers_url

    from internship_pipeline.search_runs import SourceConfig

    parts = urlsplit(company.careers_url)
    if parts.hostname == "jobs.eu.lever.co":
        raise ValueError("Regional Lever boards are not supported by saved sources")
    resolved = resolve_careers_url(company.careers_url)
    if resolved is None or resolved.ats.value != company.provider:
        raise ValueError("Unsupported company board URL")
    board = resolved.slug
    digest = hashlib.sha256(company.careers_url.encode()).digest()
    minute = int.from_bytes(digest[:2], "big") % 1440
    config = SourceConfig.model_validate(
        {
            "name": f"{company.name} careers"[:120],
            "source": company.provider,
            "board": board,
            "daily_at": f"{minute // 60:02}:{minute % 60:02}",
        }
    )
    with store.transaction() as db:
        if db.execute("SELECT stopped FROM job_ingestion WHERE id=1").fetchone()[0]:
            return False
        # Include paused sources: discovery must never undo a user's pause.
        existing = db.execute(
            "SELECT 1 FROM saved_searches WHERE json_extract(config,'$.source')=? "
            "AND lower(json_extract(config,'$.board'))=lower(?)",
            (config.source, config.board),
        ).fetchone()
        if not existing:
            db.execute(
                "INSERT INTO saved_searches VALUES(?,1,?,0,?)",
                (uuid.uuid4().hex, config.model_dump_json(), utcnow().timestamp()),
            )
        db.execute(
            "UPDATE candidates SET status='monitored',error=NULL WHERE url=?",
            (company.careers_url,),
        )
    return not bool(existing)


async def refresh_discovery(
    store: Store, settings: Settings, force: bool = False, *, stop: threading.Event | None = None
) -> int:
    from internship_pipeline.discovery import validate_company
    from internship_pipeline.search_runs import SearchRuns

    SearchRuns(store)
    if _stopped(store) or not store.claim_discovery(utcnow().timestamp(), force):
        return 0
    await _refresh_directory(store, settings)
    added = 0
    # Bounded batches and persisted candidates resume after restart.
    for candidate in store.candidate_companies(limit=40):
        if (stop is not None and stop.is_set()) or _stopped(store):
            break
        if not store.reserve_provider(candidate.provider, utcnow().timestamp(), spacing=2):
            continue
        validation = await validate_company(candidate, settings.request_timeout_seconds)
        if (stop is not None and stop.is_set()) or _stopped(store):
            break
        if validation.verified:
            try:
                added += _save_board(store, validation.company)
            except ValueError:
                store.finish_candidate(candidate, "unsupported", "UnsupportedBoardURL")
        else:
            store.finish_candidate(
                candidate,
                "failed" if validation.supported else "unsupported",
                "BoardValidationFailed" if validation.supported else "UnsupportedProvider",
            )
        store.claim_discovery(utcnow().timestamp(), force=True)
        await asyncio.sleep(2)
    return added
