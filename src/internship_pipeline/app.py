"""Same-origin static application and owner-authenticated FastAPI boundary."""

from __future__ import annotations

import hmac
import json
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware

from internship_pipeline.config import load_settings
from internship_pipeline.dashboard_api import DashboardAPI, DashboardUnavailable
from internship_pipeline.identity import Identity, IdentityError, Throttled
from internship_pipeline.model_connection_router import build_model_connection_router
from internship_pipeline.model_connections import ModelConnectionStore
from internship_pipeline.models import Settings
from internship_pipeline.profile_settings import ProfileSettings, profile_settings_router
from internship_pipeline.storage import Store


def runtime_settings(root: Path, config: Path | None) -> Settings:
    settings = load_settings(config if config and config.is_file() else None)
    defaults = {
        "database_path": root / "state.sqlite3",
        "artifact_dir": root / "artifacts",
        "companies_path": root / "config/companies.yaml",
    }
    return settings.model_copy(
        update={
            key: value for key, value in defaults.items() if key not in settings.model_fields_set
        }
    )


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class Claim(Credentials):
    setup_token: str = Field(min_length=1, max_length=100)


class ApplicationState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["applied", "not_applied"]


def create_app(
    root: Path | None = None,
    *,
    origin: str | None = None,
    static_dir: Path | None = None,
    settings: Settings | None = None,
    supervisor_status: Path | None = None,
) -> FastAPI:
    root = root or Path(os.getenv("PIPELINE_DATA_DIR", "/var/data"))
    from internship_pipeline.operations import installation_lock

    with installation_lock(root):
        origin = (origin or os.environ.get("PIPELINE_ORIGIN") or "http://localhost:8080").rstrip(
            "/"
        )
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or (
                parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            )
        ):
            raise ValueError("PIPELINE_ORIGIN must be an HTTPS origin or a loopback HTTP origin")
        secure = parsed.scheme == "https"
        cookie = "__Host-pipeline_session" if secure else "pipeline_session"
        static_dir = static_dir or Path(os.getenv("PIPELINE_WEB_DIR", "/app/web/build"))
        config = Path(os.getenv("PIPELINE_CONFIG", str(root / "config/settings.yaml")))
        settings = settings or runtime_settings(root, config)
        identity = Identity(root / "identity.sqlite3")
        store = Store(settings.database_path)
        profiles = ProfileSettings(store)
        model_connections = ModelConnectionStore(
            settings.database_path, root / "model-credentials.key"
        )
        dashboard = DashboardAPI(settings)
        from internship_pipeline.assessments import Assessments, EvaluationError

        assessments = Assessments(store, model_connections)
        if supervisor_status is None and os.getenv("PIPELINE_SUPERVISOR_STATUS"):
            supervisor_status = Path(os.environ["PIPELINE_SUPERVISOR_STATUS"])

        @asynccontextmanager
        async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
            with installation_lock(root):
                if token := identity.setup_token():
                    print(f"Owner setup token: {token}", flush=True)
                yield

        app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
        app.state.identity = identity
        app.state.model_connections = model_connections
        app.state.assessments = assessments
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=[parsed.hostname])

        @app.middleware("http")
        async def boundary(request: Request, call_next: RequestResponseEndpoint) -> Response:
            if request.url.path.startswith("/api/"):
                if request.method not in {"GET", "HEAD", "OPTIONS"}:
                    if request.headers.get("origin") not in {None, origin}:
                        return JSONResponse({"detail": "Origin denied"}, status_code=403)
                    if request.headers.get("sec-fetch-site") == "cross-site":
                        return JSONResponse({"detail": "Origin denied"}, status_code=403)
                    body = bytearray()
                    async for chunk in request.stream():
                        body.extend(chunk)
                        limit = 16384
                        if request.url.path == "/api/resume-imports/upload":
                            limit = 5 * 1024 * 1024
                        elif (
                            request.url.path == "/api/profile-settings"
                            or request.url.path.startswith("/api/resume-imports/")
                        ):
                            limit = 262144
                        if len(body) > limit:
                            return JSONResponse({"detail": "Request too large"}, status_code=413)
                    request._body = bytes(body)
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers["Referrer-Policy"] = "no-referrer"
            if request.url.path.startswith("/api/"):
                response.headers["Cache-Control"] = "no-store"
            return response

        @app.exception_handler(RequestValidationError)
        async def invalid(_request: Request, _exc: RequestValidationError) -> JSONResponse:
            # FastAPI's default validation response echoes inputs, including passwords.
            fields = [
                {
                    "field": ".".join(str(part) for part in error["loc"] if part != "body"),
                    "message": "Check this value",
                }
                for error in _exc.errors()
            ]
            return JSONResponse(
                {"detail": "Invalid request fields", "fields": fields}, status_code=422
            )

        @app.exception_handler(DashboardUnavailable)
        async def unavailable(_request: Request, _exc: DashboardUnavailable) -> JSONResponse:
            return JSONResponse(
                {"detail": "Stored jobs are temporarily unavailable"}, status_code=503
            )

        def session(request: Request) -> dict[str, Any]:
            value = identity.session(request.cookies.get(cookie, ""))
            if not value:
                raise HTTPException(401, "Sign in to continue")
            if request.method not in {"GET", "HEAD"} and not hmac.compare_digest(
                value["csrf"].encode(), request.headers.get("x-csrf-token", "").encode()
            ):
                raise HTTPException(403, "Refresh the page and try again")
            return value

        def owner(request: Request) -> None:
            if not session(request)["authenticated"]:
                raise HTTPException(401, "Sign in to continue")

        def set_session(response: Response, value: tuple[str, str, int]) -> str:
            token, csrf, ttl = value
            response.set_cookie(
                cookie,
                token,
                max_age=ttl,
                httponly=True,
                secure=secure,
                samesite="strict",
                path="/",
            )
            return csrf

        @app.get("/healthz")
        def liveness() -> dict[str, bool]:
            return {"alive": True}

        @app.get("/readyz")
        def readiness() -> JSONResponse:
            ready = (static_dir / "index.html").is_file()
            try:
                claimed = identity.claimed()
                with dashboard.connection() as connection:
                    connection.execute("SELECT 1 FROM jobs LIMIT 1")
                if supervisor_status:
                    state = json.loads(supervisor_status.read_text())
                    ready = ready and state["healthy"] and time.time() - state["at"] < 10
            except Exception:
                ready, claimed = False, False
            return JSONResponse(
                {"ready": ready, "mode": "owner" if claimed else "setup"},
                status_code=200 if ready else 503,
            )

        @app.get("/api/session")
        def current_session(request: Request, response: Response) -> dict[str, Any]:
            value = identity.session(request.cookies.get(cookie, ""))
            if value:
                csrf = value["csrf"]
            else:
                try:
                    guest = identity.anonymous_session(
                        request.client.host if request.client else "unknown",
                        request.cookies.get(cookie, ""),
                    )
                except Throttled as exc:
                    raise HTTPException(429, str(exc), headers={"Retry-After": "300"}) from None
                csrf = set_session(response, guest)
            return {
                "authenticated": bool(value and value["authenticated"]),
                "claimed": identity.claimed(),
                "csrf": csrf,
            }

        def throttle(request: Request) -> None:
            try:
                identity.attempt(request.client.host if request.client else "unknown")
            except Throttled as exc:
                raise HTTPException(429, str(exc), headers={"Retry-After": "300"}) from None

        @app.post("/api/claim", dependencies=[Depends(session)])
        def claim(body: Claim, request: Request, response: Response) -> dict[str, Any]:
            throttle(request)
            try:
                value = identity.claim(body.setup_token, body.username, body.password)
            except IdentityError as exc:
                raise HTTPException(400, str(exc)) from None
            return {"authenticated": True, "claimed": True, "csrf": set_session(response, value)}

        @app.post("/api/login", dependencies=[Depends(session)])
        def login(body: Credentials, request: Request, response: Response) -> dict[str, Any]:
            throttle(request)
            value = identity.login(body.username, body.password, request.cookies.get(cookie, ""))
            if value is None:
                raise HTTPException(401, "Incorrect username or password")
            return {"authenticated": True, "claimed": True, "csrf": set_session(response, value)}

        private = APIRouter(prefix="/api", dependencies=[Depends(owner)])

        @private.post("/logout")
        def logout(request: Request, response: Response) -> dict[str, bool]:
            identity.logout(request.cookies.get(cookie, ""))
            response.delete_cookie(
                cookie, path="/", httponly=True, secure=secure, samesite="strict"
            )
            return {"authenticated": False}

        @private.get("/status")
        def status() -> dict[str, Any]:
            roles: list[str] = []
            if supervisor_status:
                try:
                    roles = json.loads(supervisor_status.read_text()).get("roles", [])
                except (OSError, ValueError):
                    pass
            snapshot = profiles.read()
            return {
                "worker_roles": roles,
                "configuration_present": snapshot.revision > 0,
                "settings_editable": True,
                "active_settings_revision": snapshot.revision,
                "note": "Saved profile and filters are read at the next worker task boundary. "
                "Jev evaluates queued jobs when the saved profile and tested connection are ready. "
                "Automatic resume generation is off.",
            }

        @private.get("/jobs")
        def jobs(
            page: int = 1,
            page_size: int = 25,
            search: str = "",
            view: str = "All",
            sort: str = "postedAt",
            direction: str = "desc",
            selected: str | None = None,
        ) -> dict[str, Any]:
            try:
                return dashboard.jobs(
                    page=page,
                    page_size=page_size,
                    search=search,
                    view=view,
                    sort=sort,
                    direction=direction,
                    selected=selected,
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None

        @private.get("/jobs/{job_id}")
        def job_detail(job_id: str) -> dict[str, Any]:
            result = dashboard.detail(job_id)
            if result is None:
                raise HTTPException(404, "Job not found")
            return result

        @private.post("/jobs/{job_id}/workspace")
        def workspace(job_id: str, body: dict[str, Any]) -> dict[str, Any]:
            try:
                result = dashboard.update_workspace(job_id, body)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            if result is None:
                raise HTTPException(404, "Job not found")
            return result

        @private.post("/jobs/{job_id}/evaluate", status_code=202)
        def evaluate(job_id: str) -> dict[str, str]:
            try:
                fingerprint = assessments.enqueue(job_id, retry=True)
            except KeyError:
                raise HTTPException(404, "Job not found") from None
            except EvaluationError as exc:
                raise HTTPException(409, str(exc)) from None
            from internship_pipeline.assessments import stored_view

            with store.connection() as db:
                view = stored_view(db, store.get_job(job_id))
            return {"state": view["state"], "identity": fingerprint}

        @private.post("/jobs/{job_id}/applied")
        def applied(job_id: str, body: ApplicationState) -> dict[str, Any]:
            result = dashboard.mark_applied(job_id, applied=body.status == "applied")
            if result is None:
                raise HTTPException(404, "Job not found")
            return result

        app.include_router(profile_settings_router(profiles, owner))
        app.include_router(build_model_connection_router(model_connections, owner))
        from internship_pipeline.profiles.imports import build_resume_import_router

        app.include_router(build_resume_import_router(store, owner))
        from internship_pipeline.resumes.master_router import make_master_resume_router

        app.include_router(make_master_resume_router(store, settings, owner))
        from internship_pipeline.resumes.tailored_router import make_tailored_resume_router

        app.include_router(make_tailored_resume_router(store, settings, owner))
        from internship_pipeline.search_runs import SearchRuns, search_router

        app.include_router(search_router(SearchRuns(store), owner))
        from internship_pipeline.email_integrations import EmailIntegrations
        from internship_pipeline.email_router import build_email_router
        from internship_pipeline.resumes.tailored import TailoredResumes

        drafts = TailoredResumes(store, settings)

        def email_pdf(job_id: str) -> bytes | None:
            value = drafts.latest(job_id)
            return drafts.pdf(value["key"]) if value.get("download_url") else None

        email = EmailIntegrations(store, model_connections, pdf_provider=email_pdf)
        app.state.email_integrations = email
        app.include_router(build_email_router(email, owner))
        from internship_pipeline.generation_policy_router import make_generation_policy_router

        app.include_router(make_generation_policy_router(store, settings, owner))
        from internship_pipeline.sheets_integration import SheetsIntegration
        from internship_pipeline.sheets_router import build_sheets_router

        sheets = SheetsIntegration(store, model_connections)
        app.state.sheets_integration = sheets
        app.include_router(build_sheets_router(sheets, owner))
        from internship_pipeline.onboarding import Onboarding
        from internship_pipeline.onboarding_router import onboarding_router

        app.include_router(
            onboarding_router(Onboarding(store, model_connections, email, sheets), owner)
        )
        from internship_pipeline.operations import Diagnostics, diagnostics_router

        app.include_router(diagnostics_router(Diagnostics(store, supervisor_status), owner))
        app.include_router(private)

        # Unknown API paths must never fall through to a static asset.
        @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
        def missing(path: str, request: Request) -> None:
            owner(request)
            raise HTTPException(404, "Not found")

        app.mount("/", StaticFiles(directory=static_dir, html=True, check_dir=False), name="web")
        return app
