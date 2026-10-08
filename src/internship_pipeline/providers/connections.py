"""Bounded synthetic capability probes for TypeSafe and general LLM providers."""

from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from internship_pipeline.providers.structured import (
    GENERAL_ENDPOINTS,
    request_headers,
    response_text,
    structured_payload,
)

Kind = Literal["jev", "general"]
ENDPOINTS = {
    "jev": "https://api.typesafe.ai/v1/systemone",
    "general": GENERAL_ENDPOINTS["openai"],
}
ERRORS = {
    "authentication": "The provider rejected authentication. Replace the API key and test again.",
    "timeout": "The provider timed out. No automatic retry was made; usage may be unknown.",
    "rate_limit": "The provider rate limit or quota was reached. Check your provider account.",
    "unsupported": "The provider did not support the required response format or selected model.",
    "unavailable": "The provider could not be reached or returned a server error. Try again later.",
    "output": "The provider returned incomplete or unsupported output. Choose a supported model.",
}


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    endpoint: str = Field(max_length=200)
    api_key: SecretStr | None = Field(default=None, min_length=1, max_length=512)
    timeout_seconds: int = Field(default=30, ge=5, le=60)
    max_output_tokens: int = Field(default=1024, ge=256, le=4096)
    expected_revision: int = Field(ge=0)


@dataclass(frozen=True)
class ProbeResult:
    status: str
    effective_model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


def probe_body(kind: Kind, config: ConnectionInput) -> dict[str, Any]:
    if kind == "jev":
        return {
            "model": config.model,
            "state": {
                "candidate": {"skills": ["Python"]},
                "posting": {"p1": "Synthetic internship requires Python."},
            },
            "questions": {
                "requirement": {
                    "type": "choice",
                    "instructions": "Does the candidate meet p1?",
                    "criteria": {
                        "satisfied": "Meets requirement",
                        "violated": "Does not meet requirement",
                        "not_stated": "Not stated",
                        "ambiguous": "Unclear",
                    },
                },
                "evidence": {
                    "type": "choice",
                    "instructions": "Select supporting evidence ID.",
                    "criteria": {
                        "p1": "Synthetic internship requires Python.",
                        "none": "No evidence",
                    },
                },
                "fit": {
                    "type": "score",
                    "instructions": "Score the candidate skill overlap.",
                    "criteria": ["None", "Low", "Moderate", "Strong"],
                },
            },
        }
    return structured_payload(
        config.endpoint,
        config.model,
        config.max_output_tokens,
        "Return only the confirmed synthetic fact in the requested JSON schema.",
        "Synthetic capability test. Return skill Python and evidence_id fact-1, "
        "using only this confirmed fact: fact-1: The synthetic candidate knows Python.",
        "candidate_fact",
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {"skill": {"type": "string"}, "evidence_id": {"type": "string"}},
            "required": ["skill", "evidence_id"],
        },
    )


def metadata(
    body: dict[str, Any], endpoint: str = ENDPOINTS["general"]
) -> tuple[str | None, int | None, int | None]:
    if not isinstance(body, dict):
        raise ValueError("Unsupported response")
    model = body.get("model")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}", model):
        model = None
    usage = body.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    if endpoint == GENERAL_ENDPOINTS["openrouter"]:
        counts = [usage.get("prompt_tokens"), usage.get("completion_tokens")]
    else:
        counts = [usage.get("input_tokens"), usage.get("output_tokens")]
    if endpoint == GENERAL_ENDPOINTS["anthropic"]:
        cached = [
            usage.get("cache_creation_input_tokens", 0),
            usage.get("cache_read_input_tokens", 0),
        ]
        input_tokens = counts[0]
        if type(input_tokens) is int and all(
            type(v) is int and 0 <= v <= 100_000_000 for v in [input_tokens, *cached]
        ):
            counts[0] = input_tokens + sum(cached)
        else:
            counts[0] = None
    counts = [v if type(v) is int and 0 <= v <= 100_000_000 else None for v in counts]
    return model, counts[0], counts[1]


def validate_output(kind: Kind, body: dict[str, Any], endpoint: str) -> None:
    if any(value is None for value in metadata(body, endpoint)):
        raise ValueError("Missing response metadata")
    if kind == "general":
        if json.loads(response_text(endpoint, body)) != {
            "skill": "Python",
            "evidence_id": "fact-1",
        }:
            raise ValueError("Unsupported structured facts")
        return
    answers = body["answers"]
    expected = {
        "requirement": {"satisfied", "violated", "not_stated", "ambiguous"},
        "evidence": {"p1", "none"},
        "fit": {"0", "1", "2", "3"},
    }
    if set(answers) != set(expected):
        raise ValueError("Wrong answer IDs")
    for name, keys in expected.items():
        answer = answers[name]
        probabilities = answer["probabilities"]
        if set(probabilities) != keys:
            raise ValueError("Wrong probability keys")
        values = list(probabilities.values())
        if (
            any(
                type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
                for v in values
            )
            or abs(sum(values) - 1) > 0.021
        ):
            raise ValueError("Invalid probabilities")
        confidence = answer["confidence"]
        if type(confidence) not in (int, float) or not 0 <= confidence <= 1:
            raise ValueError("Invalid confidence")
        if name == "fit":
            score = answer["score"]
            if answer["type"] != "score" or type(score) not in (int, float) or not 0 <= score <= 3:
                raise ValueError("Invalid score")
            if abs(score - sum(int(k) * p for k, p in probabilities.items())) > 0.041:
                raise ValueError("Invalid score distribution")
        elif (
            answer["type"] != "choice"
            or answer["choice"] not in keys
            or probabilities[answer["choice"]] < max(values) - 0.002
        ):
            raise ValueError("Invalid choice")


async def probe(
    kind: Kind,
    config: ConnectionInput,
    key: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ProbeResult:
    """One request, no redirects/retries/environment proxies, bounded body and wall time."""
    info: tuple[str | None, int | None, int | None] = (None, None, None)
    try:
        supported = (
            config.endpoint in GENERAL_ENDPOINTS.values()
            if kind == "general"
            else (config.endpoint == ENDPOINTS["jev"])
        )
        if not supported:
            return ProbeResult("unsupported")
        async with (
            asyncio.timeout(config.timeout_seconds),
            httpx.AsyncClient(
                timeout=config.timeout_seconds,
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client,
            client.stream(
                "POST",
                config.endpoint,
                headers=request_headers(config.endpoint, key),
                json=probe_body(kind, config),
            ) as response,
        ):
            if response.status_code in (401, 403):
                return ProbeResult("authentication")
            if response.status_code == 429:
                return ProbeResult("rate_limit")
            if response.status_code >= 500:
                return ProbeResult("unavailable")
            if response.status_code != 200:
                return ProbeResult("unsupported")
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 65_536:
                    return ProbeResult("output")
            body = json.loads(data)
            info = metadata(body, config.endpoint)
            # Never retain a provider field that echoes our credential.
            if info[0] and key in info[0]:
                info = (None, info[1], info[2])
                return ProbeResult("output", *info)
            validate_output(kind, body, config.endpoint)
            return ProbeResult("success", *info)
    except (TimeoutError, httpx.TimeoutException):
        return ProbeResult("timeout")
    except httpx.HTTPError:
        return ProbeResult("unavailable")
    except (ValueError, TypeError, KeyError, AttributeError, IndexError):
        return ProbeResult("output", *info)
