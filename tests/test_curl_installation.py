"""Pipe the release shell through real bootstrap/installer code with controlled I/O.

Only the HTTPS transport and container executable are fake. No real network,
engine, user installation, provider credential or source checkout is required.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from test_installer import FAKE

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
REPOSITORY = "example/internship-pipeline"
IMAGE = "ghcr.io/example/internship-pipeline@sha256:" + "b" * 64
VERSION = "v0.1.0-rc.1"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, DEPLOY / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load("build_installer_bundle")
launcher = load("release_launcher")

# This executable interpreter leaves production download/unpack/main functions
# intact and replaces only urllib's response transport. Each subprocess gets it.
PYTHON_TRANSPORT = r"""
import io, json, os, pathlib, runpy, sys, urllib.request
mapping = json.loads(pathlib.Path(os.environ['CURL_TEST_DOWNLOADS']).read_text())
class Reply(io.BytesIO):
    def __init__(self, url):
        self.url = url
        payload = pathlib.Path(mapping[url]).read_bytes()
        original_length = len(payload)
        mode = os.environ.get('CURL_TEST_FAULT', '')
        if mode == 'bundle_changed': payload += b'changed'
        if mode == 'bundle_incomplete': payload = payload[:-7]
        super().__init__(payload)
        self.status = 503 if mode == 'bundle_status' else 200
        received_length = original_length if mode == 'bundle_incomplete' else len(payload)
        self.headers = {'Content-Length': str(received_length)}
    def geturl(self): return self.url
class Transport:
    def open(self, request, timeout):
        url = request.full_url
        if url not in mapping or not url.startswith('https://github.com/example/'):
            raise RuntimeError('Unexpected controlled download URL')
        with open(os.environ['CURL_TEST_HTTP_LOG'], 'a') as log:
            log.write(json.dumps({'url': url, 'timeout': timeout}) + '\n')
        return Reply(url)
urllib.request.build_opener = lambda *args: Transport()
args = sys.argv[1:]
if args[0] == '-c':
    sys.argv = ['-c', *args[2:]]
    exec(compile(args[1], '<controlled-python-command>', 'exec'), {'__name__': '__main__'})
elif args[0] == '-':
    sys.argv = ['-', *args[1:]]
    exec(compile(sys.stdin.read(), '<controlled-python-input>', 'exec'), {'__name__': '__main__'})
else:
    script = args[0]
    sys.argv = args
    sys.path.insert(0, str(pathlib.Path(script).resolve().parent))
    runpy.run_path(script, run_name='__main__')
"""

CURL_TRANSPORT = r"""
import json, os, pathlib, sys
args = sys.argv[1:]
mapping = json.loads(pathlib.Path(os.environ['CURL_TEST_DOWNLOADS']).read_text())
with open(os.environ['CURL_TEST_CURL_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\n')
for option in ('--fail', '--location', '--proto', '--proto-redir', '--max-time', '--max-filesize'):
    if option not in args: sys.exit('Missing bounded HTTPS curl option')
if args[args.index('--proto') + 1] != '=https' or args[args.index('--proto-redir') + 1] != '=https':
    sys.exit('Unrestricted download protocol')
url = args[-1]
if url not in mapping: sys.exit('Unexpected controlled curl URL')
payload = pathlib.Path(mapping[url]).read_bytes()
mode = os.environ.get('CURL_TEST_FAULT', '')
if mode == 'bootstrap_status': sys.exit(22)
if mode == 'bootstrap_changed': payload += b'changed'
if mode == 'bootstrap_incomplete': payload = payload[:-7]
pathlib.Path(args[args.index('--output') + 1]).write_bytes(payload)
"""


@pytest.fixture
def flow(tmp_path: Path) -> dict[str, Any]:
    tools = tmp_path / "tools"
    tools.mkdir()
    executable = os.path.realpath(sys.executable)
    for name, code in (("python3", PYTHON_TRANSPORT), ("curl", CURL_TRANSPORT), ("docker", FAKE)):
        target = tools / name
        target.write_text(f"#!{executable}\n" + code)
        target.chmod(0o700)
    # Allow only shell utilities the launcher needs. Host runtimes and download
    # clients must never become fallbacks when a test removes a fake executable.
    for name in ("cat", "dirname", "mktemp", "rm", "sh"):
        utility = shutil.which(name)
        assert utility is not None
        (tools / name).symlink_to(utility)
    state = tmp_path / "engine.json"
    state.write_text(json.dumps({"calls": [], "containers": {}, "volumes": {}}))
    downloads = tmp_path / "downloads.json"
    downloads.write_text("{}")
    private_temp = tmp_path / "temporary space"
    private_temp.mkdir(mode=0o700)
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("DOCKER_", "CONTAINER_")):
            env.pop(key)
    env.update(
        PATH=str(tools),
        FAKE_ENGINE_STATE=str(state),
        CURL_TEST_DOWNLOADS=str(downloads),
        CURL_TEST_CURL_LOG=str(tmp_path / "curl.jsonl"),
        CURL_TEST_HTTP_LOG=str(tmp_path / "http.jsonl"),
        TMPDIR=str(private_temp),
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return {
        "root": tmp_path,
        "tools": tools,
        "env": env,
        "state": state,
        "downloads": downloads,
        "temporary": private_temp,
        "install": tmp_path / "installed state with spaces",
        "commands": tmp_path / "commands with spaces",
        "port": port,
    }


def candidate(flow: dict[str, Any], version: str = VERSION, image: str = IMAGE) -> str:
    source = flow["root"] / ("checkout-" + version)
    source.mkdir()
    deploy = source / "deploy"
    deploy.mkdir()
    for name in builder.BUNDLE_FILES:
        shutil.copyfile(DEPLOY / name, deploy / name)
    shutil.copyfile(DEPLOY.parent / "LICENSE", source / "LICENSE")
    bootstrap = source / "bootstrap_installer.py"
    shutil.copyfile(DEPLOY / "bootstrap_installer.py", bootstrap)
    metadata = builder.build_bundle(deploy, source / "assets", version, "a" * 40)
    base = f"https://github.com/{REPOSITORY}/releases/download/{version}"
    mapping = json.loads(flow["downloads"].read_text())
    mapping[base + "/bootstrap_installer.py"] = str(bootstrap)
    mapping[base + "/" + metadata["archive"]] = str(source / "assets" / metadata["archive"])
    flow["downloads"].write_text(json.dumps(mapping))
    return launcher.render_launcher(
        repository=REPOSITORY,
        version=version,
        bootstrap_sha256=hashlib.sha256(bootstrap.read_bytes()).hexdigest(),
        bundle_sha256=metadata["archive_sha256"],
        image=image,
    )


def invoke(flow: dict[str, Any], text: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/bin/sh",
            "-s",
            "--",
            "--install-dir",
            str(flow["install"]),
            "--command-dir",
            str(flow["commands"]),
            "--runtime",
            "docker",
            "--port",
            str(flow["port"]),
            "--ready-timeout",
            "1",
            "--no-open",
            *extra,
        ],
        input=text,
        text=True,
        capture_output=True,
        env=flow["env"],
        timeout=30,
    )


def test_piped_install_ready_management_without_checkout_and_new_release_rerun(
    flow: dict[str, Any],
) -> None:
    text = candidate(flow)
    result = invoke(flow, text)
    assert result.returncode == 0, result.stderr
    url = f"http://localhost:{flow['port']}"
    assert f"Ready: {url}" in result.stdout
    assert f"Open your workspace: {url}/#setup=" in result.stdout
    assert "logs --tail 200" not in result.stdout
    manifest_path = flow["install"] / "installation.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["image"] == IMAGE
    before = json.loads(flow["state"].read_text())
    assert before["volumes"][manifest["volume_name"]]["payload"] == "synthetic-data-preserve"
    pulls = [call["args"] for call in before["calls"] if call["args"][0] == "pull"]
    assert pulls == [["pull", IMAGE]]
    create = next(call["args"] for call in before["calls"] if call["args"][0] == "create")
    assert create[-1] == IMAGE
    assert create[create.index("--publish") + 1] == f"127.0.0.1:{flow['port']}:8080"
    assert manifest_path.stat().st_mode & 0o777 == 0o600
    assert list(flow["temporary"].iterdir()) == []

    shutil.rmtree(flow["root"] / ("checkout-" + VERSION))
    command = flow["commands"] / "internship-pipeline"
    assert command.is_symlink()
    for operation in ("status", "stop", "start", "url"):
        managed = subprocess.run(
            [str(command), operation],
            text=True,
            capture_output=True,
            env=flow["env"],
            timeout=15,
        )
        assert managed.returncode == 0, managed.stderr
        if operation in {"status", "url"}:
            assert url in managed.stdout

    flow["state"].write_text(json.dumps({**json.loads(flow["state"].read_text()), "calls": []}))
    newer = candidate(flow, "v0.2.0-rc.1", "ghcr.io/example/internship-pipeline@sha256:" + "c" * 64)
    rerun = invoke(flow, newer)
    assert rerun.returncode == 0, rerun.stderr
    assert json.loads(manifest_path.read_text()) == manifest
    after = json.loads(flow["state"].read_text())
    assert after["volumes"] == before["volumes"]
    assert after["containers"].keys() == before["containers"].keys()
    assert not any(
        call["args"][0] in {"pull", "create", "run"} or call["args"][:2] == ["volume", "create"]
        for call in after["calls"]
    )


@pytest.mark.parametrize(
    "fault",
    [
        "bootstrap_status",
        "bootstrap_changed",
        "bootstrap_incomplete",
        "bundle_status",
        "bundle_changed",
        "bundle_incomplete",
    ],
)
def test_failed_or_altered_download_never_contacts_engine(flow: dict[str, Any], fault: str) -> None:
    text = candidate(flow)
    flow["env"]["CURL_TEST_FAULT"] = fault
    result = invoke(flow, text)
    assert result.returncode != 0
    assert "Ready:" not in result.stdout
    assert json.loads(flow["state"].read_text())["calls"] == []
    assert not flow["install"].exists()
    assert list(flow["temporary"].iterdir()) == []


@pytest.mark.parametrize(
    "extra",
    [
        ("--image", IMAGE),
        ("--image=" + IMAGE,),
        ("--default-image", IMAGE),
        ("--default-image=" + IMAGE,),
        ("--im", IMAGE),
        ("--default-im", IMAGE),
    ],
)
def test_forwarded_image_authority_cannot_override_release(
    flow: dict[str, Any], extra: tuple[str, ...]
) -> None:
    result = invoke(flow, candidate(flow), *extra)
    assert result.returncode != 0
    assert json.loads(flow["state"].read_text())["calls"] == []
    assert not flow["install"].exists()


def test_quoted_option_is_literal_and_truncated_pipe_cannot_install(flow: dict[str, Any]) -> None:
    text = candidate(flow)
    payload = flow["root"] / "commands $(touch shell-injection-proof) ; quoted"
    result = invoke(flow, text, "--command-dir", str(payload))
    assert result.returncode == 0, result.stderr
    assert (payload / "internship-pipeline").is_symlink()
    assert not (Path.cwd() / "shell-injection-proof").exists()
    before = flow["state"].read_text()
    for prefix in (text[: len(text) // 2], text[: text.rfind(")")]):
        truncated = invoke(flow, prefix)
        assert truncated.returncode != 0
        assert flow["state"].read_text() == before


def test_offline_help_and_missing_prerequisite_guidance(flow: dict[str, Any]) -> None:
    text = candidate(flow)
    help_result = subprocess.run(
        ["/bin/sh", "-s", "--", "--help"],
        input=text,
        text=True,
        capture_output=True,
        env=flow["env"],
        timeout=10,
    )
    assert help_result.returncode == 0
    assert "Python 3.12" in help_result.stdout
    assert json.loads(flow["state"].read_text())["calls"] == []
    flow["tools"].joinpath("docker").unlink()
    result = invoke(flow, text)
    assert result.returncode != 0
    assert "docker is not installed" in result.stderr.lower()
    assert json.loads(flow["state"].read_text())["calls"] == []


@pytest.mark.parametrize(
    "missing, guidance",
    [
        ("python3", "python 3.12 or newer"),
        ("curl", "install curl"),
    ],
)
def test_missing_download_prerequisite_is_actionable_and_offline(
    flow: dict[str, Any], missing: str, guidance: str
) -> None:
    text = candidate(flow)
    # A tools-only PATH prevents the host's curl/Python from masking absence.
    flow["env"]["PATH"] = str(flow["tools"])
    flow["tools"].joinpath(missing).unlink()
    result = invoke(flow, text)
    assert result.returncode != 0
    assert guidance in result.stderr.lower()
    assert json.loads(flow["state"].read_text())["calls"] == []
    assert not Path(flow["env"]["CURL_TEST_CURL_LOG"]).exists()
    assert not Path(flow["env"]["CURL_TEST_HTTP_LOG"]).exists()
    assert not flow["install"].exists()


def test_obsolete_python_prerequisite_is_actionable_and_offline(flow: dict[str, Any]) -> None:
    text = candidate(flow)
    python = flow["tools"] / "python3"
    python.write_text("#!/bin/sh\nexit 1\n")
    python.chmod(0o700)
    result = invoke(flow, text)
    assert result.returncode != 0
    assert "python 3.12 or newer" in result.stderr.lower()
    assert json.loads(flow["state"].read_text())["calls"] == []
    assert not Path(flow["env"]["CURL_TEST_CURL_LOG"]).exists()
    assert not flow["install"].exists()


@pytest.mark.parametrize("unsafe", ["traversal", "link", "unexpected"])
def test_hash_verified_unsafe_bundle_is_rejected_before_engine(
    flow: dict[str, Any], unsafe: str
) -> None:
    candidate(flow)
    base = f"https://github.com/{REPOSITORY}/releases/download/{VERSION}"
    mapping = json.loads(flow["downloads"].read_text())
    bootstrap = Path(mapping[base + "/bootstrap_installer.py"])
    bundle = Path(mapping[base + f"/internship-pipeline-installer-{VERSION}.tar.gz"])
    with tarfile.open(bundle, "r:gz") as archive:
        original = [(member, archive.extractfile(member).read()) for member in archive.getmembers()]
    with tarfile.open(bundle, "w:gz") as archive:
        for member, payload in original:
            archive.addfile(member, io.BytesIO(payload))
        name = (
            "../outside"
            if unsafe == "traversal"
            else f"internship-pipeline-installer-{VERSION}/extra"
        )
        member = tarfile.TarInfo(name)
        if unsafe == "link":
            member.type = tarfile.SYMTYPE
            member.linkname = "/tmp/outside"
            archive.addfile(member)
        else:
            member.size = 9
            archive.addfile(member, io.BytesIO(b"synthetic"))
    # Deliberately bind the new hash: this tests extraction safety after integrity succeeds.
    text = launcher.render_launcher(
        repository=REPOSITORY,
        version=VERSION,
        bootstrap_sha256=hashlib.sha256(bootstrap.read_bytes()).hexdigest(),
        bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
        image=IMAGE,
    )
    result = invoke(flow, text)
    assert result.returncode != 0
    assert json.loads(flow["state"].read_text())["calls"] == []
    assert not flow["install"].exists()
    assert list(flow["temporary"].iterdir()) == []
