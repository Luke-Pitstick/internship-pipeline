"""Storage declarations are available without loading or modifying an installation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from internship_pipeline import cli
from internship_pipeline.storage_format import STORAGE_FORMAT

SOURCE = Path(__file__).resolve().parents[1] / "src/internship_pipeline/storage_format.py"


@pytest.mark.parametrize("entrypoint", ["module", "isolated-source"])
def test_declaration_needs_no_settings_or_data(tmp_path, entrypoint):
    root = tmp_path / "uncreated-installation"
    config = tmp_path / "invalid-settings.yaml"
    config.write_text("invalid: [yaml")
    env = {
        **os.environ,
        "PIPELINE_DATA_DIR": str(root),
        "PIPELINE_CONFIG": str(config),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(SOURCE.parents[1]),
    }
    args = (
        ["-m", "internship_pipeline.storage_format"]
        if entrypoint == "module"
        else ["-I", "-S", "-B", str(SOURCE)]
    )
    result = subprocess.run(
        [sys.executable, *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout) == {"storage_format": STORAGE_FORMAT}
    assert result.stderr == ""
    assert not root.exists()
    assert config.read_text() == "invalid: [yaml"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["invalid-settings.yaml"]


def test_cli_storage_format_bypasses_configuration_and_installation_lock(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "uncreated-installation"
    monkeypatch.setenv("PIPELINE_DATA_DIR", str(root))

    def unexpected(*args, **kwargs):
        pytest.fail("Storage inspection must not load settings or acquire a data lock")

    monkeypatch.setattr(cli, "load_settings", unexpected)
    monkeypatch.setattr("internship_pipeline.operations.installation_lock", unexpected)
    assert cli.main(["--config", str(tmp_path / "missing.yaml"), "storage-format"]) == 0
    assert json.loads(capsys.readouterr().out) == {"storage_format": STORAGE_FORMAT}
    assert not root.exists()
