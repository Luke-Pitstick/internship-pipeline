"""Keep all worker roles alive together and bound their shutdown time."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import FrameType

ROLES = (
    "collector",
    "matcher",
    "discovery",
    "search-runs",
    "master-resumes",
    "tailored-resumes",
    "email-delivery",
    "sheets-sync",
)


def _signal_group(process: subprocess.Popen[bytes], signum: int) -> None:
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        pass


def supervise(
    commands: Mapping[str, Sequence[str]],
    shutdown_seconds: float = 20,
    status_path: Path | None = None,
    command_provider: Callable[[], Mapping[str, Sequence[str]]] | None = None,
) -> int:
    """Stop every role if one exits; let the service host restart the full service."""
    stop = threading.Event()

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        stop.set()

    previous = {sig: signal.signal(sig, request_stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    processes: dict[str, subprocess.Popen[bytes]] = {}
    result = 0
    last_status_at = float("-inf")
    last_refresh_at = float("-inf")
    try:
        for role, command in commands.items():
            if stop.is_set():
                break
            try:
                processes[role] = subprocess.Popen(command, start_new_session=True)
            except OSError as exc:
                print(f"Worker {role} could not start: {type(exc).__name__}", file=sys.stderr)
                result = 1
                stop.set()
                break
        while not stop.is_set():
            # Starting newly ready roles does not interrupt work already in flight.
            # Workers re-read profile/settings between tasks; no container restart.
            if command_provider and time.monotonic() - last_refresh_at >= 2:
                last_refresh_at = time.monotonic()
                for role, command in command_provider().items():
                    if role not in processes:
                        try:
                            processes[role] = subprocess.Popen(command, start_new_session=True)
                        except OSError as exc:
                            print(
                                f"Worker {role} could not start: {type(exc).__name__}",
                                file=sys.stderr,
                            )
                            result = 1
                            stop.set()
                            break
            for role, process in processes.items():
                if (code := process.poll()) is not None:
                    print(f"Worker {role} exited unexpectedly: {code}", file=sys.stderr)
                    result = 1
                    stop.set()
                    break
            if status_path and time.monotonic() - last_status_at >= 2:
                temporary = status_path.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(
                        {
                            "healthy": not stop.is_set(),
                            "at": time.time(),
                            "roles": [role for role in processes if role != "web"],
                        }
                    )
                )
                temporary.replace(status_path)
                last_status_at = time.monotonic()
            stop.wait(0.2)
    finally:
        if status_path:
            status_path.unlink(missing_ok=True)
        # Signal whole sessions, including collector subprocesses, even if their leader exited.
        for process in processes.values():
            _signal_group(process, signal.SIGTERM)
        deadline = time.monotonic() + shutdown_seconds
        for process in processes.values():
            try:
                process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
        # A child may have exited while leaving descendants alive; clean up its whole group.
        for process in processes.values():
            _signal_group(process, signal.SIGKILL)
        for process in processes.values():
            process.wait()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return result


def run_workers(config: Path | None) -> int:
    base = [sys.executable, "-m", "internship_pipeline.cli"]
    if config is not None:
        base.extend(["--config", str(config.resolve())])
    return supervise({role: [*base, "worker", role] for role in ROLES})
