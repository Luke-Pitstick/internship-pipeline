"""Deterministic release generation binds clean, synthetic Git source."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
sys.path.insert(0, str(DEPLOY))
import build_release_assets as assets  # noqa: E402

REPOSITORY = "Example/pipeline"
VERSION = "v0.1.0-rc.1"
IMAGE = "ghcr.io/example/pipeline@sha256:" + "a" * 64


def source_repository(path: Path) -> tuple[Path, str]:
    path.mkdir()
    (path / "deploy").mkdir()
    for name in assets.ARCHIVE_FILES:
        target = path / "LICENSE" if name == "LICENSE" else path / "deploy" / name
        target.write_text(f"# synthetic {name}\n")
    (path / "deploy/bootstrap_installer.py").write_text("# synthetic bootstrap\n")
    for name in assets.GENERATOR_FILES:
        (path / "deploy" / name).write_bytes((DEPLOY / name).read_bytes())
    (path / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
    (path / "uv.lock").write_text("# synthetic lock\n")
    (path / "web").mkdir()
    (path / "web/package-lock.json").write_text('{"synthetic": true}\n')
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=synthetic@example.invalid",
            "commit",
            "-qm",
            "Synthetic",
        ],
        check=True,
    )
    revision = subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()
    return path, revision


def test_assets_repeat_exactly_and_bind_all_bytes(tmp_path: Path) -> None:
    source, revision = source_repository(tmp_path / "source")
    for name in ("one", "two"):
        metadata = assets.build_release_assets(
            source,
            tmp_path / name,
            repository=REPOSITORY,
            version=VERSION,
            source_commit=revision,
            image=IMAGE,
        )
        assert metadata["source_commit"] == revision
        assert metadata["image"] == IMAGE
    one, two = tmp_path / "one", tmp_path / "two"
    assert {p.name: p.read_bytes() for p in one.iterdir()} == {
        p.name: p.read_bytes() for p in two.iterdir()
    }
    subprocess.run(["sh", "-n", str(one / "install.sh")], check=True)
    for line in (one / "SHA256SUMS").read_text().splitlines():
        digest, filename = line.split("  ")
        assert hashlib.sha256((one / filename).read_bytes()).hexdigest() == digest
    metadata = json.loads((one / "release-metadata.json").read_text())
    launcher = (one / "install.sh").read_text()
    assert metadata["bootstrap_sha256"] in launcher
    assert metadata["bundle_sha256"] in launcher
    assert IMAGE in launcher
    assert (one / "bootstrap_installer.py").read_bytes() == (
        source / "deploy/bootstrap_installer.py"
    ).read_bytes()


@pytest.mark.parametrize("change", ["tracked", "untracked", "revision", "image", "version"])
def test_invalid_source_and_identities_fail_before_output(tmp_path: Path, change: str) -> None:
    source, revision = source_repository(tmp_path / "source")
    image, version = IMAGE, VERSION
    if change == "tracked":
        (source / "deploy/install.py").write_text("changed\n")
    elif change == "untracked":
        (source / "unexpected").write_text("changed\n")
    elif change == "revision":
        revision = "a" * 40
    elif change == "image":
        image = "ghcr.io/another/pipeline@sha256:" + "a" * 64
    else:
        version = "v0.1.0;touch injected"
    with pytest.raises(ValueError):
        assets.build_release_assets(
            source,
            tmp_path / "out",
            repository=REPOSITORY,
            version=version,
            source_commit=revision,
            image=image,
        )
    assert not (tmp_path / "out").exists()


def test_existing_release_directory_is_never_replaced(tmp_path: Path) -> None:
    source, revision = source_repository(tmp_path / "source")
    output = tmp_path / "out"
    output.mkdir()
    sentinel = output / "install.sh"
    sentinel.write_text("previous release")
    with pytest.raises(ValueError, match="already exists"):
        assets.build_release_assets(
            source,
            output,
            repository=REPOSITORY,
            version=VERSION,
            source_commit=revision,
            image=IMAGE,
        )
    assert sentinel.read_text() == "previous release"


def test_assume_unchanged_cannot_certify_modified_installer(tmp_path: Path) -> None:
    source, revision = source_repository(tmp_path / "source")
    subprocess.run(
        ["git", "-C", str(source), "update-index", "--assume-unchanged", "deploy/install.py"],
        check=True,
    )
    (source / "deploy/install.py").write_text("uncommitted sentinel\n")
    assert not subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"])
    with pytest.raises(ValueError, match="committed bytes"):
        assets.build_release_assets(
            source,
            tmp_path / "out",
            repository=REPOSITORY,
            version=VERSION,
            source_commit=revision,
            image=IMAGE,
        )
    assert not (tmp_path / "out").exists()


def test_external_source_cannot_use_another_generator(tmp_path: Path) -> None:
    source, _ = source_repository(tmp_path / "source")
    (source / "deploy/release_launcher.py").write_text("different committed generator\n")
    subprocess.run(["git", "-C", str(source), "add", "deploy/release_launcher.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=synthetic@example.invalid",
            "commit",
            "-qm",
            "Generator",
        ],
        check=True,
    )
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    with pytest.raises(ValueError, match="Executing generator"):
        assets.build_release_assets(
            source,
            tmp_path / "out",
            repository=REPOSITORY,
            version=VERSION,
            source_commit=revision,
            image=IMAGE,
        )
    assert not (tmp_path / "out").exists()
