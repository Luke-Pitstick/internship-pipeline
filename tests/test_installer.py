"""Simulated installer boundaries using executable fake engines, never real containers."""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
sys.path.insert(0, str(DEPLOY))
from pipeline_runtime import Failure, Runtime, load_manifest, validate_image  # noqa: E402

SPEC = importlib.util.spec_from_file_location("installer_candidate", DEPLOY / "install.py")
assert SPEC and SPEC.loader
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)

FAKE = r"""
import json, os, sys, time
from pathlib import Path
statefile = Path(os.environ["FAKE_ENGINE_STATE"])
state = json.loads(statefile.read_text())
raw = sys.argv[1:]
args = raw[:]
while args and args[0].startswith("--"):
    key = args.pop(0)
    if "=" not in key: args.pop(0)
name = Path(sys.argv[0]).name
state["calls"].append({"engine": name, "raw": raw, "args": args,
                       "connection_env": [k for k in os.environ
                           if k.startswith("DOCKER_") or k.startswith("CONTAINER_")]})
statefile.write_text(json.dumps(state))
if state.get("delay") and args[:1] == ["ps"]: time.sleep(state["delay"])
if state.get("fail") == args[0]:
    print("private setup_token=never-print-this", file=sys.stderr)
    sys.exit(1)
if args[:2] == ["context", "inspect"]:
    print(json.dumps([{"Endpoints": {"docker": {"Host": state.get("docker_endpoint", "unix:///fake/docker.sock")}}}]))
elif args[:3] == ["system", "connection", "list"]:
    print(json.dumps(state.get("connections", [])))
elif args[0] == "info":
    if name in state.get("unhealthy", []): sys.exit(1)
    print(json.dumps({"OSType": "linux"} if name == "docker" else {"host": {"os": "linux"}}))
elif args[0] == "ps": print("\n".join(state["containers"]))
elif args[:2] == ["volume", "ls"]: print("\n".join(state["volumes"]))
elif args[:2] == ["volume", "inspect"]: print(json.dumps([state["volumes"][args[-1]]]))
elif args[0] == "inspect": print(json.dumps([state["containers"][args[-1]]]))
elif args[:2] == ["volume", "create"]:
    label = args[args.index("--label") + 1].split("=", 1)
    state["volumes"][args[-1]] = {"Labels": dict([label]), "payload": "synthetic-data-preserve"}
elif args[0] == "create":
    label = args[args.index("--label") + 1].split("=", 1)
    container_name = args[args.index("--name") + 1]
    mount = args[args.index("--mount") + 1].split(",src=", 1)[1].split(",", 1)[0]
    port = args[args.index("--publish") + 1].split(":")[1]
    state["containers"][container_name] = {
        "Image": "sha256:" + "a" * 64,
        "Config": {"Labels": dict([label]), "Image": args[-1],
                   "Env": [args[i + 1] for i, arg in enumerate(args) if arg == "--env"]},
        "Mounts": [{"Name": mount, "Destination": "/var/data"}],
        "HostConfig": {"PortBindings": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": port}]}},
        "State": {"Running": False, "Status": "created", "Health": {"Status": "starting"}}}
elif args[0] == "start":
    state["containers"][args[-1]]["State"] = {"Running": True, "Status": "running",
                                             "Health": {"Status": state.get("health", "healthy")}}
elif args[0] == "stop": state["containers"][args[-1]]["State"]["Running"] = False
elif args[0] == "pull": pass
elif args[0] == "run":
    if "-i" in args:
        import hashlib
        state["stdin_digest"] = hashlib.sha256(sys.stdin.buffer.read()).hexdigest()
    if state.get("restore_failure"): sys.exit(1)
    state["restore_count"] = state.get("restore_count", 0) + 1
elif args[0] == "logs": print("private setup_token=never-print-this")
else: sys.exit(2)
statefile.write_text(json.dumps(state))
"""


@pytest.fixture
def fake(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("docker", "podman"):
        executable = bin_dir / name
        executable.write_text(f"#!{os.path.realpath(sys.executable)}\n" + FAKE)
        executable.chmod(0o700)
    state = tmp_path / "engine.json"
    state.write_text(
        json.dumps({"calls": [], "containers": {}, "volumes": {}, "unhealthy": ["podman"]})
    )
    monkeypatch.setenv("FAKE_ENGINE_STATE", str(state))
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    for key in list(os.environ):
        if key.startswith("DOCKER_") or key.startswith("CONTAINER_"):
            monkeypatch.delenv(key)
    monkeypatch.setattr(installer, "check_port", lambda port: None)
    monkeypatch.setattr(installer, "check_host", lambda: None)
    return tmp_path / "installation", tmp_path / "commands", state


def arguments(fake, *extra):
    install_dir, commands, _ = fake
    return ["--install-dir", str(install_dir), "--command-dir", str(commands), *extra]


def read_state(fake):
    return json.loads(fake[2].read_text())


def update_state(fake, **changes):
    state = read_state(fake)
    state.update(changes)
    fake[2].write_text(json.dumps(state))


def installed(fake):
    assert installer.main(arguments(fake, "--image", "registry.invalid/pipeline:1.2.3")) == 0
    return load_manifest(fake[0] / "installation.json")


@pytest.mark.parametrize(
    "image",
    ["pipeline", "pipeline:latest", "pipeline:local", "--help", "a:b;touch", "a@sha256:123"],
)
def test_rejects_implicit_or_unsafe_image(image):
    with pytest.raises(Failure):
        validate_image(image)


def test_first_install_creates_owned_loopback_volume_and_command(fake, capsys):
    manifest = installed(fake)
    state = read_state(fake)
    commands = [call["args"] for call in state["calls"]]
    create = next(command for command in commands if command[0] == "create")
    assert create[create.index("--env") + 1] == "PIPELINE_ORIGIN=http://localhost:8080"
    assert create[create.index("--publish") + 1] == "127.0.0.1:8080:8080"
    assert create[create.index("--health-cmd") + 1] == "python -m internship_pipeline.healthcheck"
    assert create[-1] == manifest.image
    assert {"--read-only", "--init", "--tmpfs"} <= set(create)
    assert fake[0].joinpath("installation.json").stat().st_mode & 0o777 == 0o600
    command = fake[1] / "internship-pipeline"
    assert command.is_symlink()
    assert (fake[0] / "command/LICENSE").read_text() == (DEPLOY.parent / "LICENSE").read_text()
    help_run = subprocess.run([str(command), "--help"], text=True, capture_output=True)
    assert help_run.returncode == 0, help_run.stderr
    status_run = subprocess.run([str(command), "status"], text=True, capture_output=True)
    assert status_run.returncode == 0, status_run.stderr
    assert manifest.url in status_run.stdout
    stop_run = subprocess.run([str(command), "stop"], text=True, capture_output=True)
    assert stop_run.returncode == 0, stop_run.stderr
    assert manifest.volume_name in read_state(fake)["volumes"]
    start_run = subprocess.run([str(command), "start"], text=True, capture_output=True)
    assert start_run.returncode == 0, start_run.stderr
    assert manifest.url in capsys.readouterr().out


def test_rerun_preserves_exact_data_image_and_resources(fake):
    manifest = installed(fake)
    before = read_state(fake)
    before["containers"][manifest.container_name]["State"]["Running"] = False
    before["calls"] = []
    fake[2].write_text(json.dumps(before))
    assert installer.main(arguments(fake)) == 0
    after = read_state(fake)
    assert after["volumes"] == before["volumes"]
    assert after["containers"].keys() == before["containers"].keys()
    assert not any(
        call["args"][0] in {"pull", "create", "volume"}
        and (call["args"][0] != "volume" or call["args"][1] == "create")
        for call in after["calls"]
    )
    assert (fake[0] / "installation.json").read_text().find(manifest.install_id) >= 0


def test_release_default_is_used_fresh_and_never_upgrades_saved_installation(fake):
    image = "ghcr.io/example/pipeline@sha256:" + "b" * 64
    assert installer.main(arguments(fake, "--default-image", image)) == 0
    manifest = load_manifest(fake[0] / "installation.json")
    assert manifest.image == image
    before = read_state(fake)
    update_state(fake, calls=[])
    newer = "ghcr.io/example/pipeline@sha256:" + "c" * 64
    assert installer.main(arguments(fake, "--default-image", newer)) == 0
    assert load_manifest(fake[0] / "installation.json") == manifest
    after = read_state(fake)
    assert after["volumes"] == before["volumes"]
    assert after["containers"] == before["containers"]
    assert not any(call["args"][0] in {"pull", "create"} for call in after["calls"])


def test_explicit_and_default_images_are_mutually_exclusive(fake):
    with pytest.raises(SystemExit) as exc:
        installer.main(
            arguments(
                fake,
                "--image",
                "registry.invalid/pipeline:1.2.3",
                "--default-image",
                "registry.invalid/pipeline:2.0.0",
            )
        )
    assert exc.value.code == 2
    assert read_state(fake)["calls"] == []


@pytest.mark.parametrize(
    "option,value", [("--image", "pipeline:2.0.0"), ("--runtime", "podman"), ("--port", "8081")]
)
def test_rerun_refuses_changes(fake, option, value):
    installed(fake)
    update_state(fake, calls=[])
    assert installer.main(arguments(fake, option, value)) == 1
    assert read_state(fake)["calls"] == []


def test_multiple_healthy_engines_need_choice_and_do_not_mutate(fake, capsys):
    update_state(fake, unhealthy=[])
    assert installer.main(arguments(fake, "--image", "pipeline:1.0.0")) == 1
    assert "Several healthy" in capsys.readouterr().err
    assert not (fake[0] / "installation.json").exists()
    assert read_state(fake)["volumes"] == {}
    assert installer.main(arguments(fake, "--image", "pipeline:1.0.0", "--runtime", "podman")) == 0
    assert all(
        call["raw"][0] == "--remote=false"
        for call in read_state(fake)["calls"]
        if call["engine"] == "podman" and call["args"][0] != "system"
    )


def test_no_healthy_engine_guides_without_privileged_install(fake, capsys):
    update_state(fake, unhealthy=["docker", "podman"])
    assert installer.main(arguments(fake, "--image", "pipeline:1.0.0")) == 1
    assert "Install or start" in capsys.readouterr().err
    assert read_state(fake)["containers"] == {}


def test_unowned_volume_or_container_is_never_started(fake, capsys):
    manifest = installed(fake)
    state = read_state(fake)
    state["volumes"][manifest.volume_name]["Labels"] = {}
    state["calls"] = []
    fake[2].write_text(json.dumps(state))
    assert installer.main(arguments(fake)) == 1
    assert "ownership" in capsys.readouterr().err
    assert not any(
        call["args"][0] in {"start", "create", "pull"} for call in read_state(fake)["calls"]
    )


def test_missing_created_volume_refuses_empty_replacement(fake):
    installed(fake)
    update_state(fake, volumes={}, containers={}, calls=[])
    assert installer.main(arguments(fake)) == 1
    assert read_state(fake)["volumes"] == {}


def test_failed_volume_creation_resumes_with_same_manifest(fake):
    update_state(fake, fail="volume")
    assert installer.main(arguments(fake, "--image", "pipeline:1.0.0")) == 1
    manifest = load_manifest(fake[0] / "installation.json")
    update_state(fake, fail="")
    assert installer.main(arguments(fake)) == 0
    assert load_manifest(fake[0] / "installation.json") == manifest


def test_failed_pull_retains_volume_and_suppresses_private_engine_output(fake, capsys):
    update_state(fake, fail="pull")
    assert installer.main(arguments(fake, "--image", "pipeline:1.0.0")) == 1
    manifest = load_manifest(fake[0] / "installation.json")
    assert manifest.volume_name in read_state(fake)["volumes"]
    assert "never-print-this" not in str(capsys.readouterr())
    update_state(fake, fail="")
    assert installer.main(arguments(fake)) == 0


def test_readiness_deadline_caps_slow_engine_and_preserves_data(fake):
    manifest = installed(fake)
    update_state(fake, delay=3, health="starting")
    started = time.monotonic()
    from pipeline_runtime import wait_ready

    with pytest.raises(Failure):
        wait_ready(Runtime(manifest.runtime), manifest, timeout=0.15)
    assert time.monotonic() - started < 1.5
    assert manifest.volume_name in read_state(fake)["volumes"]


def test_stable_docker_endpoint_ignores_changed_environment(fake, monkeypatch):
    manifest = installed(fake)
    update_state(fake, calls=[])
    monkeypatch.setenv("DOCKER_HOST", "tcp://unrelated.invalid:2375")
    monkeypatch.setenv("DOCKER_CONTEXT", "unrelated")
    assert installer.main(arguments(fake)) == 0
    for call in read_state(fake)["calls"]:
        assert call["raw"][:2] == ["--host", manifest.runtime.endpoint]
        assert call["connection_env"] == []


def test_refuses_remote_engine_and_existing_unrelated_command(fake):
    update_state(fake, docker_endpoint="tcp://remote.invalid:2375")
    assert installer.main(arguments(fake, "--image", "pipeline:1.0.0", "--runtime", "docker")) == 1
    assert read_state(fake)["volumes"] == {}
    fake[1].joinpath("internship-pipeline").write_text("unrelated")
    assert installer.main(arguments(fake, "--image", "pipeline:1.0.0")) == 1
    assert fake[1].joinpath("internship-pipeline").read_text() == "unrelated"


def test_occupied_port_is_rejected():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind(("127.0.0.1", 0))
        except PermissionError:
            pytest.skip("sandbox denies loopback bind; fake runtime tests remain independent")
        with pytest.raises(Failure, match="unavailable"):
            installer.check_port(listener.getsockname()[1])


def test_simulated_port_collision_checks_exact_loopback(monkeypatch):
    observed = []

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def bind(self, address):
            observed.append(address)
            raise OSError("address in use")

    monkeypatch.setattr(installer.socket, "socket", lambda *_args: Socket())
    with pytest.raises(Failure, match="unavailable"):
        installer.check_port(18080)
    assert observed == [("127.0.0.1", 18080)]
    for port in (0, 80, 65536):
        with pytest.raises(Failure, match="unprivileged"):
            installer.check_port(port)
    assert len(observed) == 1


def test_incomplete_shell_bundle_fails_before_runtime(fake):
    shell = fake[0].parent / "isolated-install.sh"
    shell.write_text((DEPLOY / "install.sh").read_text())
    result = subprocess.run(
        ["sh", str(shell), "--image", "pipeline:1.0.0"], capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "complete reviewed local deploy bundle" in result.stderr
    assert read_state(fake)["calls"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 2),
        ("install_id", 17),
        ("origin", "http://public.invalid"),
        ("port", "8080"),
    ],
)
def test_invalid_manifests_fail_without_engine_mutation(fake, field, value):
    installed(fake)
    path = fake[0] / "installation.json"
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))
    update_state(fake, calls=[])
    assert installer.main(arguments(fake)) == 1
    assert read_state(fake)["calls"] == []


@pytest.mark.parametrize("change", ["labels", "image", "mount", "port", "malformed"])
def test_changed_container_contract_fails_before_mutation(fake, change):
    manifest = installed(fake)
    state = read_state(fake)
    container = state["containers"][manifest.container_name]
    if change == "labels":
        container["Config"]["Labels"] = {}
    elif change == "image":
        container["Config"]["Image"] = "unrelated:9.0.0"
    elif change == "mount":
        container["Mounts"][0]["Name"] = "unrelated-data"
    elif change == "port":
        container["HostConfig"]["PortBindings"]["8080/tcp"][0]["HostIp"] = "0.0.0.0"
    else:
        container["Config"] = "malformed"
    state["calls"] = []
    fake[2].write_text(json.dumps(state))
    assert installer.main(arguments(fake)) == 1
    assert not any(
        call["args"][0] in {"start", "create", "pull", "stop"} for call in read_state(fake)["calls"]
    )


def test_manifest_symlink_and_foreign_directory_are_refused(fake):
    fake[0].mkdir()
    unrelated = fake[0].parent / "unrelated.json"
    unrelated.write_text("{}")
    fake[0].joinpath("installation.json").symlink_to(unrelated)
    assert installer.main(arguments(fake)) == 1
    assert unrelated.read_text() == "{}"
    assert read_state(fake)["calls"] == []


def test_podman_machine_snapshots_identity_and_loopback_endpoint(fake):
    update_state(
        fake,
        unhealthy=[],
        connections=[
            {
                "Name": "local-machine",
                "Default": True,
                "URI": "ssh://user@127.0.0.1:53210/run/user/1000/podman/podman.sock",
                "Identity": "/private/synthetic-machine-key",
            }
        ],
    )
    assert installer.main(arguments(fake, "--image", "pipeline:1.0.0", "--runtime", "podman")) == 0
    manifest = load_manifest(fake[0] / "installation.json")
    assert manifest.runtime.identity == "/private/synthetic-machine-key"
    calls = [call for call in read_state(fake)["calls"] if call["args"][0] != "system"]
    assert all(
        call["raw"][:4]
        == ["--url", manifest.runtime.endpoint, "--identity", manifest.runtime.identity]
        for call in calls
    )


def test_no_image_is_defaulted_and_retry_remains_possible(fake):
    assert installer.main(arguments(fake)) == 1
    assert read_state(fake)["calls"] == []
    assert not (fake[0] / "installation.json").exists()
    assert installer.main(arguments(fake, "--image", "pipeline:1.0.0")) == 0


@pytest.mark.parametrize("system,machine", [("Windows", "AMD64"), ("Linux", "riscv64")])
def test_unsupported_hosts_fail_before_runtime(system, machine, monkeypatch):
    monkeypatch.setattr(installer.platform, "system", lambda: system)
    monkeypatch.setattr(installer.platform, "machine", lambda: machine)
    with pytest.raises(Failure):
        installer.check_host()


def recovery_arguments(fake, *extra):
    return [
        "--install-dir",
        str(fake[0].parent / "recovered"),
        "--command-dir",
        str(fake[0].parent / "recovered-commands"),
        "--port",
        "18080",
        *extra,
    ]


def prepare_recovery(fake):
    source = installed(fake)
    state = read_state(fake)
    state["containers"][source.container_name]["State"]["Running"] = False
    state["calls"] = []
    fake[2].write_text(json.dumps(state))
    backup = fake[0].parent / "private backup $(literal)"
    backup.mkdir(mode=0o700)
    (backup / "manifest.json").write_text('{"format": 1, "files": {}}')
    (backup / "manifest.json").chmod(0o600)
    return source, backup


def restore_arguments(fake, backup, *extra):
    return recovery_arguments(
        fake, "--restore-source", str(fake[0]), "--restore-from", str(backup), *extra
    )


def test_fresh_restore_registers_exact_image_data_root_and_retains_source(fake):
    source, backup = prepare_recovery(fake)
    before = read_state(fake)
    assert installer.main(restore_arguments(fake, backup)) == 0
    root = fake[0].parent / "recovered"
    destination = load_manifest(root / "installation.json")
    after = read_state(fake)
    assert destination.data_dir == "/var/data/restored"
    assert destination.image == "sha256:" + "a" * 64
    assert destination.runtime == source.runtime
    assert destination.install_id != source.install_id
    assert after["volumes"][source.volume_name] == before["volumes"][source.volume_name]
    assert after["containers"][source.container_name] == before["containers"][source.container_name]
    commands = [entry["args"] for entry in after["calls"]]
    restore = next(command for command in commands if command[0] == "run")
    assert restore[-4] == destination.image
    assert restore[-3] == "-c"
    assert "type=bind" not in ",".join(restore)
    assert "-i" in restore
    assert after["stdin_digest"]
    assert (root / ".backup-manifest.sha256").read_text().strip() == restore[-1]
    assert restore[restore.index("--network") + 1] == "none"
    assert restore[restore.index("--pull") + 1] == "never"
    create = next(command for command in commands if command[0] == "create")
    assert create[-1] == destination.image
    assert "PIPELINE_DATA_DIR=/var/data/restored" in create
    assert not any(command[0] in {"pull", "stop"} for command in commands)
    assert (root / ".restore-completed").read_text().strip() == destination.install_id
    command = fake[0].parent / "recovered-commands/internship-pipeline"
    for operation in ("status", "stop", "start"):
        result = subprocess.run([str(command), operation], text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
    update_state(fake, calls=[])
    assert installer.main(recovery_arguments(fake)) == 0
    assert read_state(fake)["restore_count"] == 1


def test_release_default_preserves_inspected_restore_and_saved_recovery_image(fake):
    _, backup = prepare_recovery(fake)
    release = "ghcr.io/example/pipeline@sha256:" + "b" * 64
    assert installer.main(restore_arguments(fake, backup, "--default-image", release)) == 0
    root = fake[0].parent / "recovered"
    destination = load_manifest(root / "installation.json")
    assert destination.image == "sha256:" + "a" * 64
    assert installer.main(recovery_arguments(fake, "--default-image", release)) == 0
    assert load_manifest(root / "installation.json") == destination
    assert read_state(fake)["restore_count"] == 1
    assert not any(call["args"][0] == "pull" for call in read_state(fake)["calls"])


@pytest.mark.parametrize("change", ["running", "volume", "owner", "image", "port", "backup"])
def test_unsafe_restore_source_refused_before_destination_resources(fake, change):
    source, backup = prepare_recovery(fake)
    state = read_state(fake)
    extra = []
    if change == "running":
        state["containers"][source.container_name]["State"]["Running"] = True
    elif change == "volume":
        state["volumes"] = {}
    elif change == "owner":
        state["volumes"][source.volume_name]["Labels"] = {}
    elif change == "image":
        state["containers"][source.container_name]["Image"] = "not-an-exact-image"
    elif change == "port":
        extra = ["--port", "8080"]
    elif change == "backup":
        backup.chmod(0o755)
    fake[2].write_text(json.dumps(state))
    assert installer.main(restore_arguments(fake, backup, *extra)) == 1
    assert not (fake[0].parent / "recovered/installation.json").exists()
    assert not any(
        call["args"][0] in {"run", "create", "start", "pull"}
        or call["args"][:2] == ["volume", "create"]
        for call in read_state(fake)["calls"]
    )


def test_interrupted_restore_never_starts_partial_destination_or_repeats(fake, capsys):
    source, backup = prepare_recovery(fake)
    update_state(fake, restore_failure=True)
    assert installer.main(restore_arguments(fake, backup)) == 1
    root = fake[0].parent / "recovered"
    destination = load_manifest(root / "installation.json")
    assert (root / ".restore-started").is_file()
    assert not (root / ".restore-completed").exists()
    assert destination.container_name not in read_state(fake)["containers"]
    assert source.volume_name in read_state(fake)["volumes"]
    update_state(fake, restore_failure=False, calls=[])
    assert installer.main(restore_arguments(fake, backup)) == 1
    assert "completion is unconfirmed" in capsys.readouterr().err
    assert not any(
        call["args"][0] in {"run", "create", "start", "pull"} for call in read_state(fake)["calls"]
    )
    command = fake[0].parent / "recovered-commands/internship-pipeline"
    result = subprocess.run([str(command), "start"], text=True, capture_output=True)
    assert result.returncode == 1
    assert "completion is unconfirmed" in result.stderr


def test_completed_restore_resumes_failed_create_without_repeating_restore(fake):
    _, backup = prepare_recovery(fake)
    update_state(fake, fail="create")
    assert installer.main(restore_arguments(fake, backup)) == 1
    assert read_state(fake)["restore_count"] == 1
    update_state(fake, fail="", calls=[])
    assert installer.main(recovery_arguments(fake)) == 0
    assert read_state(fake)["restore_count"] == 1
    assert not any(call["args"][0] in {"run", "pull"} for call in read_state(fake)["calls"])


def test_bare_podman_image_identity_is_normalized_for_exact_restore(fake):
    source, backup = prepare_recovery(fake)
    state = read_state(fake)
    state["containers"][source.container_name]["Image"] = "a" * 64
    fake[2].write_text(json.dumps(state))
    assert installer.main(restore_arguments(fake, backup)) == 0
    destination = load_manifest(fake[0].parent / "recovered/installation.json")
    assert destination.image == "sha256:" + "a" * 64


@pytest.mark.parametrize("destination", ["source", "inside-source", "inside-backup"])
def test_restore_destination_must_be_independent(fake, destination):
    _, backup = prepare_recovery(fake)
    root = {
        "source": fake[0],
        "inside-source": fake[0] / "nested",
        "inside-backup": backup / "nested",
    }[destination]
    assert installer.main(restore_arguments(fake, backup, "--install-dir", str(root))) == 1
    assert not any(
        call["args"][0] in {"run", "create", "start"} for call in read_state(fake)["calls"]
    )


def test_missing_source_and_unpaired_restore_flags_do_not_create_source(fake):
    backup = fake[0].parent / "backup"
    backup.mkdir(mode=0o700)
    assert installer.main(restore_arguments(fake, backup)) == 1
    assert not fake[0].exists()
    assert installer.main(recovery_arguments(fake, "--restore-from", str(backup))) == 1
    assert read_state(fake)["calls"] == []


@pytest.mark.parametrize("data_dir", [None, "/var/data/other", "/tmp", 17])
def test_missing_or_unsupported_data_root_manifest_refused(fake, data_dir):
    installed(fake)
    path = fake[0] / "installation.json"
    data = json.loads(path.read_text())
    if data_dir is None:
        del data["data_dir"]
    else:
        data["data_dir"] = data_dir
    path.write_text(json.dumps(data))
    update_state(fake, calls=[])
    assert installer.main(arguments(fake)) == 1
    assert read_state(fake)["calls"] == []
