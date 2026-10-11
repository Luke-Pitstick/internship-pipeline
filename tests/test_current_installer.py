"""The public curl entry point selects one complete release and verifies its launcher."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[1] / "install.sh").read_text()
VERSION = "v0.1.0-rc.123"
REVISION = "a" * 40
LAUNCHER = b"#!/bin/sh\nprintf '%s\\n' \"$@\"\nexit 7\n"


def execute(tmp_path, *, corrupt=False, incomplete=False, wrong_source=False):
    release = {
        "tag_name": VERSION,
        "draft": False,
        "assets": [
            {"name": name}
            for name in [
                "install.sh",
                "release-metadata.json",
                "bootstrap_installer.py",
                f"internship-pipeline-installer-{VERSION}.tar.gz",
            ]
        ],
    }
    if incomplete:
        release["assets"] = []
    # A newer draft must never supersede the accepted public release.
    releases = [{**release, "tag_name": "v0.1.0-rc.999", "draft": True}, release]
    metadata = {
        "repository": "Luke-Pitstick/internship-pipeline",
        "version": VERSION,
        "source_commit": "bad" if wrong_source else REVISION,
        "image": "ghcr.io/luke-pitstick/internship-pipeline@sha256:" + "b" * 64,
        "launcher_sha256": hashlib.sha256(LAUNCHER).hexdigest(),
    }
    payloads = tmp_path / "payloads"
    payloads.mkdir()
    (payloads / "releases.json").write_text(json.dumps(releases))
    (payloads / "release-metadata.json").write_text(json.dumps(metadata))
    (payloads / "install.sh").write_bytes(LAUNCHER + (b"#corrupt" if corrupt else b""))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        f"#!{os.path.realpath(sys.executable)}\n"
        "import os,pathlib,shutil,sys\n"
        "url=sys.argv[-1]\n"
        "name='releases.json' if 'api.github.com' in url else url.rsplit('/',1)[-1]\n"
        "if name!='releases.json':\n"
        f"    assert '/releases/download/{VERSION}/' in url\n"
        "shutil.copyfile(pathlib.Path(os.environ['PAYLOADS'])/name,"
        "sys.argv[sys.argv.index('--output')+1])\n"
    )
    curl.chmod(0o700)
    env = dict(
        os.environ,
        PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
        PAYLOADS=str(payloads),
        TMPDIR=str(tmp_path),
    )
    return subprocess.run(
        ["sh", "-s", "--", "--install-dir", "/a path/$(never execute)"],
        input=SCRIPT,
        text=True,
        capture_output=True,
        env=env,
    )


def test_current_curl_selects_complete_public_release_and_preserves_arguments(tmp_path):
    result = execute(tmp_path)
    assert result.returncode == 7, result.stderr
    assert f"Installing {VERSION} from commit {REVISION[:12]}" in result.stdout
    assert result.stdout.endswith("--install-dir\n/a path/$(never execute)\n")
    assert not list(tmp_path.glob("pipeline-current.*"))


@pytest.mark.parametrize("failure", ["corrupt", "incomplete", "wrong_source"])
def test_current_curl_refuses_unverified_or_incomplete_release(tmp_path, failure):
    result = execute(tmp_path, **{failure: True})
    assert result.returncode != 7 and result.returncode != 0
    assert "--install-dir" not in result.stdout
    assert not list(tmp_path.glob("pipeline-current.*"))


def test_partial_current_launcher_cannot_start_a_download(tmp_path):
    script = SCRIPT[: SCRIPT.index("PIPELINE_SELECT\n)")]
    result = subprocess.run(
        ["sh", "-s"],
        input=script,
        text=True,
        capture_output=True,
        env=dict(os.environ, TMPDIR=str(tmp_path)),
    )
    assert result.returncode != 0
    assert not list(tmp_path.iterdir())
