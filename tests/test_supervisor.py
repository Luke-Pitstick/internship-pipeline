from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from internship_pipeline import cli, supervisor


def wait_for(path: Path, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            pytest.fail(f"Supervisor exited before workers were ready: {process.communicate()}")
        time.sleep(0.02)
    pytest.fail("Worker did not become ready")


@pytest.mark.parametrize("failed_code", [None, 0, 7])
def test_process_shutdown_and_unexpected_exit(tmp_path: Path, failed_code: int | None) -> None:
    """Exercise real subprocess signals and reaping, including clean unexpected exits."""
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import signal, sys, time\n"
        "from pathlib import Path\n"
        "directory, role = Path(sys.argv[1]), sys.argv[2]\n"
        "def stop(*_):\n"
        "    (directory / (role + '.stopped')).touch()\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        "(directory / (role + '.ready')).touch()\n"
        "while True:\n"
        "    if role == 'failing' and (directory / 'fail').exists():\n"
        "        sys.exit(int((directory / 'fail').read_text()))\n"
        "    time.sleep(0.02)\n"
    )
    commands = {
        role: [sys.executable, str(worker), str(tmp_path), role] for role in ("failing", "healthy")
    }
    runner = (
        "import json, sys\n"
        "from internship_pipeline.supervisor import supervise\n"
        "sys.exit(supervise(json.loads(sys.argv[1]), shutdown_seconds=1))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", runner, json.dumps(commands)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for role in commands:
            wait_for(tmp_path / f"{role}.ready", process)
        if failed_code is None:
            process.send_signal(signal.SIGTERM)
        else:
            (tmp_path / "fail").write_text(str(failed_code))
        _, stderr = process.communicate(timeout=5)
        assert process.returncode == (0 if failed_code is None else 1)
        assert (tmp_path / "healthy.stopped").exists()
        if failed_code is None:
            assert (tmp_path / "failing.stopped").exists()
        else:
            assert f"Worker failing exited unexpectedly: {failed_code}" in stderr
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=5)


def test_stubborn_worker_is_killed_and_reaped(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    worker = (
        "import os, signal, sys, time\n"
        "from pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    runner = (
        "import sys\n"
        "from internship_pipeline.supervisor import supervise\n"
        f"sys.exit(supervise({{'stubborn': {repr([sys.executable, '-c', worker, str(ready)])}}}, "
        "shutdown_seconds=0.2))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", runner],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_for(ready, process)
        pid = int(ready.read_text())
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=5)
        assert process.returncode == 0
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=5)


def test_shutdown_signals_worker_descendants(tmp_path: Path) -> None:
    descendant = tmp_path / "descendant.py"
    descendant.write_text(
        "import signal, sys, time\n"
        "from pathlib import Path\n"
        "directory = Path(sys.argv[1])\n"
        "def stop(*_):\n"
        "    (directory / 'descendant.stopped').touch()\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        "(directory / 'descendant.ready').touch()\n"
        "time.sleep(60)\n"
    )
    worker = (
        "import signal, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "directory = Path(sys.argv[1])\n"
        "child = subprocess.Popen([sys.executable, sys.argv[2], str(directory)])\n"
        "def stop(*_):\n"
        "    child.wait(timeout=2)\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        "while not (directory / 'descendant.ready').exists():\n"
        "    time.sleep(0.02)\n"
        "(directory / 'worker.ready').touch()\n"
        "time.sleep(60)\n"
    )
    commands = {"collector": [sys.executable, "-c", worker, str(tmp_path), str(descendant)]}
    runner = (
        "import json, sys\n"
        "from internship_pipeline.supervisor import supervise\n"
        "sys.exit(supervise(json.loads(sys.argv[1]), shutdown_seconds=3))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", runner, json.dumps(commands)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_for(tmp_path / "worker.ready", process)
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=5)
        assert process.returncode == 0
        assert (tmp_path / "descendant.stopped").exists()
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=5)


def test_all_workers_share_resolved_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def supervise(commands):
        captured.update(commands)
        return 7

    monkeypatch.setattr(supervisor, "supervise", supervise)
    config = tmp_path / "settings.yaml"
    assert supervisor.run_workers(config) == 7
    assert tuple(captured) == supervisor.ROLES
    for role, command in captured.items():
        assert command == [
            sys.executable,
            "-m",
            "internship_pipeline.cli",
            "--config",
            str(config.resolve()),
            "worker",
            role,
        ]


def test_serve_initializes_storage_before_spawning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from internship_pipeline.models import Settings

    settings = Settings(
        database_path=tmp_path / "state.sqlite3",
        recording_notifications_path=tmp_path / "notifications.jsonl",
    )
    monkeypatch.setattr(cli, "load_settings", lambda _: settings)

    def run_workers(_):
        import sqlite3

        with sqlite3.connect(settings.database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone() == (0,)
        return 3

    monkeypatch.setattr(supervisor, "run_workers", run_workers)
    assert cli.main(["serve"]) == 3


def test_resume_pause_keeps_collection_and_delivery_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}
    monkeypatch.setenv("RESUME_GENERATION_PAUSED", "1")
    monkeypatch.setattr(supervisor, "supervise", lambda commands: captured.update(commands) or 0)
    assert supervisor.run_workers(None) == 0
    assert set(captured) == {"collector", "matcher", "delivery", "discovery"}


def test_newly_ready_role_starts_without_restarting_existing_worker(tmp_path: Path) -> None:
    """A newly claimed/configured instance gains workers in its existing process tree."""
    runner = (
        "import sys\n"
        "from pathlib import Path\n"
        "from internship_pipeline.supervisor import supervise\n"
        "root = Path(sys.argv[1])\n"
        'worker = "import os,sys,time; from pathlib import Path; '
        'Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)"\n'
        "commands = {'web': [sys.executable, '-c', worker, str(root / 'web.ready')]}\n"
        "def configured():\n"
        "    result = dict(commands)\n"
        "    if (root / 'enable').exists():\n"
        "        result['collector'] = [sys.executable, '-c', worker, "
        "str(root / 'collector.ready')]\n"
        "    return result\n"
        "sys.exit(supervise(commands, shutdown_seconds=1, command_provider=configured))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", runner, str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_for(tmp_path / "web.ready", process)
        web_pid = (tmp_path / "web.ready").read_text()
        (tmp_path / "enable").touch()
        wait_for(tmp_path / "collector.ready", process)
        assert (tmp_path / "web.ready").read_text() == web_pid
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=5)
        assert process.returncode == 0
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=5)
