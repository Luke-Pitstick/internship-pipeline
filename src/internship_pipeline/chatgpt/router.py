"""Owner-only account controls plus state-bound OAuth and helper callbacks."""

from __future__ import annotations

import html
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from internship_pipeline.chatgpt.accounts import ChatGPTAccounts
from internship_pipeline.chatgpt.protocol import USAGE_URL, ChatGPTError


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Start(Input):
    expected_revision: int = Field(ge=0)
    account_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class Account(Input):
    account_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class Attempt(Input):
    attempt_id: str = Field(min_length=1, max_length=100)


class Pair(Input):
    port: int = Field(ge=1024, le=65535)


class Complete(Input):
    state: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1, max_length=100)
    tokens: dict[str, Any]
    denied: bool = False


def build_chatgpt_router(
    accounts: ChatGPTAccounts, owner: Callable[[Request], None], origin: str
) -> APIRouter:
    router = APIRouter()
    private = APIRouter(prefix="/api/chatgpt", dependencies=[Depends(owner)])
    parsed = urlsplit(origin)
    local = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    callback = f"http://127.0.0.1:{parsed.port or 80}/auth/callback" if local else None

    @private.get("")
    def status() -> dict[str, Any]:
        return {"accounts": accounts.accounts(), "local": local, "usage_url": USAGE_URL}

    @private.post("/start")
    def start(body: Start) -> dict[str, Any]:
        return accounts.begin(body.expected_revision, callback, body.account_id)

    @private.post("/status")
    def attempt(body: Attempt) -> dict[str, Any]:
        return {
            "status": accounts.attempt_status(body.attempt_id),
            "account_id": accounts.attempt_account(body.attempt_id),
        }

    @private.post("/cancel")
    def cancel(body: Attempt) -> dict[str, bool]:
        accounts.cancel(body.attempt_id)
        return {"cancelled": True}

    @private.post("/models")
    def models(body: Account) -> dict[str, Any]:
        return {"models": accounts.models(body.account_id)}

    @private.post("/welcome")
    def welcome(body: Account) -> dict[str, bool]:
        accounts.welcome(body.account_id)
        return {"acknowledged": True}

    @private.post("/disconnect")
    def disconnect(body: Account) -> dict[str, Any]:
        confirmed = accounts.disconnect(body.account_id)
        return {
            "revoked": confirmed,
            "message": "ChatGPT account disconnected."
            if confirmed
            else "Disconnected locally. Remote revocation was not confirmed; "
            "disconnect the app in ChatGPT settings to end remote access.",
        }

    @private.get("/helper")
    def helper() -> FileResponse:
        return FileResponse(
            Path(__file__).with_name("login_helper.py"),
            filename="pipeline-chatgpt-connect.py",
            media_type="text/x-python",
        )

    router.include_router(private)

    def pairing(request: Request) -> str:
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or not 30 <= len(header[7:]) <= 100:
            raise HTTPException(403, "A valid one-time pairing code is required.")
        return header[7:]

    @router.post("/api/chatgpt/pair")
    def pair(body: Pair, request: Request) -> dict[str, Any]:
        return accounts.claim_pairing(pairing(request), body.port)

    @router.post("/api/chatgpt/complete")
    def complete(body: Complete, request: Request) -> dict[str, bool]:
        accounts.complete(
            body.state,
            None,
            body.client_id,
            pairing=pairing(request),
            tokens=body.tokens,
            denied=body.denied,
        )
        return {"connected": True}

    @router.get("/auth/callback")
    def oauth_callback(request: Request) -> HTMLResponse:
        # Uvicorn logs scope on response send; omit code/state from access logs.
        query = request.query_params
        request.scope["query_string"] = b""
        message, code = (
            "ChatGPT is connected. Return to AI settings to choose and test a model.",
            200,
        )
        try:
            if (
                not local
                or len(str(query)) > 16384
                or any(
                    len(query.getlist(name)) > 1 for name in ("state", "code", "client_id", "error")
                )
            ):
                raise ChatGPTError("Invalid callback. Start again in AI settings.")
            accounts.complete(
                query.get("state", ""),
                query.get("code"),
                query.get("client_id"),
                denied="error" in query,
            )
        except ChatGPTError as exc:
            message, code = str(exc), 400
        return HTMLResponse(
            "<!doctype html><html lang='en'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>ChatGPT connection · Internship Pipeline</title><main>"
            "<h1>ChatGPT connection</h1><p>" + html.escape(message) + "</p>"
            "<a href='"
            + html.escape(origin, quote=True)
            + "'>Return to Internship Pipeline</a></main></html>",
            status_code=code,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            },
        )

    return router
