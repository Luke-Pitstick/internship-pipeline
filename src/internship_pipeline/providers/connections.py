"""Bounded synthetic capability probes for TypeSafe and OpenAI."""

from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

Kind = Literal["jev", "general"]
ENDPOINTS = {
    "jev": "https://api.typesafe.ai/v1/systemone",
    "general": "https://api.openai.com/v1/responses",
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
    model: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
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


def probe_body(kind: Kind, model: str, max_output_tokens: int) -> dict[str, Any]:
    if kind == "jev":
        return {
            "model": model,
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
    return {
        "model": model,
        "store": False,
        "max_output_tokens": max_output_tokens,
        "input": "Synthetic capability test. Return skill Python and evidence_id fact-1, "
        "using only this confirmed fact: fact-1: The synthetic candidate knows Python.",
        "text": {
            "format": {
                "type": "json_schema",
                "name": "candidate_fact",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"skill": {"type": "string"}, "evidence_id": {"type": "string"}},
                    "required": ["skill", "evidence_id"],
                },
            }
        },
    }


def metadata(body: dict[str, Any]) -> tuple[str | None, int | None, int | None]:
    model = body.get("model")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}", model):
        model = None
    usage = body.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    counts = [usage.get("input_tokens"), usage.get("output_tokens")]
    counts = [v if type(v) is int and 0 <= v <= 100_000_000 else None for v in counts]
    return model, counts[0], counts[1]


def validate_output(kind: Kind, body: dict[str, Any]) -> None:
    if any(value is None for value in metadata(body)):
        raise ValueError("Missing response metadata")
    if kind == "general":
        if body.get("status") != "completed":
            raise ValueError("Incomplete response")
        messages = [item for item in body["output"] if item["type"] == "message"]
        if len(messages) != 1 or messages[0].get("status") != "completed":
            raise ValueError("Missing message")
        content = messages[0]["content"]
        if len(content) != 1 or content[0]["type"] != "output_text":
            raise ValueError("Refusal or missing text")
        if json.loads(content[0]["text"]) != {"skill": "Python", "evidence_id": "fact-1"}:
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
                ENDPOINTS[kind],
                headers={"Authorization": f"Bearer {key}"},
                json=probe_body(kind, config.model, config.max_output_tokens),
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
            info = metadata(body)
            # Never retain a provider field that echoes our credential.
            if info[0] and key in info[0]:
                info = (None, info[1], info[2])
                return ProbeResult("output", *info)
            validate_output(kind, body)
            return ProbeResult("success", *info)
    except (TimeoutError, httpx.TimeoutException):
        return ProbeResult("timeout")
    except httpx.HTTPError:
        return ProbeResult("unavailable")
    except (ValueError, TypeError, KeyError, AttributeError, IndexError):
        return ProbeResult("output", *info)
