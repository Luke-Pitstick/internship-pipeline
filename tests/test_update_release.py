"""One release selection policy is shared by the curl entry point and updater."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
import bootstrap_installer  # noqa: E402
import pipeline_release as releases  # noqa: E402
from build_installer_bundle import build_bundle  # noqa: E402
from test_update import RELEASE  # noqa: E402


def entry(version, **extra):
    return {
        "tag_name": version,
        "id": 1,
        "published_at": "2026-10-20T12:00:00Z",
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


def test_publication_order_supports_numbering_reset_independent_of_listing_order():
    old = entry("v1.0.3", id=200, published_at="2026-10-19T12:00:00Z")
    reset = entry("v0.1.4-rc.1", id=201)
    stable = entry("v0.1.4", id=202)
    assert releases.select_release([old, reset]) == reset["tag_name"]
    assert releases.select_release([stable, old, reset]) == stable["tag_name"]
    assert releases.select_release([reset, old, stable]) == stable["tag_name"]


@pytest.mark.parametrize("bad", [None, "", "not-a-date", "2026-13-20T12:00:00Z"])
def test_complete_release_without_valid_publication_time_is_rejected(bad):
    with pytest.raises(ValueError):
        releases.select_release([entry("v0.1.4", published_at=bad)])


@pytest.mark.parametrize("status", ["behind", "diverged", "identical", "ahead"])
def test_update_direction_is_proven_from_source_ancestry(monkeypatch, status):
    base, target = "a" * 40, "b" * 40
    calls = []

    def fetch(url):
        calls.append(url)
        return json.dumps(
            {"status": status, "base_commit": {"sha": base}, "merge_base_commit": {"sha": base}}
        ).encode()

    monkeypatch.setattr(releases, "fetch", fetch)
    if status == "ahead":
        releases.require_forward_source(base, target)
    else:
        with pytest.raises(ValueError, match="downgrade"):
            releases.require_forward_source(base, target)
    assert calls == [
        f"https://api.github.com/repos/{releases.REPOSITORY}/compare/"
        f"{base}...{target}?per_page=1&page=2"
    ]


def test_same_source_promotion_needs_no_ancestry_network_request(monkeypatch):
    monkeypatch.setattr(releases, "fetch", Mock(side_effect=AssertionError("Unexpected network")))
    releases.require_forward_source("a" * 40, "a" * 40)


@pytest.mark.parametrize(
    "body",
    [
        {},
        [],
        {
            "status": "ahead",
            "base_commit": {"sha": "a" * 40},
            "merge_base_commit": {"sha": "c" * 40},
        },
    ],
)
def test_missing_or_divergent_ancestry_is_rejected(monkeypatch, body):
    monkeypatch.setattr(releases, "fetch", lambda url: json.dumps(body).encode())
    with pytest.raises(ValueError):
        releases.require_forward_source("a" * 40, "b" * 40)


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
    downloads = []

    def download(*args, **kwargs):
        downloads.append(kwargs)
        return b"verified-bundle"

    monkeypatch.setattr(bootstrap_installer, "download", download)
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
    assert downloads == [{"progress": False}]


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

    def download(url, digest, *, progress=True):
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


@pytest.mark.parametrize("interactive", [False, True])
def test_staging_reports_installer_download_once(tmp_path, monkeypatch, capsys, interactive):
    deploy = Path(__file__).resolve().parents[1] / "deploy"
    built = build_bundle(deploy, tmp_path / "assets", RELEASE.version, RELEASE.source_commit)
    payloads = {
        "bootstrap_installer.py": (deploy / "bootstrap_installer.py").read_bytes(),
        "install.sh": b"#!/bin/sh\nexit 0\n",
        built["archive"]: (tmp_path / "assets" / built["archive"]).read_bytes(),
    }
    release = replace(
        RELEASE,
        bootstrap_sha256=hashlib.sha256(payloads["bootstrap_installer.py"]).hexdigest(),
        launcher_sha256=hashlib.sha256(payloads["install.sh"]).hexdigest(),
        bundle_sha256=built["archive_sha256"],
    )
    requests = []

    def open_response(request, **kwargs):
        requests.append(request.full_url)
        payload = payloads[request.full_url.rsplit("/", 1)[-1]]
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status = 200
        response.headers = {"Content-Length": str(len(payload))}
        response.geturl.return_value = request.full_url
        response.read1.side_effect = [payload, b""]
        return response

    opener = Mock()
    opener.open.side_effect = open_response
    monkeypatch.setattr(bootstrap_installer.urllib.request, "build_opener", lambda *args: opener)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: interactive)
    monkeypatch.setenv("TERM", "xterm")
    release.stage(tmp_path)
    output = capsys.readouterr().err
    assert len(requests) == 3
    assert output.count("Downloading installer bundle…") == 1
    assert output.count("Installer bundle verified.") == 1
    assert output.count("[====================] 100%") == int(interactive)
