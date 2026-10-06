"""Authenticated dashboard access and explicit application tracking."""

from __future__ import annotations

import argparse
import hmac
import json
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from internship_pipeline.config import load_profile, load_settings
from internship_pipeline.matching import _deterministic_match
from internship_pipeline.models import Job, ResumeArtifact, Settings
from internship_pipeline.normalization import canonical_url

JOB_ID = re.compile(r"[a-zA-Z0-9_-]{1,128}")
APPLIED_ROUTE = re.compile(r"/api/jobs/([a-zA-Z0-9_-]{1,128})/applied")
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
    def __init__(self, settings: Settings | Path, token: str) -> None:
        self._configuration = settings
        self._token = token
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] | None = None
        self._cached_at = float("-inf")

    @property
    def settings(self) -> Settings:
        if isinstance(self._configuration, Settings):
            return self._configuration
        return load_settings(self._configuration)

    def authorized(self, authorization: str | None) -> bool:
        if not self._token or authorization is None:
            return False
        return hmac.compare_digest(
            authorization.encode("utf-8"), ("Bearer " + self._token).encode("utf-8")
        )

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
            if self._snapshot is not None and time.monotonic() - self._cached_at < 10:
                return self._snapshot
            try:
                snapshot = self._read_jobs()
            except Exception as exc:
                # Failed screening must not return raw inventory or a previously healthy view.
                self._snapshot = None
                raise DashboardUnavailable("Job screening is temporarily unavailable") from exc
            self._snapshot = snapshot
            self._cached_at = time.monotonic()
            return snapshot

    def _read_jobs(self) -> dict[str, Any]:
        profile = load_profile(self.settings.profile_path)
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
                    raise DashboardUnavailable("Screening timeout")
                job = Job.model_validate_json(row["data"])
                screened += 1
                if row["status"] != "open":
                    screened_applied_closed += 1
                match = _deterministic_match(job, profile)
                if not match.accepted or not match.fact_ids or match.role_family is None:
                    continue
                if job.id != row["id"] or not JOB_ID.fullmatch(job.id):
                    raise DashboardUnavailable("Invalid job identity")
                # Validate links without converting original apply endpoints into listing URLs.
                canonical_url(job.posting.apply_url)
                source_url = job.posting.source_url
                if source_url:
                    canonical_url(source_url)
                artifact = self._artifact(connection, job.id)
                description, description_truncated = plain_description(job.posting.description)
                reasons = [
                    reason[:500]
                    for reason in match.reasons
                    if not reason.startswith("Candidate fact ")
                ]
                reasons.append("Supported candidate experience overlaps with requested skills.")
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
                        "fit": match.fit,
                        "role_family": match.role_family.value,
                        "assessment": "preliminary",
                        "eligible": match.eligible,
                        "reasons": reasons,
                        "unknowns": [item[:500] for item in match.unknowns[:30]],
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
                "eligible_preliminary": len(jobs),
            },
            "jobs": jobs,
            "health": {
                "status": health,
                "sources": sources,
                "queues": queues,
                "oldest_work_age_seconds": None if oldest is None else max(0, int(now - oldest)),
                "resume_generation_paused": os.getenv("RESUME_GENERATION_PAUSED") == "1",
                "resume_model": self.settings.resume_model,
                "resume_source_connected": bool(
                    profile.master_resume_path
                    and profile.master_resume_path.suffix.lower() == ".tex"
                    and profile.master_resume_path.is_file()
                ),
                "note": "SQLite state does not verify inference or local relay delivery.",
            },
        }

    def mark_applied(self, job_id: str) -> dict[str, str] | None:
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
                    applied_at = job.applied_at or datetime.now(UTC)
                    if job.applied_at is None:
                        job = job.model_copy(update={"applied_at": applied_at})
                        connection.execute(
                            "UPDATE jobs SET data=? WHERE id=?", (job.model_dump_json(), job_id)
                        )
                self._snapshot = None
                return {"id": job_id, "status": "applied", "applied_at": applied_at.isoformat()}
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


def make_handler(api: DashboardAPI) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(10)

        def respond(
            self,
            code: int,
            body: bytes,
            mime: str = "application/json",
            *,
            filename: str | None = None,
        ) -> None:
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/healthz":
                self.respond(200, b'{"ok":true}')
                return
            if not api.authorized(self.headers.get("Authorization")):
                self.respond(401, b'{"error":"Unauthorized"}')
                return
            if self.path == "/api/jobs":
                try:
                    payload = json.dumps(api.jobs(), allow_nan=False).encode()
                except DashboardUnavailable:
                    self.respond(503, b'{"error":"Job screening is temporarily unavailable"}')
                    return
                self.respond(200, payload)
            elif self.path.startswith("/api/resumes/"):
                job_id = self.path.removeprefix("/api/resumes/")
                pdf = api.resume(job_id)
                if pdf is None:
                    self.respond(404, b'{"error":"Resume unavailable"}')
                else:
                    self.respond(200, pdf, "application/pdf", filename=f"resume-{job_id}.pdf")
            else:
                self.respond(404, b'{"error":"Not found"}')

        def do_POST(self) -> None:
            if not api.authorized(self.headers.get("Authorization")):
                self.respond(401, b'{"error":"Unauthorized"}')
                return
            route = APPLIED_ROUTE.fullmatch(self.path)
            if route is None:
                self.respond(404, b'{"error":"Not found"}')
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if (
                    not 0 < length <= 256
                    or content_type != "application/json"
                    or self.headers.get("Transfer-Encoding") is not None
                ):
                    raise ValueError("Invalid application confirmation")
                confirmation = json.loads(self.rfile.read(length))
                if confirmation != {"status": "applied"}:
                    raise ValueError("Invalid application confirmation")
            except (ValueError, OSError):
                self.respond(400, b'{"error":"Expected JSON confirmation: status applied"}')
                return
            try:
                result = api.mark_applied(route[1])
            except DashboardUnavailable:
                self.respond(503, b'{"error":"Application tracking is temporarily unavailable"}')
                return
            if result is None:
                self.respond(404, b'{"error":"Job not found"}')
            else:
                self.respond(200, json.dumps(result).encode())

        def log_message(self, _format: str, *args: Any) -> None:
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("/var/data/config/settings.yaml"))
    args = parser.parse_args()
    api = DashboardAPI(args.config, os.getenv("DASHBOARD_API_TOKEN", ""))
    server = ThreadingHTTPServer(("0.0.0.0", int(os.getenv("PORT", "10000"))), make_handler(api))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
