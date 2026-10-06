"""Authenticated dashboard access and explicit application tracking."""

from __future__ import annotations

import os
import re
import sqlite3
import stat
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from internship_pipeline.config import load_settings
from internship_pipeline.models import Job, ResumeArtifact, Settings
from internship_pipeline.normalization import canonical_url

JOB_ID = re.compile(r"[a-zA-Z0-9_-]{1,128}")
MAX_JOBS = 1000
MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_DESCRIPTION = 30000
SAFE_REVIEW_WARNINGS = {
    "Changed custom-section claims require factual review",
    "Semantic grounding is unverified; review rewritten claims against factual experience",
    "Text origin outside the page requires visual review",
}


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


def review_warnings(artifact: ResumeArtifact | None) -> list[str]:
    if artifact is None:
        return []
    warnings = [item for item in artifact.review_warnings if item in SAFE_REVIEW_WARNINGS]
    if any(item not in SAFE_REVIEW_WARNINGS for item in artifact.review_warnings):
        warnings.append("Additional stored review warnings need private review of the PDF.")
    return list(dict.fromkeys(warnings))[:10]


def resume_status(artifact: ResumeArtifact | None) -> str:
    if artifact is not None:
        return (
            "draft_requires_review"
            if artifact.engine == "original-latex"
            else "legacy_preview_requires_review"
        )
    return (
        "awaiting_latex_source" if os.getenv("RESUME_GENERATION_PAUSED") == "1" else "not_generated"
    )


class DashboardUnavailable(RuntimeError):
    """Return a generic unavailable response without private configuration details."""


class DashboardAPI:
    def __init__(self, settings: Settings | Path) -> None:
        self._configuration = settings
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

    def jobs(self) -> dict[str, Any]:
        with self._lock:
            try:
                snapshot = self._read_jobs()
            except Exception as exc:
                # Failed screening must not return raw inventory or a previously healthy view.
                self._snapshot = None
                raise DashboardUnavailable("Jobs are temporarily unavailable") from exc
            self._snapshot = snapshot
            self._cached_at = time.monotonic()
            return snapshot

    def _read_jobs(self) -> dict[str, Any]:
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
            deadline = time.monotonic() + 10
            for row in connection.execute(
                "SELECT id,data,status,first_seen,last_seen FROM jobs WHERE status='open' "
                "OR json_extract(data,'$.applied_at') IS NOT NULL "
                "ORDER BY first_seen DESC LIMIT ?",
                (MAX_JOBS,),
            ):
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
                artifact = self._artifact(connection, job.id)
                description, description_truncated = plain_description(job.posting.description)
                jobs.append(
                    {
                        "id": job.id,
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
                        "resume": {
                            "available": artifact is not None,
                            "download_path": f"/api/resumes/{job.id}" if artifact else None,
                            "created_at": artifact.created_at.isoformat() if artifact else None,
                            "engine": artifact.engine if artifact else None,
                            "review_warnings": review_warnings(artifact),
                            "status": resume_status(artifact),
                        },
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
                "limit": MAX_JOBS,
                "returned": len(jobs),
            },
            "jobs": jobs,
            "health": {
                "status": health,
                "sources": sources,
                "queues": queues,
                "oldest_work_age_seconds": None if oldest is None else max(0, int(now - oldest)),
                "resume_generation_paused": os.getenv("RESUME_GENERATION_PAUSED") == "1",
                "resume_model": self.settings.resume_model,
                "resume_reasoning_effort": self.settings.resume_reasoning_effort,
                "note": "SQLite state does not verify inference or local relay delivery.",
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

    def _artifact_path(self, artifact: ResumeArtifact) -> Path | None:
        try:
            root = self.settings.artifact_dir.resolve(strict=True)
            if self.settings.artifact_dir.is_symlink() or not root.is_dir():
                return None
            path = artifact.pdf_path.resolve(strict=True)
            if not path.is_relative_to(root) or path.suffix.lower() != ".pdf":
                return None
            for candidate in (artifact.pdf_path, *artifact.pdf_path.parents):
                if candidate.is_symlink():
                    return None
                if candidate == root:
                    break
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_PDF_BYTES:
                return None
            with path.open("rb") as source:
                if source.read(5) != b"%PDF-":
                    return None
            return path
        except OSError:
            return None

    def _artifact(self, connection: sqlite3.Connection, job_id: str) -> ResumeArtifact | None:
        for row in connection.execute(
            "SELECT key,job_id,data FROM artifacts WHERE job_id=? "
            "ORDER BY json_extract(data,'$.created_at') DESC LIMIT 20",
            (job_id,),
        ):
            try:
                artifact = ResumeArtifact.model_validate_json(row["data"])
            except ValueError:
                continue
            if artifact.key != row["key"] or artifact.job_id != row["job_id"]:
                continue
            if self._artifact_path(artifact) is not None:
                return artifact
        return None

    def resume(self, job_id: str) -> bytes | None:
        if not JOB_ID.fullmatch(job_id):
            return None
        try:
            with self.connection() as connection:
                if not connection.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
                    return None
                artifact = self._artifact(connection, job_id)
            if artifact is None or (path := self._artifact_path(artifact)) is None:
                return None
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_PDF_BYTES:
                    return None
                pdf = source.read(MAX_PDF_BYTES + 1)
            return pdf if pdf.startswith(b"%PDF-") and len(pdf) <= MAX_PDF_BYTES else None
        except (OSError, sqlite3.Error, ValueError):
            return None
