"""Native synthetic fixture validation; passing does not prove any container ran."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import select
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from internship_pipeline.app import runtime_settings
from internship_pipeline.identity import Identity
from internship_pipeline.operations import backup_installation, restore_installation

FIXTURE = Path(__file__).resolve().parents[1] / "deploy/container-recovery-fixture.py"
spec = importlib.util.spec_from_file_location("container_recovery_fixture", FIXTURE)
assert spec and spec.loader
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


@pytest.mark.skipif(not shutil.which("pdflatex"), reason="Synthetic image renderer needs pdflatex")
def test_fixture_interruption_and_encrypted_fresh_restore(tmp_path) -> None:
    source = tmp_path / "source"
    previous_umask = os.umask(0o077)
    try:
        identity = Identity(source / "identity.sqlite3")
        identity.claim(identity.setup_token(), "synthetic-owner", "synthetic-smoke-password")
        fixture.seed(source)
        process = subprocess.Popen(
            [sys.executable, str(FIXTURE), "interrupt", "--root", str(source)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            assert process.stdout
            assert select.select([process.stdout], [], [], 20)[0], "Checkpoint deadline exceeded"
            assert process.stdout.readline().strip() == "CHECKPOINT_PERSISTED"
            process.kill()
            assert process.wait(timeout=5) == -9
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()
        original_fetch = fixture.ats.fetch_company
        asyncio.run(fixture.collection(source, interrupted=False))
        assert fixture.ats.fetch_company is original_fetch
        backup = tmp_path / "backup"
        restored = tmp_path / "restored"
        settings = runtime_settings(source, source / "config/settings.yaml")
        backup_installation(source, settings, backup)
        restore_installation(backup, restored)
        fixture.verify(restored, expected_uid=os.getuid())
        assert Identity(restored / "identity.sqlite3").login(
            "synthetic-owner", "synthetic-smoke-password"
        )
    finally:
        os.umask(previous_umask)
