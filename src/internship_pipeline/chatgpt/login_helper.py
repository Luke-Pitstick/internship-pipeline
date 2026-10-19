#!/usr/bin/env python3
"""Local OAuth helper for a remote Internship Pipeline. Uses only Python's standard library.

Download from your pipeline's AI settings, run with Python 3.10+, and paste the
one-time pairing code when prompted. Credentials are sent only to OpenAI and the
pipeline origin you explicitly select. No credentials are written to disk.
"""

from __future__ import annotations

import argparse
import getpass
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, cast

TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"


class HelperError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def origin_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or (parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"})
    ):
        raise HelperError("Use your pipeline's HTTPS origin, or HTTP on a loopback address.")
    return value.rstrip("/")


def post(url: str, body: dict[str, Any], pairing: str | None = None) -> dict[str, Any]:
    data = json.dumps(body).encode() if pairing else urllib.parse.urlencode(body).encode()
    headers = {
        "Content-Type": "application/json" if pairing else "application/x-www-form-urlencoded"
    }
    if pairing:
        headers["Authorization"] = "Bearer " + pairing
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            data = response.read(131073)
            if len(data) > 131072:
                raise HelperError("The connection response exceeded the size limit.")
            result = json.loads(data)
            if not isinstance(result, dict):
                raise ValueError
            return result
    except (urllib.error.URLError, ValueError, OSError):
        raise HelperError(
            "Connection failed. Check AI settings and start a new connection."
        ) from None


def callback_values(path: str, expected_state: str) -> dict[str, str] | None:
    parsed = urllib.parse.urlsplit(path)
    if parsed.path != "/auth/callback" or len(path) > 16384:
        return None
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True, max_num_fields=20)
    if any(len(values) != 1 for values in query.values()):
        return None
    state = query.get("state", [""])[0]
    if not state.isascii() or not hmac.compare_digest(state, expected_state):
        return None
    return {key: values[0] for key, values in query.items()}


class LocalServer(HTTPServer):
    def get_request(self) -> Any:
        connection, address = super().get_request()
        connection.settimeout(3)
        return connection, address


def connect(origin: str, pairing: str) -> None:
    received: dict[str, str] = {}
    expected_state = ""

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *args: Any) -> None:
            pass  # Authorization codes and state must never appear in access logs.

        def do_GET(self) -> None:
            try:
                values = callback_values(self.path, expected_state)
            except ValueError:
                values = None
            if self.headers.get("Host") != f"127.0.0.1:{cast(HTTPServer, self.server).server_port}":
                values = None
            self.send_response(200 if values else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
            )
            self.end_headers()
            self.wfile.write(
                b"<!doctype html><html lang='en'><title>Internship Pipeline</title>"
                b"<p>Return to the terminal to finish the ChatGPT connection.</p></html>"
            )
            if values:
                received.update(values)

    with LocalServer(("127.0.0.1", 0), Callback) as server:
        server.timeout = 1
        pending = post(origin + "/api/chatgpt/pair", {"port": server.server_port}, pairing)
        expected_state = pending["state"]
        authorize = urllib.parse.urlsplit(pending["authorize_url"])
        if (
            authorize.scheme != "https"
            or authorize.netloc != "auth.openai.com"
            or authorize.path != "/api/accounts/authorize"
            or pending["redirect_uri"] != f"http://127.0.0.1:{server.server_port}/auth/callback"
        ):
            raise HelperError("The pipeline returned an invalid sign-in destination.")
        print("Opening OpenAI sign-in. Approve ChatGPT plan usage for Internship Pipeline.")
        if not webbrowser.open(pending["authorize_url"]):
            raise HelperError(
                "The browser could not be opened. Start again with a desktop browser."
            )
        deadline = time.monotonic() + 540
        while not received and time.monotonic() < deadline:
            server.handle_request()
    if not received:
        raise HelperError("Connection timed out. Start a new connection in AI settings.")
    client_id = received.get("client_id", pending["client_id"])
    if "error" in received:
        post(
            origin + "/api/chatgpt/complete",
            {"state": expected_state, "client_id": client_id, "tokens": {}, "denied": True},
            pairing,
        )
        raise HelperError("ChatGPT sign-in was cancelled.")
    if (
        client_id == "dynamic_agent_client"
        or not received.get("code")
        or (pending["client_id"] != "dynamic_agent_client" and client_id != pending["client_id"])
    ):
        raise HelperError("ChatGPT registration was incomplete. Start again in AI settings.")
    tokens = post(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": received["code"],
            "code_verifier": pending["code_verifier"],
            "redirect_uri": pending["redirect_uri"],
            "resource": RESOURCE,
        },
    )
    post(
        origin + "/api/chatgpt/complete",
        {"state": expected_state, "client_id": client_id, "tokens": tokens},
        pairing,
    )
    print("ChatGPT connected. Return to AI settings to choose, save and test a model.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Connect a remote pipeline to your ChatGPT plan")
    parser.add_argument(
        "--origin",
        required=True,
        help="Your pipeline's origin, for example https://jobs.example.com",
    )
    args = parser.parse_args()
    try:
        origin = origin_url(args.origin)
        print("Connect ChatGPT to: " + origin)
        pairing = getpass.getpass("One-time pairing code from AI settings: ").strip()
        if not 30 <= len(pairing) <= 100 or not pairing.isascii():
            raise HelperError("Enter the one-time pairing code from AI settings.")
        connect(origin, pairing)
        return 0
    except (HelperError, KeyError, TypeError, OSError):
        print(
            "ChatGPT connection did not finish. "
            "Check the connection and start again in AI settings."
        )
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nConnection cancelled. You can start again in AI settings.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
