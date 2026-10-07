"""Authenticated setup coordinator; connection/configuration endpoints stay separate."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from internship_pipeline.models import Record
from internship_pipeline.onboarding import Checkpoint, Onboarding, Start, Step


class Visit(Record):
    step: Step


def onboarding_router(setup: Onboarding, owner: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/onboarding", dependencies=[Depends(owner)])

    def invoke(action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return action()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @router.get("")
    def read() -> dict[str, Any]:
        return setup.view()

    @router.post("/checkpoint")
    def checkpoint(body: Checkpoint) -> dict[str, Any]:
        return invoke(lambda: setup.checkpoint(body))

    @router.post("/visit")
    def visit(body: Visit) -> dict[str, Any]:
        return setup.visit(body.step)

    @router.post("/start")
    def start(body: Start) -> dict[str, Any]:
        return invoke(lambda: setup.start(body))

    @router.post("/finish")
    def finish() -> dict[str, Any]:
        return invoke(setup.finish)

    return router
