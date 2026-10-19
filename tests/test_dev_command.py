"""Development commands stay tied to the checkout and its dedicated data volume."""

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def dev(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "deploy/dev"
    loader = importlib.machinery.SourceFileLoader("pipeline_dev", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    settings = tmp_path / "data/dev/config.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "docker": "/synthetic/docker",
                "host": "unix:///dev.sock",
                "volume": "synthetic-dev-data",
                "port": 18080,
            }
        )
    )
    return module


def test_reset_stops_current_app_and_restarts_only_after_success(dev, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["dev", "recover-owner"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    calls = []

    def run(argv, **options):
        calls.append(argv)
        assert options["env"]["PIPELINE_DEV_VOLUME"] == "synthetic-dev-data"
        assert str(dev.ROOT / "compose.dev.yaml") in argv
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    assert dev.main() == 0
    assert calls[0][-2:] == ["stop", "app"]
    assert (
        calls[1][-5:]
        == ["-m", "internship_pipeline.cli", "recover-owner", "--data-dir", "/var/data"]
    )
    assert "run" in calls[1] and "--rm" in calls[1]
    assert "up" in calls[2] and "--no-build" in calls[2] and "never" in calls[2]


def test_failed_reset_keeps_app_stopped(dev, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["dev", "recover-owner"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    calls = []

    def run(argv, **options):
        calls.append(argv)
        if "run" in argv:
            raise subprocess.CalledProcessError(2, argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    assert dev.main() == 2
    assert len(calls) == 2
    assert not any("up" in argv for argv in calls)


def test_noninteractive_reset_does_not_stop_app(dev, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["dev", "recover-owner"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    def unexpected_run(*args, **kwargs):
        pytest.fail("A noninteractive reset must not change the running app")

    monkeypatch.setattr(subprocess, "run", unexpected_run)
    with pytest.raises(SystemExit, match="2"):
        dev.main()
