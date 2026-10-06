"""Authenticated configuration API; credentials are never read back."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from internship_pipeline.model_connections import ConnectionError, ModelConnectionStore
from internship_pipeline.providers.connections import ERRORS, ConnectionInput, Kind, probe


class RevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)


def build_model_connection_router(
    store: ModelConnectionStore,
    require_owner: Callable[[Request], None],
) -> APIRouter:
    router = APIRouter(prefix="/api/model-connections", dependencies=[Depends(require_owner)])

    @router.get("")
    def read() -> dict[str, Any]:
        return store.summary()

    @router.post("/{kind}/save")
    def save(kind: Kind, body: ConnectionInput) -> dict[str, Any]:
        try:
            return store.save(kind, body)
        except ConnectionError as exc:
            raise HTTPException(409, str(exc)) from None

    @router.post("/{kind}/remove")
    def remove(kind: Kind, body: RevisionInput) -> dict[str, Any]:
        try:
            return store.remove(kind, body.expected_revision)
        except ConnectionError as exc:
            raise HTTPException(409, str(exc)) from None

    @router.post("/{kind}/test")
    async def test(kind: Kind, body: RevisionInput) -> dict[str, Any]:
        try:
            attempt, config, key = store.reserve_test(kind, body.expected_revision)
        except ConnectionError as exc:
            raise HTTPException(409, str(exc)) from None
        result = await probe(kind, config, key)
        store.complete_test(attempt, result)
        return {
            "connection": store.summary()[kind],
            "status": result.status,
            "message": "Synthetic capability test passed."
            if result.status == "success"
            else ERRORS[result.status],
        }

    return router
