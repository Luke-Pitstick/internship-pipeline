"""One release selection policy is shared by the curl entry point and updater."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
import bootstrap_installer  # noqa: E402
import pipeline_release as releases  # noqa: E402
from build_installer_bundle import build_bundle  # noqa: E402
from test_update import RELEASE  # noqa: E402


def entry(version, **extra):
    return {
        "tag_name": version,
        "draft": False,
        "assets": [
            {"name": name}
            for name in (
                "install.sh",
                "release-metadata.json",
                "bootstrap_installer.py",
                f"internship-pipeline-installer-{version}.tar.gz",
            )
        ],
        **extra,
    }


def metadata(**extra):
    return {**asdict(RELEASE), "schema": 1, "repository": releases.REPOSITORY, **extra}


def test_drafts_incomplete_and_unrelated_tags_do_not_replace_complete_release():
    listing = [
        entry("v0.1.0-rc.5", draft=True),
        entry("v0.1.0-rc.4", assets=[]),
        entry("unrelated"),
        entry(RELEASE.version),
    ]
    assert releases.select_release(listing) == RELEASE.version


@pytest.mark.parametrize(
    "versions,expected",
    [
        (["v1.0.0-rc.99", "v1.0.0"], "v1.0.0"),
        (["v1.0.0", "v1.0.1-rc.1"], "v1.0.1-rc.1"),
        (["v1.0.0-rc.2", "v1.0.0-rc.10"], "v1.0.0-rc.10"),
        (["v1.0.0", "v0.9.9"], "v1.0.0"),
    ],
)
def test_latest_complete_version_uses_numeric_order_and_stable_precedence(versions, expected):
    assert releases.select_release([entry(version) for version in versions]) == expected


def test_stable_release_metadata_is_valid_and_incomplete_stable_is_skipped():
    assert releases.Release.parse(metadata(version="v1.0.0"), "v1.0.0").version == "v1.0.0"
    assert releases.select_release([entry("v1.0.0", assets=[]), entry(RELEASE.version)]) == (
        RELEASE.version
    )


@pytest.mark.parametrize("listing", [{"message": "API rate limit exceeded"}, {}, [], [None]])
def test_no_valid_preview_is_an_explicit_failure(listing):
    with pytest.raises(ValueError):
        releases.select_release(listing)


@pytest.mark.parametrize("bad", [True, 1.0, "1", 0, None])
def test_metadata_refuses_noninteger_or_missing_storage_contract(bad):
    with pytest.raises(ValueError, match="storage format"):
        releases.Release.parse(metadata(storage_format=bad), RELEASE.version)


def test_newest_incompatible_format_is_reported_without_older_release_fallback(monkeypatch):
    calls = []

    def fetch(url):
        calls.append(url)
        return json.dumps(
            [entry(RELEASE.version), entry("v0.1.0-rc.1")]
            if "api.github.com" in url
            else metadata(storage_format=2)
        ).encode()

    monkeypatch.setattr(releases, "fetch", fetch)
    assert releases.latest().storage_format == 2
    assert len(calls) == 2 and RELEASE.version in calls[-1]


def test_reviewed_bootstrap_pins_the_selected_update_instead_of_resolving_again(
    tmp_path, monkeypatch
):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(bootstrap_installer, "download", lambda *args: b"verified-bundle")
    monkeypatch.setattr(bootstrap_installer, "unpack", lambda *args: bundle)
    monkeypatch.setattr(releases, "fetch", lambda url: json.dumps(metadata()).encode())
    launches = []

    def launch(argv, **kwargs):
        launches.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(bootstrap_installer.subprocess, "run", launch)
    assert (
        bootstrap_installer.main(
            [
                "--bundle-url",
                f"{RELEASE.base}/internship-pipeline-installer-{RELEASE.version}.tar.gz",
                "--sha256",
                RELEASE.bundle_sha256,
                "--version",
                RELEASE.version,
                "--release-image",
                RELEASE.image,
                "--",
                "--update",
            ]
        )
        == 0
    )
    assert json.loads((bundle / ".selected-release.json").read_text())["image"] == RELEASE.image
    assert (bundle / ".selected-release.json").stat().st_mode & 0o077 == 0
    assert "--update" in launches[0]


@pytest.mark.parametrize("different_bootstrap", [False, True])
def test_staged_release_verifies_complete_archive_and_bootstrap_agreement(
    tmp_path, monkeypatch, different_bootstrap
):
    deploy = Path(__file__).resolve().parents[1] / "deploy"
    built = build_bundle(deploy, tmp_path / "assets", RELEASE.version, RELEASE.source_commit)
    bootstrap = (
        b"different reviewed bootstrap"
        if different_bootstrap
        else (deploy / "bootstrap_installer.py").read_bytes()
    )
    launcher = b"#!/bin/sh\nexit 0\n"
    release = replace(
        RELEASE,
        bootstrap_sha256=hashlib.sha256(bootstrap).hexdigest(),
        launcher_sha256=hashlib.sha256(launcher).hexdigest(),
        bundle_sha256=built["archive_sha256"],
    )
    payloads = {
        "bootstrap_installer.py": bootstrap,
        "install.sh": launcher,
        f"internship-pipeline-installer-{release.version}.tar.gz": (
            tmp_path / "assets" / built["archive"]
        ).read_bytes(),
    }

    def download(url, digest):
        payload = payloads[url.rsplit("/", 1)[-1]]
        assert hashlib.sha256(payload).hexdigest() == digest
        return payload

    monkeypatch.setattr(bootstrap_installer, "download", download)
    target = tmp_path / "target"
    target.mkdir()
    if different_bootstrap:
        with pytest.raises(ValueError, match="bundled bootstrap differs"):
            release.stage(target)
    else:
        bundle = release.stage(target)
        assert (bundle / "pipeline_update.py").is_file()
        assert (bundle / "internship-pipeline").stat().st_mode & 0o100
