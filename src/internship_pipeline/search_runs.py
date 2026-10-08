"""Saved sources, durable schedules and collection independent of model work."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from internship_pipeline.assessments import current_revisions, resolved_model, stored_view
from internship_pipeline.models import Company, FetchResult, Job, SearchQuery, Settings
from internship_pipeline.profile_settings import ProfileSettings
from internship_pipeline.queue import Queue
from internship_pipeline.run_limits import SCHEMA as LIMIT_SCHEMA
from internship_pipeline.sources.jobspy import SUPPORTED_SITES
from internship_pipeline.storage import Store, enqueue

SCHEMA = """
CREATE TABLE IF NOT EXISTS saved_searches (
 id TEXT PRIMARY KEY, revision INTEGER NOT NULL, config TEXT NOT NULL,
 paused INTEGER NOT NULL DEFAULT 0, next_due REAL);
CREATE TABLE IF NOT EXISTS search_runs (
 id TEXT PRIMARY KEY, search_id TEXT NOT NULL, config TEXT NOT NULL, target_id TEXT NOT NULL,
 stage TEXT NOT NULL, created REAL NOT NULL, collected_at REAL, result TEXT,
 collected INTEGER NOT NULL DEFAULT 0, error TEXT,
 cancelled INTEGER NOT NULL DEFAULT 0, review_backlog INTEGER NOT NULL DEFAULT 0,
 max_jobs INTEGER NOT NULL, max_calls INTEGER NOT NULL, max_tokens INTEGER NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS search_run_active ON search_runs(search_id)
 WHERE stage IN ('queued','collecting','fetched');
CREATE TABLE IF NOT EXISTS search_run_jobs (
 run_id TEXT NOT NULL REFERENCES search_runs(id), job_id TEXT NOT NULL REFERENCES jobs(id),
 PRIMARY KEY(run_id,job_id));
"""


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    source: Literal["greenhouse", "lever", "ashby", "jobspy"] = "greenhouse"
    board: str = ""
    search_term: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=200)
    country: str = Field(default="USA", min_length=1, max_length=80)
    sites: list[str] = Field(default_factory=lambda: ["indeed"])
    hours_old: int = Field(default=72, ge=1, le=8760)
    results_wanted: int = Field(default=100, ge=1, le=1000)
    daily_at: str | None = None
    timezone: str = "UTC"
    max_jobs: int = Field(default=20, ge=0, le=1000)
    max_calls: int = Field(default=30, ge=0, le=3000)
    max_tokens: int = Field(default=5_000_000, ge=0, le=100_000_000)

    @model_validator(mode="after")
    def valid(self) -> SourceConfig:
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Enter a search name")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError("Choose an IANA timezone") from None
        if self.daily_at is not None and not re.fullmatch(
            r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", self.daily_at
        ):
            raise ValueError("Enter a daily schedule as HH:MM")
        if self.source == "jobspy":
            if not self.search_term.strip():
                raise ValueError("Enter a search term")
            if (
                not self.sites
                or len(self.sites) != len(set(self.sites))
                or set(self.sites) - SUPPORTED_SITES
            ):
                raise ValueError("Choose supported broad-search sites")
            if self.board:
                raise ValueError("Broad search does not use a company board")
        else:
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", self.board):
                raise ValueError("Enter only the company board token")
            if self.search_term:
                raise ValueError("Company boards do not use a search term")
        return self

    def target(self, search_id: str) -> Company | SearchQuery:
        if self.source == "jobspy":
            return SearchQuery(
                id=search_id,
                search_term=self.search_term,
                location=self.location,
                country=self.country,
                sites=self.sites,
                hours_old=self.hours_old,
                results_wanted=self.results_wanted,
            )
        urls = {
            "greenhouse": "https://boards.greenhouse.io/",
            "lever": "https://jobs.lever.co/",
            "ashby": "https://jobs.ashbyhq.com/",
        }
        return Company(
            id=f"browser-{self.source}-{self.board}",
            name=self.name,
            careers_url=urls[self.source] + self.board,
            provider=self.source,
        )


class SourceSave(SourceConfig):
    id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    expected_revision: int = Field(ge=0)


class RunStart(BaseModel):
    search_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    review_backlog: bool = False


class Revision(BaseModel):
    expected_revision: int = Field(ge=1)


class Pause(Revision):
    paused: bool


def next_due(config: SourceConfig, now: float) -> float | None:
    if config.daily_at is None:
        return None
    zone = ZoneInfo(config.timezone)
    day = datetime.fromtimestamp(now, zone).date()
    hour, minute = map(int, config.daily_at.split(":"))
    for offset in range(370):
        local = datetime.combine(day + timedelta(days=offset), datetime.min.time(), zone).replace(
            hour=hour, minute=minute
        )
        stamp = local.timestamp()
        # Nonexistent DST times skip that day; repeated times use the first occurrence.
        if datetime.fromtimestamp(stamp, zone).replace(tzinfo=None) != local.replace(tzinfo=None):
            continue
        if stamp > now:
            return stamp
    raise ValueError("Cannot compute next schedule")


class SearchRuns:
    def __init__(self, store: Store):
        self.store = store
        with store.connection() as db:
            db.executescript(SCHEMA + LIMIT_SCHEMA)

    def settings(self) -> dict[str, Any]:
        with self.store.connection() as db:
            items = []
            for row in db.execute("SELECT * FROM saved_searches ORDER BY rowid"):
                success = db.execute(
                    "SELECT MAX(collected_at) FROM search_runs WHERE "
                    "search_id=? AND stage='collected' AND error IS NULL",
                    (row["id"],),
                ).fetchone()[0]
                items.append(
                    {
                        "id": row["id"],
                        "revision": row["revision"],
                        **json.loads(row["config"]),
                        "paused": bool(row["paused"]),
                        "next_run": row["next_due"],
                        "last_success": success,
                    }
                )
        return {
            "searches": items,
            "sources": ["greenhouse", "lever", "ashby", "jobspy"],
            "sites": sorted(SUPPORTED_SITES),
        }

    def save(self, body: SourceSave) -> dict[str, Any]:
        config = SourceConfig.model_validate(body.model_dump(exclude={"id", "expected_revision"}))
        search_id = body.id or uuid.uuid4().hex
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT revision,paused FROM saved_searches WHERE id=?", (search_id,)
            ).fetchone()
            revision = row["revision"] if row else 0
            if revision != body.expected_revision:
                raise ValueError("Search changed. Reload before saving.")
            db.execute(
                "INSERT INTO saved_searches VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "revision=excluded.revision,config=excluded.config,next_due=excluded.next_due",
                (
                    search_id,
                    revision + 1,
                    config.model_dump_json(),
                    row["paused"] if row else 0,
                    None if row and row["paused"] else next_due(config, time.time()),
                ),
            )
        return self.settings()

    def pause(self, search_id: str, body: Pause) -> dict[str, Any]:
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM saved_searches WHERE id=?", (search_id,)).fetchone()
            if not row or row["revision"] != body.expected_revision:
                raise ValueError("Search changed. Reload.")
            config = SourceConfig.model_validate_json(row["config"])
            db.execute(
                "UPDATE saved_searches SET paused=?,revision=revision+1,next_due=? WHERE id=?",
                (body.paused, None if body.paused else next_due(config, time.time()), search_id),
            )
        return self.settings()

    def delete(self, search_id: str, body: Revision) -> dict[str, Any]:
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT revision FROM saved_searches WHERE id=?", (search_id,)
            ).fetchone()
            if not row or row[0] != body.expected_revision:
                raise ValueError("Search changed. Reload.")
            db.execute("UPDATE search_runs SET cancelled=1 WHERE search_id=?", (search_id,))
            db.execute(
                "UPDATE search_runs SET stage='cancelled' WHERE search_id=? "
                "AND stage IN ('queued','collecting','fetched')",
                (search_id,),
            )
            db.execute("DELETE FROM saved_searches WHERE id=?", (search_id,))
        return self.settings()

    def _start(
        self, db: sqlite3.Connection, search_id: str, review_backlog: bool, now: float
    ) -> str:
        db.execute(
            "UPDATE search_runs SET stage='failed',error='collection_worker_failed' WHERE id IN "
            "(SELECT json_extract(payload,'$.run_id') FROM tasks WHERE "
            "kind='collection_run' AND status='failed') "
            "AND stage IN ('queued','collecting','fetched')"
        )
        active = db.execute(
            "SELECT id FROM search_runs WHERE search_id=? AND stage IN "
            "('queued','collecting','fetched')",
            (search_id,),
        ).fetchone()
        source = db.execute("SELECT * FROM saved_searches WHERE id=?", (search_id,)).fetchone()
        if not source:
            raise ValueError("Save a search in Settings first.")
        if source["paused"]:
            raise ValueError("Resume this search before running it.")
        if active:
            active_id: str = active[0]
            return active_id
        config = SourceConfig.model_validate_json(source["config"])
        target = config.target(search_id)
        run_id = uuid.uuid4().hex
        target_id = ("search:" if config.source == "jobspy" else "company:") + target.id
        db.execute(
            "INSERT INTO "
            "search_runs(id,search_id,config,target_id,stage,created,review_ba"
            "cklog,max_jobs,max_calls,max_tokens) "
            "VALUES(?,?,?,?,'queued',?,?,?,?,?)",
            (
                run_id,
                search_id,
                config.model_dump_json(),
                target_id,
                now,
                review_backlog,
                config.max_jobs,
                config.max_calls,
                config.max_tokens,
            ),
        )
        enqueue(db, "collection_run", "collection-run:" + run_id, {"run_id": run_id}, now)
        return run_id

    def start(self, search_id: str, review_backlog: bool = False) -> dict[str, Any]:
        with self.store.transaction() as db:
            run_id = self._start(db, search_id, review_backlog, time.time())
        return self.view(run_id)

    def schedule(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        count = 0
        with self.store.transaction() as db:
            for row in db.execute(
                "SELECT * FROM saved_searches WHERE paused=0 AND next_due<=?", (now,)
            ).fetchall():
                self._start(db, row["id"], False, now)
                config = SourceConfig.model_validate_json(row["config"])
                db.execute(
                    "UPDATE saved_searches SET next_due=? WHERE id=?",
                    (next_due(config, now), row["id"]),
                )
                count += 1
        return count

    def cancel(self, run_id: str) -> dict[str, Any]:
        with self.store.transaction() as db:
            if not db.execute("SELECT 1 FROM search_runs WHERE id=?", (run_id,)).fetchone():
                raise KeyError(run_id)
            db.execute(
                "UPDATE search_runs SET cancelled=1,stage=CASE WHEN stage IN "
                "('queued','collecting','fetched') THEN 'cancelled' ELSE stage END WHERE id=?",
                (run_id,),
            )
        return self.view(run_id)

    def review_backlog(self, run_id: str) -> dict[str, Any]:
        with self.store.transaction() as db:
            if not db.execute("SELECT 1 FROM search_runs WHERE id=?", (run_id,)).fetchone():
                raise KeyError(run_id)
            db.execute(
                "UPDATE search_runs SET review_backlog=1 WHERE id=? AND cancelled=0", (run_id,)
            )
        return self.view(run_id)

    def history(self) -> dict[str, Any]:
        with self.store.connection() as db:
            ids = [
                r[0]
                for r in db.execute("SELECT id FROM search_runs ORDER BY created DESC LIMIT 100")
            ]
        return {"runs": [self.view(i)["run"] for i in ids]}

    def view(self, run_id: str | None = None) -> dict[str, Any]:
        with self.store.connection() as db:
            row = (
                db.execute("SELECT * FROM search_runs WHERE id=?", (run_id,)).fetchone()
                if run_id
                else db.execute(
                    "SELECT * FROM search_runs ORDER BY created DESC LIMIT 1"
                ).fetchone()
            )
            if not row:
                return {"run": None}
            counts = dict(
                evaluated=0,
                pending=0,
                review=0,
                rejected=0,
                recommended=0,
                evaluation_errors=0,
                inactive=0,
            )
            errors: set[str] = set()
            waiting_backlog = 0
            for item in db.execute(
                "SELECT j.data FROM jobs j JOIN search_run_jobs r "
                "ON j.id=r.job_id WHERE r.run_id=?",
                (row["id"],),
            ):
                job = Job.model_validate_json(item[0])
                if job.status != "open" or job.applied_at:
                    counts["inactive"] += 1
                    continue
                view = stored_view(db, job)
                if view["state"] == "complete":
                    counts["evaluated"] += 1
                    recommendation = view["result"]["recommendation"]
                    counts[
                        {"review": "review", "reject": "rejected"}.get(
                            recommendation, "recommended"
                        )
                    ] += 1
                elif view["state"] == "error":
                    counts["evaluation_errors"] += 1
                    if view.get("error"):
                        errors.add(view["error"])
                else:
                    counts["pending"] += 1
                    if job.event == "backlog" and not row["review_backlog"]:
                        waiting_backlog += 1
            usage = db.execute(
                "SELECT "
                "COUNT(*),COALESCE(SUM(reserved_tokens),0),SUM(input_tokens),SUM(o"
                "utput_tokens) FROM run_reservations WHERE run_id=?",
                (row["id"],),
            ).fetchone()
            backlog = db.execute(
                "SELECT COUNT(*) FROM search_run_jobs r JOIN jobs j ON "
                "j.id=r.job_id WHERE r.run_id=? AND json_extract(j.data,'$.event')='backlog'",
                (row["id"],),
            ).fetchone()[0]
            stage = row["stage"]
            source_error = row["error"]
            task = db.execute(
                "SELECT status,error FROM tasks WHERE key=?", ("collection-run:" + row["id"],)
            ).fetchone()
            if task and task["status"] == "failed":
                stage = "needs_attention"
                source_error = task["error"] or "Collection worker needs attention"
            if row["cancelled"]:
                stage = "cancelled"
            elif stage == "collected":
                stage = "evaluating" if counts["pending"] else "complete"
                if counts["pending"] and waiting_backlog == counts["pending"]:
                    stage = "awaiting_backlog_review"
                elif counts["pending"]:
                    profile, revision = current_revisions(db)
                    if not profile or not resolved_model(db, revision):
                        stage = "awaiting_model_configuration"
                if row["error"] or counts["evaluation_errors"]:
                    stage = "needs_attention"
            return {
                "run": {
                    "id": row["id"],
                    "search_id": row["search_id"],
                    "name": json.loads(row["config"])["name"],
                    "review_backlog": bool(row["review_backlog"]),
                    "backlog": backlog,
                    "waiting_backlog": waiting_backlog,
                    "limits": {
                        "jobs": row["max_jobs"],
                        "calls": row["max_calls"],
                        "tokens": row["max_tokens"],
                    },
                    "usage": {
                        "calls": usage[0],
                        "reserved_tokens": usage[1],
                        "input_tokens": usage[2],
                        "output_tokens": usage[3],
                    },
                    "stage": stage,
                    "created_at": row["created"],
                    "collected_at": row["collected_at"],
                    "collected": row["collected"],
                    "source_error": source_error,
                    "evaluation_error_codes": sorted(errors),
                    **counts,
                }
            }

    async def process_next(self, settings: Settings) -> bool:
        from internship_pipeline.sources.ats import fetch_company

        self.schedule()
        queue = Queue(self.store, lease_seconds=int(settings.request_timeout_seconds + 120))
        task = queue.claim(["collection_run"])
        if task is None:
            return False
        now = time.time()
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM search_runs WHERE id=?", (task.payload["run_id"],)
            ).fetchone()
            if row is None or row["stage"] not in {"queued", "collecting", "fetched"}:
                db.execute(
                    "UPDATE tasks SET status='done' WHERE id=? AND token=?", (task.id, task.token)
                )
                return False
            db.execute(
                "UPDATE search_runs SET stage=CASE WHEN stage='fetched' THEN stage "
                "ELSE 'collecting' END WHERE id=?",
                (row["id"],),
            )
        config = SourceConfig.model_validate_json(row["config"])
        target = config.target(row["search_id"])
        provider = config.source
        target_id = row["target_id"]
        self.store.register_target(
            target_id,
            "search" if provider == "jobspy" else "company",
            target.model_dump_json(),
            provider,
            collection_owner="saved_search",
        )
        if row["stage"] == "fetched":
            result = FetchResult.model_validate_json(row["result"])
            collected_at = row["collected_at"]
        else:
            ready_at = self.store.provider_ready_at(provider)
            if not self.store.reserve_provider(provider, now, spacing=2):
                queue.defer(task, max(0, ready_at - now))
                return False
            if isinstance(target, Company):
                result = await fetch_company(target, settings.request_timeout_seconds)
            else:
                from internship_pipeline.sources.jobspy import fetch_search

                result = await asyncio.to_thread(
                    fetch_search, target, settings.request_timeout_seconds
                )
            if result.error:
                result = result.model_copy(update={"error": "source_request_failed"})
            # Persist the fetch before ingestion; resume it without another public request.
            collected_at = time.time()
            with self.store.transaction() as db:
                changed = db.execute(
                    "UPDATE search_runs SET stage='fetched',result=?,"
                    "collected_at=? WHERE id=? AND cancelled=0 AND EXISTS (SELECT 1 FROM tasks "
                    "WHERE id=? AND token=? AND status='running')",
                    (result.model_dump_json(), collected_at, row["id"], task.id, task.token),
                )
                if not changed.rowcount:
                    return False
        profile = ProfileSettings(self.store).read().candidate()

        def checkpoint(db: sqlite3.Connection) -> None:
            if db.execute("SELECT cancelled FROM search_runs WHERE id=?", (row["id"],)).fetchone()[
                0
            ]:
                raise ValueError("Run cancelled")
            current = db.execute("SELECT token,status FROM tasks WHERE id=?", (task.id,)).fetchone()
            if current[0] != task.token or current[1] != "running":
                raise ValueError("Run lease changed")
            for posting in result.jobs:
                db.execute(
                    "INSERT OR IGNORE INTO search_run_jobs SELECT ?,job_id FROM "
                    "observations WHERE source=? AND board_id=? AND source_id=?",
                    (row["id"], posting.source, posting.board_id, posting.source_id),
                )
            count = db.execute(
                "SELECT COUNT(*) FROM search_run_jobs WHERE run_id=?", (row["id"],)
            ).fetchone()[0]
            error = result.error or (None if result.complete else "Incomplete inventory")
            db.execute(
                "UPDATE search_runs SET stage='collected',collected=?,error=?,"
                "result=NULL WHERE id=?",
                (count, error, row["id"]),
            )
            db.execute(
                "UPDATE tasks SET status='done',lease_until=NULL,updated=?,error=NULL "
                "WHERE id=? AND token=?",
                (time.time(), task.id, task.token),
            )
            db.execute(
                "UPDATE targets SET complete=?,error=?,last_attempt=?,last_success="
                "CASE WHEN ? THEN ? ELSE last_success END WHERE id=?",
                (int(result.complete), error, collected_at, not error, collected_at, target_id),
            )
            if result.retry_after_seconds:
                db.execute(
                    "UPDATE providers SET next_allowed=MAX(next_allowed,?) WHERE id=?",
                    (collected_at + result.retry_after_seconds, provider),
                )

        self.store.ingest(
            target_id,
            result,
            profile.revision,
            datetime.fromtimestamp(collected_at, UTC),
            checkpoint=checkpoint,
        )
        return True


def search_router(runs: SearchRuns, owner: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api", dependencies=[Depends(owner)])

    def invoke(call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return call()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        except KeyError:
            raise HTTPException(404, "Search or run not found") from None

    @router.get("/search-settings")
    def read() -> dict[str, Any]:
        return runs.settings()

    @router.post("/search-settings")
    def save(body: SourceSave) -> dict[str, Any]:
        return invoke(lambda: runs.save(body))

    @router.post("/search-settings/{search_id}/pause")
    def pause(search_id: str, body: Pause) -> dict[str, Any]:
        return invoke(lambda: runs.pause(search_id, body))

    @router.post("/search-settings/{search_id}/delete")
    def delete(search_id: str, body: Revision) -> dict[str, Any]:
        return invoke(lambda: runs.delete(search_id, body))

    @router.post("/search-runs", status_code=202)
    def start(body: RunStart) -> dict[str, Any]:
        return invoke(lambda: runs.start(body.search_id, body.review_backlog))

    @router.get("/search-runs/current")
    def current() -> dict[str, Any]:
        return runs.view()

    @router.get("/search-runs")
    def history() -> dict[str, Any]:
        return runs.history()

    @router.get("/search-runs/{run_id}")
    def view(run_id: str) -> dict[str, Any]:
        return runs.view(run_id)

    @router.post("/search-runs/{run_id}/review-backlog")
    def review(run_id: str) -> dict[str, Any]:
        return invoke(lambda: runs.review_backlog(run_id))

    @router.post("/search-runs/{run_id}/cancel")
    def cancel(run_id: str) -> dict[str, Any]:
        return invoke(lambda: runs.cancel(run_id))

    return router
