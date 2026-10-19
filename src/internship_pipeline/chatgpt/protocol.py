"""Bounded OpenAI OAuth operations and standards-based ID-token verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
import jwt

ISSUER = "https://auth.openai.com"
AUTHORIZE = ISSUER + "/api/accounts/authorize"
TOKEN = ISSUER + "/api/accounts/oauth/token"
DISCOVERY = ISSUER + "/.well-known/openid-configuration"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
USAGE_URL = "https://chatgpt.com/settings/usage"
MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}")


class ChatGPTError(ValueError):
    """Application-authored errors safe for display; never include upstream payloads."""


class ReauthorizationRequired(ChatGPTError):
    """An OAuth grant is no longer usable."""


def request_json(
    method: str,
    url: str,
    *,
    transport: httpx.BaseTransport | None = None,
    max_bytes: int = 262_144,
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        with (
            httpx.Client(
                timeout=15, follow_redirects=False, trust_env=False, transport=transport
            ) as client,
            client.stream(method, url, **kwargs) as response,
        ):
            data = bytearray()
            deadline = time.monotonic() + 20
            for chunk in response.iter_bytes():
                if time.monotonic() >= deadline:
                    raise ChatGPTError("ChatGPT request timed out. Try again.")
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise ChatGPTError(
                        "OpenAI returned an oversized response. Try connecting again."
                    )
            if response.status_code != 200:
                if response.status_code in (400, 401, 403):
                    raise ReauthorizationRequired(
                        "ChatGPT authorization expired or was denied. Connect again."
                    )
                if response.status_code == 429:
                    raise ChatGPTError(
                        "ChatGPT usage or rate limit reached. Manage usage in ChatGPT."
                    )
                raise ChatGPTError("OpenAI is unavailable. Try again later.")
            import json

            body = json.loads(data)
            if not isinstance(body, dict):
                raise ValueError
            return body
    except ChatGPTError:
        raise
    except (httpx.HTTPError, ValueError, TypeError):
        raise ChatGPTError("Could not complete the ChatGPT request. Try again.") from None


def discovery(*, transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    document = request_json("GET", DISCOVERY, transport=transport)
    if document.get("issuer") != ISSUER:
        raise ChatGPTError("OpenAI identity metadata could not be verified.")
    return document


def trusted_auth_url(value: Any) -> str:
    if not isinstance(value, str):
        raise ChatGPTError("OpenAI identity metadata could not be verified.")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "auth.openai.com"
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
    ):
        raise ChatGPTError("OpenAI identity metadata could not be verified.")
    return value


def validate_identity(
    tokens: dict[str, Any],
    client_id: str,
    nonce: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    try:
        token = tokens["id_token"]
        if not isinstance(token, str) or len(token) > 32_768:
            raise ValueError
        document = discovery(transport=transport)
        jwks = request_json("GET", trusted_auth_url(document["jwks_uri"]), transport=transport)
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise ValueError
        matches = [key for key in jwks["keys"] if key.get("kid") == header["kid"]]
        if len(matches) != 1:
            raise ValueError
        key = jwt.PyJWK.from_dict(matches[0], algorithm="RS256")
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
        )
        if not isinstance(claims["nonce"], str) or not hmac.compare_digest(claims["nonce"], nonce):
            raise ValueError
        if not isinstance(claims["sub"], str) or not 1 <= len(claims["sub"]) <= 512:
            raise ValueError
        if claims.get("azp", client_id) != client_id:
            raise ValueError
        if "at_hash" in claims:
            digest = hashlib.sha256(tokens["access_token"].encode()).digest()
            expected = base64.urlsafe_b64encode(digest[: len(digest) // 2]).rstrip(b"=").decode()
            if not hmac.compare_digest(claims["at_hash"], expected):
                raise ValueError
        return claims
    except ChatGPTError:
        raise
    except (jwt.PyJWTError, ValueError, KeyError, TypeError, AttributeError):
        raise ChatGPTError(
            "ChatGPT identity could not be verified. Start a new connection."
        ) from None


def token_bundle(
    tokens: dict[str, Any], *, previous: dict[str, Any] | None = None
) -> dict[str, Any]:
    previous = previous or {}
    result = {**previous, **tokens}
    for field in ("access_token", "refresh_token", "id_token"):
        value = result.get(field)
        if not isinstance(value, str) or not 1 <= len(value) <= 32_768 or not value.isascii():
            raise ChatGPTError("ChatGPT returned incomplete credentials. Connect again.")
        if any(ord(char) < 33 or ord(char) > 126 for char in value):
            raise ChatGPTError("ChatGPT returned invalid credentials. Connect again.")
    if result.get("token_type", "Bearer") != "Bearer":
        raise ChatGPTError("ChatGPT returned an unsupported token type.")
    scope = result.get("scope", "")
    if not isinstance(scope, str) or PLAN_SCOPE not in scope.split():
        raise ChatGPTError(
            "ChatGPT plan usage was not approved. Connect again and allow plan usage."
        )
    expiry = tokens.get("expires_in")
    if type(expiry) is not int or not 1 <= expiry <= 86400:
        raise ChatGPTError("ChatGPT returned invalid token expiry. Connect again.")
    return {
        field: result[field]
        for field in ("access_token", "refresh_token", "id_token", "scope", "expires_in")
    }
