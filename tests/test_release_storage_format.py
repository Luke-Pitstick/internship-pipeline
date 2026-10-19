"""Publication's image-format gate uses an isolated image and refuses mismatches."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
sys.path.insert(0, str(DEPLOY))
spec = importlib.util.spec_from_file_location(
    "release_install_smoke", DEPLOY / "release-install-smoke.py"
)
assert spec and spec.loader
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


@pytest.mark.parametrize("engine", ["docker", "podman"])
def test_image_format_check_disables_network_and_never_mounts_installation(engine, monkeypatch):
    calls = []

    def command(*args):
        calls.append(args)
        return b'{"storage_format": 7}'

    monkeypatch.setattr(smoke, "command", command)
    smoke.verify_image_storage_format(engine, "sha256:" + "a" * 64, 7)
    assert calls == [
        (
            engine,
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--entrypoint",
            "python",
            "sha256:" + "a" * 64,
            "-B",
            "-m",
            "internship_pipeline.storage_format",
        )
    ]


@pytest.mark.parametrize(
    "declaration",
    [
        {"storage_format": 2},
        {"storage_format": True},
        {"storage_format": 1.0},
        {"storage_format": "1"},
        {},
        {"storage_format": 1, "extra": True},
        [1],
    ],
)
def test_release_gate_refuses_malformed_or_different_image_format(declaration, monkeypatch):
    monkeypatch.setattr(smoke, "command", lambda *args: json.dumps(declaration).encode())
    with pytest.raises(RuntimeError, match="storage format differs"):
        smoke.verify_image_storage_format("docker", "sha256:" + "a" * 64, 1)
