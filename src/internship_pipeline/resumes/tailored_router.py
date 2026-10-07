"""Authenticated manual job draft generation and explicit review."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from internship_pipeline.models import Settings
from internship_pipeline.resumes.master import MasterConflict
from internship_pipeline.resumes.tailored import TailoredResumes
from internship_pipeline.resumes.validation import ResumeValidationError
from internship_pipeline.storage import Store


class GenerateTailored(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_profile_revision: int = Field(ge=0, strict=True)
    expected_model_revision: int = Field(ge=0, strict=True)


def make_tailored_resume_router(
    store: Store, settings: Settings, require_owner: Callable[..., Any]
) -> APIRouter:
    service = TailoredResumes(store, settings)
    router = APIRouter(prefix="/api", dependencies=[Depends(require_owner)])

    @router.get("/jobs/{job_id}/resume")
    def latest(job_id: str) -> dict[str, Any]:
        try:
            return service.latest(job_id)
        except KeyError:
            raise HTTPException(404, "Job unavailable") from None

    @router.post("/jobs/{job_id}/resume", status_code=202)
    def request(job_id: str, body: GenerateTailored) -> dict[str, Any]:
        try:
            return service.request(
                job_id, body.expected_profile_revision, body.expected_model_revision
            )
        except KeyError:
            raise HTTPException(404, "Job unavailable") from None
        except MasterConflict as exc:
            raise HTTPException(409, str(exc)) from None
        except (ResumeValidationError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from None

    @router.post("/tailored-resume/{key}/review")
    def review(key: str) -> dict[str, Any]:
        try:
            return service.review(key)
        except FileNotFoundError:
            raise HTTPException(404, "Draft unavailable") from None
        except MasterConflict as exc:
            raise HTTPException(409, str(exc)) from None

    @router.get("/tailored-resume/{key}/pdf")
    def pdf(key: str, download: bool = False) -> Response:
        try:
            content = service.pdf(key)
        except (FileNotFoundError, ValueError, OSError):
            raise HTTPException(404, "PDF unavailable or stale. Generate again.") from None
        return Response(
            content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": ("attachment" if download else "inline")
                + "; filename=tailored-resume.pdf",
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "SAMEORIGIN",
            },
        )

    return router
