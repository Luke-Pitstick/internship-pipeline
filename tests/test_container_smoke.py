"""Offline safety checks for the runner; these do not certify container acceptance."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "container_smoke", Path(__file__).resolve().parents[1] / "deploy/container-smoke.py"
)
assert spec and spec.loader
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_docker_failure_does_not_echo_private_arguments_or_output(monkeypatch) -> None:
    def fail(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "private-setup-token", "private-cookie")

    monkeypatch.setattr(smoke.subprocess, "run", fail)
    with pytest.raises(smoke.SmokeFailure, match=r"Docker exec failed \(exit 1\)") as exc:
        smoke.docker("exec", "private-container-argument")
    assert "private" not in str(exc.value)


def test_timeout_is_bounded_and_sanitized(monkeypatch) -> None:
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 15
        raise subprocess.TimeoutExpired(args, 15, output="private-setup-token")

    monkeypatch.setattr(smoke.subprocess, "run", timeout)
    with pytest.raises(smoke.SmokeFailure, match="Docker info exceeded 15s"):
        smoke.docker("info", timeout=15)


def test_built_relative_asset_url_resolves_at_same_origin(monkeypatch) -> None:
    browser = smoke.Browser("http://127.0.0.1:43210")
    urls = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b"built-asset"

    def open_request(request, timeout):
        urls.append(request.full_url)
        assert timeout == 3
        return Response()

    monkeypatch.setattr(browser.opener, "open", open_request)
    assert browser.request("./_app/immutable/entry/start.js") == (200, b"built-asset")
    assert urls == ["http://127.0.0.1:43210/_app/immutable/entry/start.js"]


def test_failed_readiness_cleans_only_uniquely_created_resources(monkeypatch) -> None:
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        if args[0] == "info":
            return '{"OperatingSystem":"synthetic","ServerVersion":"1",' \
                   '"OSType":"linux","Architecture":"arm64"}'
        return "synthetic-image"

    def failed_readiness(*args):
        raise smoke.SmokeFailure("synthetic readiness failure")

    class AvailablePort:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def bind(self, address):
            assert address == ("127.0.0.1", 0)

        def getsockname(self):
            return ("127.0.0.1", 43210)

    monkeypatch.setattr(smoke, "docker", docker)
    monkeypatch.setattr(smoke, "ready", failed_readiness)
    monkeypatch.setattr(smoke.socket, "socket", AvailablePort)
    with pytest.raises(smoke.SmokeFailure, match="synthetic readiness failure"):
        smoke.run(20)
    cleanup = calls[-3:]
    name = next(args[args.index("--name") + 1] for args in calls if args[0] == "run")
    assert name.startswith("pipeline-t03-")
    assert cleanup == [
        ("rm", "--force", name),
        ("volume", "rm", name + "-data"),
        ("image", "rm", name + ":smoke"),
    ]
    assert not any("prune" in args for args in calls)
