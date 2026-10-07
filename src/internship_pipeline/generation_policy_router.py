"""Owner-authenticated draft automation settings and read-only previews."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from internship_pipeline.generation_policy import (
    GenerationPolicies,
    GenerationPolicy,
    SaveGenerationPolicy,
)
from internship_pipeline.models import Settings
from internship_pipeline.resumes.master import MasterConflict
from internship_pipeline.resumes.tailored import TailoredResumes
from internship_pipeline.storage import Store


def make_generation_policy_router(
    store: Store, settings: Settings, require_owner: Callable[..., Any]
) -> APIRouter:
    policies = GenerationPolicies(TailoredResumes(store, settings))
    router = APIRouter(prefix="/api/generation-policy", dependencies=[Depends(require_owner)])

    @router.get("")
    def view() -> dict[str, Any]:
        return policies.view()

    @router.post("/preview")
    def preview(body: GenerationPolicy) -> dict[str, Any]:
        return policies.view(body)

    @router.post("")
    def save(body: SaveGenerationPolicy) -> dict[str, Any]:
        try:
            return policies.save(body)
        except MasterConflict as exc:
            raise HTTPException(409, str(exc)) from None

    return router
