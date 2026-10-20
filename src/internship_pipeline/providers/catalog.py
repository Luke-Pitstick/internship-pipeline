"""Read current model catalogs from fixed official URLs without running inference."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

CatalogEndpoint = Literal[
    "https://api.openai.com/v1/responses",
    "https://api.anthropic.com/v1/messages",
    "https://openrouter.ai/api/v1/chat/completions",
]
CATALOG_URLS = {
    "https://api.openai.com/v1/responses": "https://api.openai.com/v1/models",
    "https://api.anthropic.com/v1/messages": "https://api.anthropic.com/v1/models",
    "https://openrouter.ai/api/v1/chat/completions": "https://openrouter.ai/api/v1/models",
}
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}")


class CatalogError(ValueError):
    """Safe catalog error that never includes upstream payloads or credentials."""


class CatalogInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: CatalogEndpoint
    expected_revision: int = Field(ge=0)
    api_key: SecretStr | None = Field(default=None, min_length=1, max_length=512)

    @field_validator("api_key")
    @classmethod
    def printable_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and any(not 33 <= ord(c) <= 126 for c in value.get_secret_value()):
            raise ValueError("API keys must contain printable ASCII without whitespace.")
        return value


async def list_models(
    endpoint: CatalogEndpoint,
    key: str | None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    url = CATALOG_URLS[endpoint]
    anthropic = "api.anthropic.com" in url
    public = "openrouter.ai" in url
    if not public and not key:
        raise CatalogError("Enter an API key to load available models.")
    headers = {} if public else {"Authorization": f"Bearer {key}"}
    if anthropic:
        headers = {"x-api-key": key or "", "anthropic-version": "2023-06-01"}
    params: dict[str, str | int] = {"limit": 1000} if anthropic else {}
    models: dict[str, dict[str, Any]] = {}
    cursors: set[str] = set()
    size = 0
    deadline = time.monotonic() + 30
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=False, trust_env=False, transport=transport
        ) as client:
            for _ in range(20):
                async with client.stream("GET", url, headers=headers, params=params) as response:
                    if response.status_code in (401, 403):
                        raise CatalogError(
                            "Model access was denied. Check this provider's API key."
                        )
                    if response.status_code == 429:
                        raise CatalogError("Model-list rate limit reached. Try again later.")
                    if response.status_code != 200:
                        raise CatalogError("The provider's model list is unavailable. Try again.")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 16 * 1024 * 1024 or time.monotonic() >= deadline:
                            raise CatalogError(
                                "The provider's model list exceeded its request limit."
                            )
                        data.extend(chunk)
                body = json.loads(data)
                if not isinstance(body, dict) or not isinstance(body.get("data"), list):
                    raise ValueError
                for item in body["data"]:
                    if not isinstance(item, dict):
                        raise ValueError
                    slug = item.get("id")
                    name = (
                        slug
                        if not public and not anthropic
                        else item.get("display_name" if anthropic else "name", slug)
                    )
                    if (
                        isinstance(slug, str)
                        and MODEL_ID.fullmatch(slug)
                        and isinstance(name, str)
                        and 1 <= len(name) <= 200
                        and not any(ord(c) < 32 for c in name)
                        and (not key or (key not in name and key not in slug))
                    ):
                        models[slug] = {"id": slug, "name": name}
                        if public:
                            architecture = item.get("architecture")
                            modalities = (
                                architecture.get("input_modalities", [])
                                if isinstance(architecture, dict)
                                else []
                            )
                            models[slug]["pdf_input"] = (
                                isinstance(modalities, list) and "file" in modalities
                            )
                if not anthropic or not body.get("has_more"):
                    return list(models.values())
                cursor = body.get("last_id")
                if (
                    not isinstance(cursor, str)
                    or not MODEL_ID.fullmatch(cursor)
                    or cursor in cursors
                ):
                    raise ValueError
                cursors.add(cursor)
                params["after_id"] = cursor
            raise CatalogError("The provider's model list exceeded its page limit.")
    except CatalogError:
        raise
    except httpx.TimeoutException:
        raise CatalogError("Loading models timed out. Try again.") from None
    except (httpx.HTTPError, ValueError, TypeError):
        raise CatalogError("Could not read the provider's model list. Try again.") from None
