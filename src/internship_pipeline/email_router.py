"""Owner-only email setup; explicit test and ambiguous-delivery retry actions."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from internship_pipeline.email_integrations import EmailInput, EmailIntegrations
from internship_pipeline.model_connection_router import RevisionInput


def build_email_router(
    service: EmailIntegrations, require_owner: Callable[[Request], None]
) -> APIRouter:
    router = APIRouter(prefix="/api/email", dependencies=[Depends(require_owner)])

    @router.get("")
    def read() -> dict[str, Any]:
        return service.summary()

    @router.post("/save")
    def save(body: EmailInput) -> dict[str, Any]:
        try:
            return service.save(body)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @router.post("/test")
    def test(body: RevisionInput) -> dict[str, Any]:
        try:
            return {
                "delivery_id": service.test(body.expected_revision),
                "message": "Test queued. Watch delivery status below.",
            }
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @router.post("/{delivery}/retry")
    def retry(delivery: str) -> dict[str, Any]:
        try:
            service.retry(delivery)
            return service.summary()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    return router
