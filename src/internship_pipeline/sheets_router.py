"""Owner-only Google connection, preview, queue, CSV and inward review API."""

from collections.abc import Callable, Generator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from starlette.types import Receive, Scope, Send

from internship_pipeline.model_connection_router import RevisionInput
from internship_pipeline.sheets_integration import SheetsInput, SheetsIntegration


class CsvResponse(StreamingResponse):
    """Close the CSV read snapshot after completion, transport error or disconnect."""

    def __init__(self, chunks: Generator[str, None, None], **kwargs: Any):
        super().__init__(chunks, **kwargs)
        self.chunks = chunks

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.chunks.close()


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accept: bool


def build_sheets_router(
    service: SheetsIntegration, require_owner: Callable[[Request], None]
) -> APIRouter:
    router = APIRouter(prefix="/api/sheets", dependencies=[Depends(require_owner)])

    def failure(exc: ValueError) -> HTTPException:
        return HTTPException(409, str(exc))

    @router.get("")
    def read() -> dict[str, Any]:
        return service.summary()

    @router.get("/export.csv")
    def export() -> CsvResponse:
        return CsvResponse(
            service.csv_chunks(),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="internship-opportunities.csv"',
                "Cache-Control": "private, no-store",
            },
        )

    @router.post("/save")
    def save(body: SheetsInput) -> dict[str, Any]:
        try:
            return service.save(body)
        except ValueError as exc:
            raise failure(exc) from None

    @router.post("/test")
    def test(body: RevisionInput) -> dict[str, Any]:
        try:
            return service.test(body.expected_revision)
        except ValueError as exc:
            raise failure(exc) from None

    @router.post("/preview")
    def preview(body: RevisionInput) -> dict[str, Any]:
        try:
            return service.preview(body.expected_revision)
        except ValueError as exc:
            raise failure(exc) from None

    @router.post("/remove")
    def remove(body: RevisionInput) -> dict[str, Any]:
        try:
            return service.remove(body.expected_revision)
        except ValueError as exc:
            raise failure(exc) from None

    @router.post("/{run}/sync")
    def sync(run: str) -> dict[str, Any]:
        try:
            service.request(run)
            return service.summary()
        except ValueError as exc:
            raise failure(exc) from None

    @router.post("/inward/{identity}/review")
    def review(identity: str, body: ReviewInput) -> dict[str, Any]:
        try:
            return service.resolve(identity, body.accept)
        except ValueError as exc:
            raise failure(exc) from None

    return router
