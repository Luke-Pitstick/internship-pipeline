"""Bounded JSON/SSE decoding shared by capability probes and résumé generation."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from httpx_sse import EventSource, SSEError


class ProviderFailure(ValueError):
    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


class BoundedStream(httpx.AsyncByteStream):
    def __init__(self, response: httpx.Response, limit: int):
        self.response, self.limit = response, limit

    async def __aiter__(self) -> AsyncIterator[bytes]:
        count = 0
        async for chunk in self.response.aiter_bytes():
            count += len(chunk)
            if count > self.limit:
                raise ProviderFailure("output")
            yield chunk

    async def aclose(self) -> None:
        await self.response.aclose()


async def read_body(response: httpx.Response, *, chatgpt: bool, limit: int) -> dict[str, Any]:
    if not chatgpt:
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > limit:
                raise ProviderFailure("output")
        decoded = json.loads(data)
        if not isinstance(decoded, dict):
            raise ProviderFailure("output")
        return decoded
    # Count before SSE line decoding; even a stream without newlines stays bounded.
    bounded = httpx.Response(
        200,
        headers={"Content-Type": response.headers.get("content-type", "")},
        stream=BoundedStream(response, limit),
    )
    try:
        async for event in EventSource(bounded).aiter_sse():
            if not event.data:
                continue
            body = json.loads(event.data)
            if not isinstance(body, dict):
                raise ProviderFailure("output")
            event_type = body.get("type", event.event)
            if event_type == "response.completed":
                result = body["response"]
                if not isinstance(result, dict):
                    raise ProviderFailure("output")
                if result.get("status") != "completed":
                    raise ProviderFailure("output")
                return result
            if event_type in {"response.failed", "error"}:
                error = body.get("response", body).get("error", body)
                code = error.get("code")
                status = {
                    "subscription_sharing_usage_limit_exceeded": "subscription_limit",
                    "subscription_sharing_usage_unavailable": "subscription_unavailable",
                }.get(code, "output")
                raise ProviderFailure(status)
            if event_type == "response.incomplete":
                raise ProviderFailure("output")
    except SSEError:
        raise ProviderFailure("output") from None
    raise ProviderFailure("output")
