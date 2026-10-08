"""Real native stdin transfer semantics; no actual container/UID-map certification."""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
sys.path.insert(0, str(DEPLOY))
import pipeline_runtime as runtime  # noqa: E402

from internship_pipeline.identity import Identity  # noqa: E402
from internship_pipeline.model_connections import ModelConnectionStore  # noqa: E402
from internship_pipeline.models import Settings  # noqa: E402
from internship_pipeline.operations import backup_installation  # noqa: E402
from internship_pipeline.storage import Store  # noqa: E402


def backup_fixture(tmp_path):
    root = tmp_path / "source"
    settings = Settings(database_path=root / "state.sqlite3", artifact_dir=root / "artifacts")
    Store(settings.database_path)
    account = Identity(root / "identity.sqlite3")
    account.claim(account.setup_token(), "owner", "synthetic recovery password")
    ModelConnectionStore(settings.database_path, root / "model-credentials.key")
    backup = tmp_path / "owner-only backup"
    backup_installation(root, settings, backup)
    return backup


def test_native_private_archive_restores_from_stdin_without_host_bind(tmp_path):
    backup = backup_fixture(tmp_path)
    before = {
        path: (path.stat().st_uid, path.stat().st_mode, path.read_bytes())
        for path in backup.rglob("*")
        if path.is_file()
    }
    extracted = tmp_path / "volume/backup"
    restored = tmp_path / "volume/restored"
    extracted.parent.mkdir(mode=0o700)
    with io.BytesIO() as stream:
        digest = runtime.archive_backup(backup, stream, time.monotonic() + 30)
        with tarfile.open(fileobj=stream, mode="r") as archive:
            assert all(item.uid == item.gid == 10001 for item in archive.getmembers())
        stream.seek(0)
        script = runtime.RESTORE_STREAM.replace("/var/data/backup", str(extracted)).replace(
            "/var/data/restored", str(restored)
        )
        result = subprocess.run(
            [sys.executable, "-c", script, digest],
            input=stream.read(),
            capture_output=True,
            timeout=30,
            check=False,
        )
    assert result.returncode == 0, result.stderr.decode()
    assert backup.stat().st_mode & 0o777 == 0o700
    assert Identity(restored / "identity.sqlite3").login("owner", "synthetic recovery password")
    for path, state in before.items():
        assert (path.stat().st_uid, path.stat().st_mode, path.read_bytes()) == state
    for path in extracted.rglob("*"):
        # tar UID is not an ownership change: unprivileged extraction writes as
        # the receiving process, just as the image's UID10001 will do in its volume.
        assert path.stat().st_uid == os.getuid()
        assert path.stat().st_mode & 0o077 == 0
    assert hashlib.sha256((extracted / "manifest.json").read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("link", ["symlink", "hardlink"])
def test_transfer_refuses_links_before_launch(tmp_path, link):
    backup = backup_fixture(tmp_path)
    source = backup / "manifest.json"
    target = backup / "unsafe"
    if link == "symlink":
        target.symlink_to(source)
    else:
        os.link(source, target)
    with pytest.raises(runtime.Failure, match="unsafe"):
        runtime.archive_backup(backup, io.BytesIO(), time.monotonic() + 30)


def test_transfer_refuses_low_temp_disk_and_expired_deadline(tmp_path, monkeypatch):
    backup = backup_fixture(tmp_path)
    monkeypatch.setattr(runtime.shutil, "disk_usage", lambda _path: SimpleNamespace(free=0))
    with pytest.raises(runtime.Failure, match="temporary disk"):
        runtime.archive_backup(backup, io.BytesIO(), time.monotonic() + 30)
    monkeypatch.setattr(runtime.shutil, "disk_usage", lambda _path: SimpleNamespace(free=10**12))
    with pytest.raises(runtime.Failure, match="timed out"):
        runtime.archive_backup(backup, io.BytesIO(), time.monotonic() - 1)


def test_transfer_rejects_changed_manifest_identity_in_receiving_process(tmp_path):
    backup = backup_fixture(tmp_path)
    extracted = tmp_path / "volume/backup"
    restored = tmp_path / "volume/restored"
    extracted.parent.mkdir(mode=0o700)
    stream = io.BytesIO()
    runtime.archive_backup(backup, stream, time.monotonic() + 30)
    script = runtime.RESTORE_STREAM.replace("/var/data/backup", str(extracted)).replace(
        "/var/data/restored", str(restored)
    )
    result = subprocess.run(
        [sys.executable, "-c", script, "0" * 64],
        input=stream.read(),
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert not restored.exists()


def test_saved_runtime_stdin_command_timeout_includes_receiver_read(tmp_path):
    executable = tmp_path / "docker"
    executable.write_text(f"#!{os.path.realpath(sys.executable)}\nimport time\ntime.sleep(10)\n")
    executable.chmod(0o700)
    engine = runtime.Runtime(runtime.RuntimeSpec("docker", str(executable), "unix:///fake.sock"))
    with (tmp_path / "private-stream").open("w+b") as stream:
        stream.write(b"synthetic" * 10000)
        stream.seek(0)
        start = time.monotonic()
        with pytest.raises(runtime.Failure, match="could not complete"):
            engine.run("run", "-i", "exact-image", stdin=stream, timeout=0.05)
        assert time.monotonic() - start < 2
