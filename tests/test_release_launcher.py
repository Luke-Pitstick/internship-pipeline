"""Execute generated POSIX launchers against a controlled curl transport."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
SPEC = importlib.util.spec_from_file_location("release_launcher", DEPLOY / "release_launcher.py")
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)
IMAGE = "ghcr.io/example/pipeline@sha256:" + "b" * 64
BOOTSTRAP = b"import json, sys\nprint(json.dumps(sys.argv[1:]))\nsys.exit(7)\n"


def render(**changes: str) -> str:
    values = {
        "repository": "example/pipeline",
        "version": "v0.1.0-rc.1",
        "bootstrap_sha256": hashlib.sha256(BOOTSTRAP).hexdigest(),
        "bundle_sha256": "a" * 64,
        "image": IMAGE,
    }
    return launcher.render_launcher(**(values | changes))


@pytest.fixture
def transport(tmp_path: Path) -> tuple[dict[str, str], Path]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "python3").symlink_to(os.path.realpath(sys.executable))
    payload = tmp_path / "bootstrap bytes.py"
    payload.write_bytes(BOOTSTRAP)
    calls = tmp_path / "downloads.json"
    curl = bindir / "curl"
    curl.write_text(
        f"#!{os.path.realpath(sys.executable)}\n"
        "import json, os, pathlib, shutil, sys\n"
        "pathlib.Path(os.environ['DOWNLOAD_CALLS']).write_text(json.dumps(sys.argv[1:]))\n"
        "if os.environ.get('DOWNLOAD_FAILURE'): sys.exit(22)\n"
        "target = sys.argv[sys.argv.index('--output') + 1]\n"
        "shutil.copyfile(os.environ['BOOTSTRAP_PAYLOAD'], target)\n"
    )
    curl.chmod(0o700)
    temporary = tmp_path / "temporary path with spaces"
    temporary.mkdir()
    env = dict(
        os.environ,
        PATH=str(bindir) + os.pathsep + os.environ.get("PATH", ""),
        TMPDIR=str(temporary),
        BOOTSTRAP_PAYLOAD=str(payload),
        DOWNLOAD_CALLS=str(calls),
    )
    return env, calls


def execute(script: str, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", "-s", "--", *args], input=script, env=env, text=True, capture_output=True
    )


@pytest.mark.parametrize("downloaded_file", [False, True])
def test_literal_options_pinned_metadata_exit_and_cleanup(
    transport: tuple[dict[str, str], Path], tmp_path: Path, downloaded_file: bool
) -> None:
    env, calls = transport
    sentinel = tmp_path / "never created"
    arguments = ["--install-dir", f"{tmp_path}/user's $(touch {sentinel}) path", "--port=9191"]
    if downloaded_file:
        path = tmp_path / "downloaded install.sh"
        path.write_text(render())
        result = subprocess.run(
            ["/bin/sh", str(path), *arguments], env=env, text=True, capture_output=True
        )
    else:
        result = execute(render(), env, *arguments)
    assert result.returncode == 7, result.stderr
    assert json.loads(result.stdout) == [
        "--bundle-url",
        "https://github.com/example/pipeline/releases/download/v0.1.0-rc.1/"
        "internship-pipeline-installer-v0.1.0-rc.1.tar.gz",
        "--sha256",
        "a" * 64,
        "--version",
        "v0.1.0-rc.1",
        "--release-image",
        IMAGE,
        "--",
        *arguments,
    ]
    curl_args = json.loads(calls.read_text())
    assert curl_args[:5] == ["--disable", "--fail", "--silent", "--show-error", "--location"]
    assert curl_args[curl_args.index("--proto") + 1] == "=https"
    assert curl_args[curl_args.index("--proto-redir") + 1] == "=https"
    assert curl_args[-1].endswith("/v0.1.0-rc.1/bootstrap_installer.py")
    assert not sentinel.exists()
    assert list(Path(env["TMPDIR"]).iterdir()) == []


@pytest.mark.parametrize("failure", ["download", "digest", "empty", "oversize"])
def test_failure_never_executes_bootstrap_and_cleans_up(
    transport: tuple[dict[str, str], Path], failure: str
) -> None:
    env, _ = transport
    if failure == "download":
        env["DOWNLOAD_FAILURE"] = "1"
    if failure == "empty":
        Path(env["BOOTSTRAP_PAYLOAD"]).write_bytes(b"")
    if failure == "oversize":
        Path(env["BOOTSTRAP_PAYLOAD"]).write_bytes(b"x" * 2097153)
    script = render(bootstrap_sha256="c" * 64) if failure == "digest" else render()
    result = execute(script, env)
    assert result.returncode != 0
    assert result.stdout == ""
    assert list(Path(env["TMPDIR"]).iterdir()) == []


def test_truncated_pipe_cannot_start_any_download(transport: tuple[dict[str, str], Path]) -> None:
    env, calls = transport
    script = render()
    # Every line boundary, every position in the final invocation, and the last
    # closing parenthesis cover executable shell prefixes and interrupted delivery.
    offsets = {offset for offset, char in enumerate(script) if char == "\n"}
    final = script.rindex('python3 "$temporary/bootstrap_installer.py"')
    offsets.update(range(final, len(script) - 2))
    for offset in sorted(offsets):
        if offset > script.rindex(")"):
            continue
        result = execute(script[:offset], env)
        assert not calls.exists(), (offset, result.stdout, result.stderr)
        assert list(Path(env["TMPDIR"]).iterdir()) == []


def test_help_is_offline_without_python_or_runtime(tmp_path: Path) -> None:
    # cat is the only utility needed to print the help text.
    (tmp_path / "cat").symlink_to("/bin/cat")
    result = execute(render(), {"PATH": str(tmp_path)}, "--help")
    assert result.returncode == 0
    assert "Python 3.12+" in result.stdout
    assert "--image" not in result.stdout


def test_missing_python_guidance_precedes_download(tmp_path: Path) -> None:
    result = execute(render(), {"PATH": str(tmp_path)})
    assert result.returncode == 1
    assert "Install Python" in result.stderr


@pytest.mark.parametrize(
    "changes",
    [
        {"repository": "example/repo;touch /tmp/bad"},
        {"repository": "https://github.com/example/repo"},
        {"version": "latest"},
        {"version": "v1.0.0/../../escape"},
        {"bootstrap_sha256": "A" * 64},
        {"bundle_sha256": "a" * 63},
        {"image": "ghcr.io/example/pipeline:latest"},
        {"image": "registry.invalid/example/pipeline@sha256:" + "a" * 64},
        {"image": "ghcr.io/example/../pipeline@sha256:" + "a" * 64},
    ],
)
def test_rejects_unsafe_or_unpinned_inputs(changes: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        render(**changes)
