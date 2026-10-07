"""Authenticated dashboard access and explicit application tracking."""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from internship_pipeline.config import load_settings
from internship_pipeline.models import Job, Settings
from internship_pipeline.normalization import canonical_url

JOB_ID = re.compile(r"[a-zA-Z0-9_-]{1,128}")
MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_DESCRIPTION = 30000


class _DescriptionText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        elif not self.hidden and tag in {"p", "div", "br", "li", "h1", "h2", "h3", "section"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in {"p", "div", "li", "h1", "h2", "h3", "section"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def plain_description(raw: str) -> tuple[str, bool]:
    parser = _DescriptionText()
    parser.feed(raw[: MAX_DESCRIPTION * 3])
    parser.close()
    text = "\n".join(
        re.sub(r"[ \t]+", " ", line).strip() for line in "".join(parser.parts).splitlines()
    ).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:MAX_DESCRIPTION], len(raw) > MAX_DESCRIPTION * 3 or len(text) > MAX_DESCRIPTION


class DashboardUnavailable(RuntimeError):
    """Return a generic unavailable response without private configuration details."""


class DashboardAPI:
    def __init__(self, settings: Settings | Path) -> None:
        self._configuration = settings
        from internship_pipeline.job_workspace import initialize

        initialize(self.settings.database_path)
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] | None = None
        self._cached_at = float("-inf")

    @property
    def settings(self) -> Settings:
        if isinstance(self._configuration, Settings):
            return self._configuration
        return load_settings(self._configuration)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        # Opening an absent database must fail rather than initialize production state.
        connection = sqlite3.connect(
            self.settings.database_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            deadline = time.monotonic() + 5
            connection.set_progress_handler(lambda: time.monotonic() > deadline, 10000)
            yield connection
        finally:
            connection.close()

    def jobs(
        self,
        *,
        page: int = 1,
        page_size: int = 25,
        search: str = "",
        view: str = "All",
        sort: str = "postedAt",
        direction: str = "desc",
        selected: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            try:
                return self._read_jobs(
                    page=page,
                    page_size=page_size,
                    search=search,
                    view=view,
                    sort=sort,
                    direction=direction,
                    selected=selected,
                )
            except ValueError:
                raise
            except Exception as exc:
                raise DashboardUnavailable("Jobs are temporarily unavailable") from exc

    def detail(self, job_id: str) -> dict[str, Any] | None:
        if not JOB_ID.fullmatch(job_id):
            return None
        result = self.jobs(selected=job_id)
        selected: dict[str, Any] | None = result["selected"]
        return selected

    def update_workspace(self, job_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
        if not JOB_ID.fullmatch(job_id):
            return None
        from internship_pipeline.job_workspace import update

        return update(self.settings.database_path, job_id, body)

    def _read_jobs(
        self,
        *,
        page: int,
        page_size: int,
        search: str,
        view: str,
        sort: str,
        direction: str,
        selected: str | None,
    ) -> dict[str, Any]:
        now = time.time()
        jobs: list[dict[str, Any]] = []
        screened = 0
        screened_applied_closed = 0
        with self.connection() as connection:
            raw_count = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            queues = [
                dict(row)
                for row in connection.execute(
                    "SELECT kind,status,COUNT(*) count FROM tasks "
                    "GROUP BY kind,status ORDER BY kind,status"
                )
            ]
            oldest = connection.execute(
                "SELECT MIN(created) FROM tasks WHERE status IN ('pending','running')"
            ).fetchone()[0]
            sources = dict(
                connection.execute(
                    "SELECT COUNT(*) total,COALESCE(SUM(enabled),0) enabled,"
                    "COALESCE(SUM(enabled AND failures>0),0) failing,"
                    "COALESCE(SUM(enabled AND next_due<?),0) overdue,"
                    "MAX(last_success) last_success "
                    "FROM targets",
                    (now - 60,),
                ).fetchone()
            )
            from internship_pipeline import job_workspace

            ids, total, page = job_workspace.page(
                connection,
                number=page,
                size=page_size,
                search=search,
                view=view,
                sort=sort,
                direction=direction,
            )
            row_ids = list(
                dict.fromkeys(
                    [*ids, *([selected] if selected and JOB_ID.fullmatch(selected) else [])]
                )
            )
            deadline = time.monotonic() + 10
            placeholders = ",".join("?" for _ in row_ids) or "NULL"
            rows = {
                r["id"]: r
                for r in connection.execute(
                    "SELECT id,data,status,first_seen,last_seen FROM jobs WHERE id IN "
                    f"({placeholders})",
                    row_ids,
                )
            }
            for job_id in row_ids:
                if job_id not in rows:
                    continue
                row = rows[job_id]
                if time.monotonic() > deadline:
                    raise DashboardUnavailable("Inventory timeout")
                job = Job.model_validate_json(row["data"])
                screened += 1
                if row["status"] != "open":
                    screened_applied_closed += 1
                if job.id != row["id"] or not JOB_ID.fullmatch(job.id):
                    raise DashboardUnavailable("Invalid job identity")
                # Validate links without converting original apply endpoints into listing URLs.
                canonical_url(job.posting.apply_url)
                source_url = job.posting.source_url
                if source_url:
                    canonical_url(source_url)
                from internship_pipeline.assessments import stored_view

                evaluation = stored_view(connection, job)
                assessment = evaluation["result"]
                description, description_truncated = plain_description(job.posting.description)
                jobs.append(
                    {
                        "id": job.id,
                        "workspace": job_workspace.state(connection, job.id),
                        "company": job.posting.company,
                        "title": job.posting.title,
                        "description": description,
                        "description_truncated": description_truncated,
                        "locations": job.posting.locations,
                        "employment_type": job.posting.employment_type,
                        "term": list(
                            dict.fromkeys(
                                re.findall(
                                    r"\b(?:summer|spring|fall|autumn|winter)(?:\s+20\d{2})?\b",
                                    job.posting.title,
                                    re.I,
                                )
                            )
                        ),
                        "deadline": job.posting.deadline,
                        "source": job.posting.source,
                        "source_url": source_url or None,
                        "application_url": job.posting.apply_url,
                        "source_timestamp": (
                            job.posting.published_at.isoformat()
                            if job.posting.published_at
                            else None
                        ),
                        "timestamp_kind": job.posting.timestamp_kind,
                        "first_seen": row["first_seen"],
                        "last_seen": row["last_seen"],
                        "last_seen_age_seconds": max(0, int(now - row["last_seen"])),
                        "status": row["status"],
                        "applied_at": job.applied_at.isoformat() if job.applied_at else None,
                        "application_status": "applied" if job.applied_at else "not_applied",
                        "event": job.event,
                        "fit": assessment["normalized_fit"] if assessment else None,
                        "role_family": None,
                        "assessment": assessment["recommendation"]
                        if assessment
                        else evaluation["state"],
                        "evaluation": evaluation,
                        "eligible": assessment["eligible"] if assessment else None,
                        "reasons": [],
                        "unknowns": assessment["uncertainty"] if assessment else [],
                    }
                )
        failed = sum(row["count"] for row in queues if row["status"] == "failed")
        health = "degraded" if failed or sources["failing"] or sources["overdue"] else "scheduled"
        if not sources["enabled"]:
            health = "idle"
        return {
            "observed_at": datetime.fromtimestamp(now, UTC).isoformat(),
            "scope": {
                "raw_collected": raw_count,
                "screened_open": screened - screened_applied_closed,
                "screened_applied_closed": screened_applied_closed,
                "limit": page_size,
                "returned": len(jobs),
            },
            "jobs": [job for job in jobs if job["id"] in ids],
            "selected": next((job for job in jobs if job["id"] == selected), None),
            "pagination": {
                "total": total,
                "page": page,
                "pages": max(1, (total + page_size - 1) // page_size),
                "page_size": page_size,
            },
            "health": {
                "status": health,
                "sources": sources,
                "queues": queues,
                "oldest_work_age_seconds": None if oldest is None else max(0, int(now - oldest)),
                "note": (
                    "SQLite state does not verify model-provider health or "
                    "remote email/Sheets acceptance."
                ),
            },
        }

    def mark_applied(self, job_id: str, *, applied: bool = True) -> dict[str, str | None] | None:
        """Record a user-confirmed application once, preserving its first recorded date."""
        if not JOB_ID.fullmatch(job_id):
            return None
        with self._lock:
            connection = None
            try:
                connection = sqlite3.connect(
                    self.settings.database_path.resolve().as_uri() + "?mode=rw",
                    uri=True,
                    timeout=2,
                )
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    row = connection.execute(
                        "SELECT data FROM jobs WHERE id=?", (job_id,)
                    ).fetchone()
                    if row is None:
                        return None
                    job = Job.model_validate_json(row[0])
                    if job.id != job_id:
                        raise DashboardUnavailable("Invalid job identity")
                    applied_at = (job.applied_at or datetime.now(UTC)) if applied else None
                    if job.applied_at != applied_at:
                        job = job.model_copy(update={"applied_at": applied_at})
                        connection.execute(
                            "UPDATE jobs SET data=? WHERE id=?", (job.model_dump_json(), job_id)
                        )
                self._snapshot = None
                return {
                    "id": job_id,
                    "status": "applied" if applied else "not_applied",
                    "applied_at": applied_at.isoformat() if applied_at else None,
                }
            except Exception as exc:
                raise DashboardUnavailable(
                    "Application tracking is temporarily unavailable"
                ) from exc
            finally:
                if connection is not None:
                    connection.close()
