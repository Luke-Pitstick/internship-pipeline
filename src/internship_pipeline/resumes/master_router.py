"""Owner-only generation status and safe, private PDF delivery."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from internship_pipeline.models import Settings
from internship_pipeline.resumes.master import MasterConflict, MasterResumes
from internship_pipeline.resumes.validation import ResumeValidationError
from internship_pipeline.storage import Store


class GenerateMaster(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, strict=True)


def make_master_resume_router(
    store: Store, settings: Settings, require_owner: Callable[..., Any]
) -> APIRouter:
    service = MasterResumes(store, settings)
    router = APIRouter(prefix="/api/master-resume", dependencies=[Depends(require_owner)])

    @router.get("")
    def latest() -> dict[str, Any]:
        return service.latest()

    @router.post("", status_code=202)
    def generate(body: GenerateMaster) -> dict[str, Any]:
        try:
            return service.request(body.expected_revision)
        except MasterConflict as exc:
            raise HTTPException(409, str(exc)) from None
        except ResumeValidationError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.get("/{key}/pdf")
    def pdf(key: str, download: bool = False) -> Response:
        try:
            content = service.pdf(key)
        except (FileNotFoundError, OSError, ValueError):
            raise HTTPException(
                404, "This PDF is unavailable. Generate again or check artifact storage."
            ) from None
        return Response(
            content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": ("attachment" if download else "inline")
                + '; filename="master-resume.pdf"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "SAMEORIGIN",
            },
        )

    return router
