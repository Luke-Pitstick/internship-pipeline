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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline_runtime import (
    Failure,
    Manifest,
    Runtime,
    default_install_dir,
    host_lock,
    load_manifest,
    require_complete_restore,
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
    if args.command == "url":
        return manifest.url
    runtime = Runtime(manifest.runtime)
    runtime.check()
    if args.command == "start" and "-update-" in manifest.container_name:
        from pipeline_update import activate_container

        activate_container(runtime, manifest)
    container = runtime.require_owned(manifest)
    state = _state(container)
    if args.command == "open":
        url = runtime.browser_url(manifest)
        try:
            opened = webbrowser.open(url)
        except (OSError, webbrowser.Error):
            opened = False
        if not opened:
            return f"Browser could not open automatically. Open your workspace: {url}"
        return url
    if args.command in {"setup-token", "recover-owner"}:
        if state.get("Running") is True:
            raise Failure("Stop the application and all workers before offline recovery.")
        if not sys.stdin.isatty():
            raise Failure("Recovery requires a private interactive terminal.")
        image_id = container.get("Image")
        if not isinstance(image_id, str):
            raise Failure("Exact installed image identity is unavailable; preserve the volume.")
        runtime.maintenance(manifest, args.command, image_id)
        return {"recovery_completed": True, "volume_preserved": True, "running": False}
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
            runtime.run(
                "logs", "--tail", str(args.lines), manifest.container_name, include_stderr=True
            )
        )
    result: dict[str, Any] = {
        "runtime": manifest.runtime.name,
        "running": state.get("Running") is True,
        "ready": runtime.is_ready(container),
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
        print("Owner username: ", end="", file=sys.stderr, flush=True)
        username = input("")
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


def _detail(value: Any, field: str) -> str:
    if value is None:
        return "Unknown"
    if field in {"at", "last_attempt", "last_success", "oldest_update", "lease_until", "updated"}:
        try:
            return datetime.fromtimestamp(value, UTC).strftime("%Y-%m-%d %H:%M UTC")
        except (ValueError, OverflowError, OSError):
            return "Unknown"
    if field == "healthy":
        return "Healthy" if value else "Needs attention"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if field == "error":
        return "Check Settings > Diagnostics"
    return str(value).replace("_", " ")


def print_diagnostics(summary: dict[str, Any]) -> None:
    """Format only the bounded, sanitized diagnostics returned by diagnostic_summary."""
    workers = summary["workers"]
    print(f"\nWorkers: {_detail(workers['healthy'], 'healthy')}")
    if workers["roles"]:
        print("  " + ", ".join(workers["roles"]))
    sections = (
        ("Sources", "sources", ("healthy", "last_attempt", "last_success", "age_seconds", "error")),
        ("Queue", "queue", ("kind", "status", "count")),
        ("Active work", "activity", ("kind", "running", "oldest_update", "lease_until")),
        ("Failed work", "failed", ("id", "attempts", "updated", "retryable")),
        ("Models", "models", ("operation", "status", "count")),
    )
    labels = {
        "healthy": "Health",
        "last_attempt": "Last attempt",
        "last_success": "Last success",
        "age_seconds": "Age (seconds)",
        "error": "Issue",
        "kind": "Work",
        "status": "Status",
        "count": "Count",
        "running": "Running",
        "oldest_update": "Last update",
        "lease_until": "Lease until",
        "id": "Task",
        "attempts": "Attempts",
        "updated": "Updated",
        "retryable": "Can retry",
        "operation": "Operation",
    }
    for title, key, fields in sections:
        records = summary[key]
        print(f"\n{title}" + ("" if records else ": None"))
        for index, record in enumerate(records, 1):
            if len(records) > 1:
                print(f"  {index}.")
            for field in fields:
                if field == "error" and record[field] is None:
                    continue
                print(f"    {labels[field]}: {_detail(record[field], field)}")
    print_work_logs(summary["logs"])


def print_work_logs(records: list[dict[str, Any]]) -> None:
    print("\nWork events" + ("" if records else ": No recent failures."))
    for record in records:
        print(f"  {_detail(record['at'], 'at')}  Work failed.")
    if records:
        print("  Open Settings > Diagnostics for details and retry options.")


def print_result(command: str, result: dict[str, Any] | str) -> None:
    """Keep everyday commands readable, with JSON reserved for explicit --json use."""
    if isinstance(result, str):
        if command == "open" and result.startswith("http"):
            print(f"Opened your workspace.\n\n  {result}")
        else:
            print(result)
    elif command == "stop":
        print("Application stopped. Your data is saved.")
    elif command == "start":
        print(f"Application is running.\n\n  Workspace  {result['url']}")
    elif command == "update":
        if "message" in result:
            print(result["message"])
        elif result.get("updated"):
            state = "running" if result["running"] else "stopped"
            print(f"Updated to {result['version']}. Application is {state}.\n\n  {result['url']}")
            print("The original data volume and verified backup are retained.")
        else:
            print(f"Installed: {result['installed_version'] or result['installed_image']}")
            print(f"Latest release: {result['available_version']}")
            if not result["eligible"]:
                print(f"Update unavailable: {result['reason']}")
            elif result["update_available"]:
                print("Update available. Run internship-pipeline update to install it.")
            else:
                print("Already running the latest release.")
    elif command in {"setup-token", "recover-owner"}:
        message = "Setup token refreshed." if command == "setup-token" else "Owner recovered."
        print(f"{message} Your data is saved.\nRun internship-pipeline start when you're ready.")
    elif command == "logs" and "events" in result:
        events = result["events"]
        print("Worker events" if events else "No recent worker failures.")
        for event in events:
            detail = (
                f"exited unexpectedly (exit code {event['exit_code']})"
                if event["event"] == "worker_exited"
                else "could not start"
            )
            print(f"  {event['role']}: {detail}.")
        if result["omitted_lines"]:
            count = result["omitted_lines"]
            noun = "line" if count == 1 else "lines"
            print(f"\n  {count} other log {noun} hidden for privacy.")
        print("\nUse internship-pipeline logs --diagnostics for work events.")
    elif command == "logs":
        print_work_logs(result["diagnostics"])
    else:
        if not result["running"]:
            status = "Stopped"
        else:
            status = "Running" if result["ready"] else "Starting or needs attention"
        print(f"Internship Pipeline\n\n  Status     {status}")
        print(f"  Workspace  {result['url']}\n  Runtime    {result['runtime'].title()}")
        if isinstance(result["diagnostics"], dict):
            print_diagnostics(result["diagnostics"])
        else:
            if not result["running"]:
                print("\nRun internship-pipeline start to start the app.")
            print("\nUse internship-pipeline status --diagnostics for work activity.")


def parser(install_dir: Path | None = None) -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="internship-pipeline",
        description="Open and manage your local Internship Pipeline workspace.",
        epilog="Get started: internship-pipeline open\n"
        "Check activity: internship-pipeline status --diagnostics\n"
        "Get command help: internship-pipeline <command> --help",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    root.add_argument(
        "--install-dir",
        type=Path,
        default=install_dir if install_dir is not None else default_install_dir(),
        help="directory containing the installer's installation.json",
    )
    root.add_argument("--json", action="store_true", help="print JSON for scripts")
    commands = root.add_subparsers(dest="command", title="commands", metavar="COMMAND")
    update = commands.add_parser("update", help="install the latest compatible published release")
    update.add_argument(
        "--check", action="store_true", help="check release eligibility without updating"
    )
    start = commands.add_parser("start", help="start the app and wait until it's ready")
    start.add_argument(
        "--wait", type=float, default=60, help="readiness deadline in seconds (1–120)"
    )
    commands.add_parser("stop", help="stop the app and keep your data")
    status = commands.add_parser("status", help="check whether the app is running")
    status.add_argument("--diagnostics", action="store_true", help="prompt for an owner login")
    logs = commands.add_parser(
        "logs", help="show recent worker failures with private details hidden"
    )
    logs.add_argument("--lines", type=int, default=100, help="bounded runtime tail (1–200)")
    logs.add_argument(
        "--diagnostics", action="store_true", help="prompt for sanitized owner event logs"
    )
    commands.add_parser(
        "url", aliases=["show-url"], help="print the workspace URL, even while stopped"
    )
    commands.add_parser("open", help="open the saved URL in your default browser")
    commands.add_parser("setup-token", help="refresh the setup token before creating your account")
    commands.add_parser("recover-owner", help="reset your account using a private terminal")
    for subcommand in set(commands.choices.values()):
        subcommand.allow_abbrev = False
        subcommand.add_argument(
            "--json", action="store_true", default=argparse.SUPPRESS, help="print JSON for scripts"
        )
        subcommand.add_argument(
            "--install-dir",
            type=Path,
            default=argparse.SUPPRESS,
            help="use an existing installation in this directory",
        )
    return root


def main(argv: list[str] | None = None, *, install_dir: Path | None = None) -> int:
    command_parser = parser(install_dir)
    args = command_parser.parse_args(argv)
    if args.command is None:
        command_parser.print_help()
        return 0
    if args.command == "show-url":
        args.command = "url"
    if args.json and args.command in {"setup-token", "recover-owner"}:
        command_parser.error("--json is unavailable for interactive account recovery")
    if not 1 <= getattr(args, "wait", 60) <= 120:
        command_parser.error("--wait must be between 1 and 120 seconds")
    if not 1 <= getattr(args, "lines", 100) <= 200:
        command_parser.error("--lines must be between 1 and 200")
    try:
        args.install_dir = args.install_dir.expanduser().absolute()
        result: dict[str, Any] | str
        with host_lock(args.install_dir):
            from pipeline_release import latest
            from pipeline_update import apply, check, require_idle

            if args.command == "update":
                if args.check:
                    require_idle(args.install_dir)
                    manifest = load_manifest(args.install_dir / "installation.json")
                    result = check(args.install_dir, manifest, latest())
                else:
                    result = apply(args.install_dir)
            else:
                require_idle(args.install_dir)
                manifest = load_manifest(args.install_dir / "installation.json")
                result = managed_installation(args, manifest)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print_result(args.command, result)
        return 0
    except (Failure, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Command cancelled; installation data was preserved.", file=sys.stderr)
        return 1


def managed_installation(args: argparse.Namespace, manifest: Manifest) -> dict[str, Any] | str:
    require_complete_restore(args.install_dir, manifest)
    return manage(args, manifest)


if __name__ == "__main__":
    raise SystemExit(main())
