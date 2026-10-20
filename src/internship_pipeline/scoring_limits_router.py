"""Owner-authenticated scoring budget settings."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from internship_pipeline.scoring_limits import (
    SaveScoringLimits,
    ScoringLimitsConflict,
    ScoringSettings,
)
from internship_pipeline.storage import Store


def make_scoring_limits_router(store: Store, require_owner: Callable[..., Any]) -> APIRouter:
    settings = ScoringSettings(store)
    router = APIRouter(prefix="/api/scoring-limits", dependencies=[Depends(require_owner)])

    @router.get("")
    def read() -> dict[str, Any]:
        return settings.view()

    @router.post("")
    def save(body: SaveScoringLimits) -> dict[str, Any]:
        try:
            return settings.save(body)
        except ScoringLimitsConflict as exc:
            raise HTTPException(409, str(exc)) from None

    return router
