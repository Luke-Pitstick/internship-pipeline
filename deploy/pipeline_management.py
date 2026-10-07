"""Host lifecycle commands; uses only the Python standard library and saved runtime."""

from __future__ import annotations

import argparse
import getpass
import http.cookiejar
import json
import math
import re
import sys
import urllib.error
import urllib.request
import warnings
import webbrowser
from pathlib import Path
from typing import Any

from pipeline_runtime import (
    Failure,
    Manifest,
    Runtime,
    default_install_dir,
    load_manifest,
    wait_ready,
)

ROLES = {
    "web",
    "matcher",
    "collector",
    "discovery",
    "search-runs",
    "master-resumes",
    "tailored-resumes",
    "email-delivery",
    "sheets-sync",
}
KINDS = {
    "collect",
    "collection",
    "discover",
    "discovery",
    "evaluate",
    "assessment",
    "search_run",
    "master_resume",
    "tailored_resume",
    "email_delivery",
    "sheets_sync",
    "match",
    "collection_run",
}
MODEL_STATES = {
    "success",
    "pending",
    "timeout",
    "provider_unavailable",
    "rate_limited",
    "invalid_output",
    "interrupted_unknown_usage",
    "unauthorized",
    "needs_attention",
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class DiagnosticsClient:
    """One ephemeral owner session; never read or persist browser cookies."""

    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.cookies),
            NoRedirect(),
        )
        self.csrf: str | None = None

    def request(self, path: str, body: dict[str, str] | None = None) -> dict[str, Any]:
        headers = {"Origin": self.origin, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
            if self.csrf:
                headers["X-CSRF-Token"] = self.csrf
        request = urllib.request.Request(
            self.origin + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
        )
        try:
            with self.opener.open(request, timeout=5) as response:
                data = response.read(262_145)
            if len(data) > 262_144:
                raise Failure("Diagnostics response exceeded its safe size limit.")
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise Failure("Owner sign-in failed; verify your username and password.") from None
            if exc.code == 429:
                raise Failure(
                    "Sign-in is rate limited; wait five minutes before retrying."
                ) from None
            raise Failure("Diagnostics request failed; open Settings → Diagnostics.") from None
        except (OSError, ValueError):
            raise Failure(
                "Diagnostics unavailable; check status and the saved application URL."
            ) from None

    def fetch(self, username: str, password: str) -> dict[str, Any]:
        def csrf_token(value: dict[str, Any]) -> str:
            token = value.get("csrf")
            if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", token):
                raise Failure("Unexpected authentication response; open Settings → Diagnostics.")
            return token

        try:
            self.csrf = csrf_token(self.request("/api/session"))
            logged_in = self.request("/api/login", {"username": username, "password": password})
            if logged_in.get("authenticated") is not True:
                raise Failure("Owner sign-in failed; open the application to sign in.")
            self.csrf = csrf_token(logged_in)
            return self.request("/api/diagnostics")
        except (KeyError, TypeError):
            raise Failure(
                "Unexpected authentication response; open Settings → Diagnostics."
            ) from None
        finally:
            if self.csrf:
                try:
                    self.request("/api/logout", {})
                except Failure:
                    pass
            self.cookies.clear()
            self.csrf = None


def _number(value: Any) -> int | float | None:
    if type(value) is int:
        return value if abs(value) <= 2**53 else None
    return value if type(value) is float and math.isfinite(value) else None


def _enum(value: Any, allowed: set[str], default: str = "other") -> str:
    return value if isinstance(value, str) and value in allowed else default


def diagnostic_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Print a bounded allowlist, including neither arbitrary strings nor auth material."""

    def records(name: str) -> list[dict[str, Any]]:
        value = data.get(name, [])
        return [x for x in value[:50] if isinstance(x, dict)] if isinstance(value, list) else []

    workers = data.get("workers", {})
    if not isinstance(workers, dict):
        workers = {}
    roles = workers.get("roles", [])
    summary: dict[str, Any] = {
        "at": _number(data.get("at")),
        "workers": {
            "healthy": workers.get("healthy") is True,
            "roles": [r for r in roles if isinstance(r, str) and r in ROLES]
            if isinstance(roles, list)
            else [],
            "at": _number(workers.get("at")),
        },
        "sources": [
            {
                "last_attempt": _number(x.get("last_attempt")),
                "last_success": _number(x.get("last_success")),
                "age_seconds": _number(x.get("age_seconds")),
                "healthy": x.get("healthy") is True,
                "error": "source_request_failed" if x.get("error") else None,
            }
            for x in records("sources")
        ],
        "queue": [
            {
                "kind": _enum(x.get("kind"), KINDS),
                "status": _enum(
                    x.get("status"), {"pending", "running", "failed", "completed", "done"}
                ),
                "count": _number(x.get("count")),
            }
            for x in records("queue")
        ],
        "activity": [
            {
                "kind": _enum(x.get("kind"), KINDS),
                "running": _number(x.get("running")),
                "oldest_update": _number(x.get("oldest_update")),
                "lease_until": _number(x.get("lease_until")),
            }
            for x in records("activity")
        ],
        "failed": [
            {
                "id": _number(x.get("id")),
                "attempts": _number(x.get("attempts")),
                "updated": _number(x.get("updated")),
                "error": "work_failed_check_settings",
                "retryable": x.get("retryable") is True,
            }
            for x in records("failed")
        ],
        "models": [
            {
                "operation": _enum(
                    x.get("operation"),
                    {"assessment_attempts", "model_attempts", "tailored_attempts"},
                ),
                "status": _enum(x.get("status"), MODEL_STATES, "needs_attention"),
                "count": _number(x.get("count")),
            }
            for x in records("models")
        ],
        "logs": [
            {
                "at": _number(x.get("at")),
                "event": "work_failed",
                "message": "work_failed_check_settings",
            }
            for x in records("logs")
            if x.get("event") == "work_failed"
        ],
    }
    return summary


def runtime_log_summary(raw: str) -> dict[str, Any]:
    events = []
    lines = raw.splitlines()
    for line in lines[-200:]:
        match = re.fullmatch(r"Worker ([a-z-]+) exited unexpectedly: (-?\d{1,3})", line)
        if match and match[1] in ROLES:
            events.append({"event": "worker_exited", "role": match[1], "exit_code": int(match[2])})
        match = re.fullmatch(r"Worker ([a-z-]+) could not start: ([A-Za-z]+)", line)
        if match and match[1] in ROLES:
            events.append({"event": "worker_start_failed", "role": match[1]})
    return {"events": events, "omitted_lines": len(lines) - len(events)}


def _state(container: dict[str, Any]) -> dict[str, Any]:
    state = container.get("State", {})
    if not isinstance(state, dict):
        raise Failure("Runtime returned invalid container state; preserve the installation.")
    return state


def manage(args: argparse.Namespace, manifest: Manifest) -> dict[str, Any] | str:
    if args.command in {"url", "open"}:
        if args.command == "open":
            if not webbrowser.open(manifest.url):
                raise Failure("Browser could not open; use the URL shown by the url command.")
        return manifest.url
    runtime = Runtime(manifest.runtime)
    runtime.check()
    container = runtime.require_owned(manifest)
    state = _state(container)
    if args.command == "start":
        if state.get("Running") is not True:
            runtime.run("start", manifest.container_name)
        wait_ready(runtime, manifest, timeout=args.wait)
        return {"running": True, "ready": True, "url": manifest.url}
    if args.command == "stop":
        if state.get("Running") is True:
            runtime.run("stop", "--time", "30", manifest.container_name, timeout=40)
        stopped = runtime.require_owned(manifest)
        if _state(stopped).get("Running") is True:
            raise Failure("Container did not stop; data was preserved. Inspect runtime status.")
        return {"running": False, "volume_preserved": True}
    if args.command == "logs" and not args.diagnostics:
        return runtime_log_summary(
            runtime.run("logs", "--tail", str(args.lines), manifest.container_name)
        )
    health = state.get("Health", {})
    result: dict[str, Any] = {
        "runtime": manifest.runtime.name,
        "running": state.get("Running") is True,
        "ready": isinstance(health, dict)
        and health.get("Status") == "healthy"
        and state.get("Running") is True,
        "url": manifest.url,
        "diagnostics": "Sign in with --diagnostics for work activity and sanitized errors.",
    }
    if args.diagnostics:
        if not result["running"]:
            raise Failure("Start the saved installation before requesting owner diagnostics.")
        if not sys.stdin.isatty():
            raise Failure(
                "Owner diagnostics require an interactive terminal; open Settings → Diagnostics."
            )
        username = input("Owner username: ")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                password = getpass.getpass("Owner password: ")
        except getpass.GetPassWarning:
            raise Failure(
                "Secure password prompt unavailable; open Settings → Diagnostics."
            ) from None
        summary = diagnostic_summary(DiagnosticsClient(manifest.origin).fetch(username, password))
        result["diagnostics"] = summary["logs"] if args.command == "logs" else summary
    return result


def parser(install_dir: Path | None = None) -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Manage an existing installation; never creates or replaces its data.",
        epilog="Use status --diagnostics for an interactive owner sign-in. "
        "Backup, restore and explicit image updates: docs/t20-management.md. "
        "The host command and the image's maintenance CLI have different commands.",
    )
    root.add_argument(
        "--install-dir",
        type=Path,
        default=install_dir if install_dir is not None else default_install_dir(),
        help="directory containing the installer's installation.json",
    )
    commands = root.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="start the saved container and await image readiness")
    start.add_argument(
        "--wait", type=float, default=60, help="readiness deadline in seconds (1–120)"
    )
    commands.add_parser(
        "stop", help="stop the saved container while retaining its persistent volume"
    )
    status = commands.add_parser(
        "status", help="show lifecycle readiness; work data requires sign-in"
    )
    status.add_argument("--diagnostics", action="store_true", help="prompt for an owner login")
    logs = commands.add_parser(
        "logs", help="show recognized lifecycle events; raw lines are omitted"
    )
    logs.add_argument("--lines", type=int, default=100, help="bounded runtime tail (1–200)")
    logs.add_argument(
        "--diagnostics", action="store_true", help="prompt for sanitized owner event logs"
    )
    commands.add_parser(
        "url", aliases=["show-url"], help="print the saved URL, even if runtime is stopped"
    )
    commands.add_parser("open", help="open the saved URL in your default browser")
    return root


def main(argv: list[str] | None = None, *, install_dir: Path | None = None) -> int:
    command_parser = parser(install_dir)
    args = command_parser.parse_args(argv)
    if args.command == "show-url":
        args.command = "url"
    if not 1 <= getattr(args, "wait", 60) <= 120:
        command_parser.error("--wait must be between 1 and 120 seconds")
    if not 1 <= getattr(args, "lines", 100) <= 200:
        command_parser.error("--lines must be between 1 and 200")
    try:
        manifest = load_manifest(args.install_dir / "installation.json")
        result = manage(args, manifest)
        print(result if isinstance(result, str) else json.dumps(result, indent=2))
        return 0
    except Failure as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Command cancelled; installation data was preserved.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
