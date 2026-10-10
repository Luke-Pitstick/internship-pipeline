"""Host commands against synthetic engines and the real owner API; never start an engine."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import warnings
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from internship_pipeline.app import create_app
from internship_pipeline.identity import Identity
from internship_pipeline.storage import Store, enqueue

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


def module(name: str):
    spec = importlib.util.spec_from_file_location(name, DEPLOY / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


runtime_module = module("pipeline_runtime")
management = module("pipeline_management")

ENGINE = r"""#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
root = Path(__file__).parent
args = sys.argv[1:]
with (root / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps({"argv": args, "connection_env": {
        k: v for k, v in os.environ.items()
        if k.startswith("DOCKER_") or k in {"CONTAINER_HOST", "CONTAINER_CONNECTION"}
    }}) + "\n")
if args[:1] in [["--host"], ["--url"]]:
    args = args[2:]
state_path = root / "engine.json"
state = json.loads(state_path.read_text())
if state.get("delay"):
    time.sleep(state["delay"])
if state.get("fail"):
    print("Owner setup token: must-not-print", file=sys.stderr)
    sys.exit(1)
command = args[0]
if command == "info":
    result = json.dumps({"OSType": "linux", "host": {"os": "linux"}})
elif command == "ps":
    result = state["container_name"] if state.get("container") else ""
elif args[:2] == ["volume", "ls"]:
    result = state["volume_name"] if state.get("volume") else ""
elif args[:2] == ["volume", "inspect"]:
    result = json.dumps([state["volume"]])
elif command == "inspect":
    result = json.dumps([state["container"]])
elif command in {"start", "stop"}:
    state["container"]["State"]["Running"] = command == "start"
    state["container"]["State"]["Health"]["Status"] = state.get("health", "healthy")
    state_path.write_text(json.dumps(state))
    result = state["container_name"]
elif command == "exec":
    result = state.get("browser_url", args[-1] + "/#setup=" + "s" * 43)
elif command == "logs":
    result = state.get("logs", "")
    print(state.get("stderr_logs", ""), file=sys.stderr, end="")
elif command == "run":
    result = "maintenance completed"
else:
    raise SystemExit("unexpected operation")
print(result)
"""


@pytest.fixture(params=["docker", "podman"])
def installed(tmp_path, request):
    engine_dir = tmp_path / "engine path $(touch SHOULD_NOT_EXIST)"
    engine_dir.mkdir()
    executable = engine_dir / request.param
    executable.write_text(
        "#!" + os.path.realpath(sys.executable) + "\n" + ENGINE.partition("\n")[2]
    )
    executable.chmod(0o700)
    installation = tmp_path / "installation"
    installation.mkdir(mode=0o700)
    install_id = str(uuid4())
    name = "internship-pipeline-" + install_id
    manifest = runtime_module.Manifest(
        1,
        install_id,
        runtime_module.RuntimeSpec(
            request.param, str(executable), "unix:///tmp/runtime $(touch SHOULD_NOT_EXIST).sock"
        ),
        name,
        name + "-data",
        "synthetic/pipeline:0.1.0",
        8080,
        "http://localhost:8080",
        "http://localhost:8080",
        "/var/data",
    )
    runtime_module.write_manifest(installation / "installation.json", manifest)
    state = {
        "container_name": name,
        "volume_name": manifest.volume_name,
        "volume": {"Labels": {runtime_module.LABEL: install_id}},
        "container": {
            "Image": "sha256:" + "a" * 64,
            "Config": {
                "Labels": {runtime_module.LABEL: install_id},
                "Image": manifest.image,
                "Env": [
                    "PIPELINE_DATA_DIR=/var/data",
                    "PIPELINE_CONFIG=/var/data/config/settings.yaml",
                ],
            },
            "Mounts": [{"Destination": "/var/data", "Name": manifest.volume_name}],
            "HostConfig": {
                "PortBindings": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]}
            },
            "State": {"Running": False, "Health": {"Status": "healthy"}},
        },
    }
    (engine_dir / "engine.json").write_text(json.dumps(state))
    return installation, manifest, engine_dir


def calls(engine_dir):
    path = engine_dir / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def alter(engine_dir, mutate):
    path = engine_dir / "engine.json"
    state = json.loads(path.read_text())
    mutate(state)
    path.write_text(json.dumps(state))


def run(installation, *args):
    return management.main(["--install-dir", str(installation), *args])


def test_data_preserving_lifecycle_literal_argv_and_frozen_runtime(installed, monkeypatch, capsys):
    installation, manifest, engine_dir = installed
    monkeypatch.setenv("DOCKER_CONTEXT", "unrelated-global-context")
    monkeypatch.setenv("DOCKER_HOST", "tcp://unrelated-host:2375")
    monkeypatch.setenv("CONTAINER_CONNECTION", "unrelated-machine")
    assert run(installation, "start", "--wait", "2") == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True
    assert run(installation, "start", "--wait", "2") == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True
    assert run(installation, "status") == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True
    assert run(installation, "stop") == 0
    assert json.loads(capsys.readouterr().out)["volume_preserved"] is True
    assert run(installation, "stop") == 0
    operations = [x["argv"][2:] for x in calls(engine_dir)]
    assert sum(x[0] == "start" for x in operations) == 1
    assert sum(x[0] == "stop" for x in operations) == 1
    assert {x[0] for x in operations} <= {"info", "ps", "volume", "inspect", "start", "stop"}
    assert ["stop", "--time", "30", manifest.container_name] in operations
    assert all(x["argv"][1] == manifest.runtime.endpoint for x in calls(engine_dir))
    assert all(x["connection_env"] == {} for x in calls(engine_dir))
    assert os.environ["DOCKER_CONTEXT"] == "unrelated-global-context"
    assert not (Path.cwd() / "SHOULD_NOT_EXIST").exists()


@pytest.mark.parametrize("change", ["container", "volume", "image", "mount", "port"])
def test_mismatched_resources_are_never_mutated(installed, change, capsys):
    installation, _, engine_dir = installed

    def mutate(state):
        if change == "container":
            state["container"]["Config"]["Labels"][runtime_module.LABEL] = str(uuid4())
        elif change == "volume":
            state["volume"]["Labels"][runtime_module.LABEL] = str(uuid4())
        elif change == "image":
            state["container"]["Config"]["Image"] = "other:1"
        elif change == "mount":
            state["container"]["Mounts"][0]["Name"] = "other-data"
        else:
            state["container"]["HostConfig"]["PortBindings"]["8080/tcp"][0]["HostIp"] = "0.0.0.0"

    alter(engine_dir, mutate)
    assert run(installation, "start") == 1
    assert "untouched" in capsys.readouterr().err
    assert all(x["argv"][2] not in {"start", "stop", "run", "rm"} for x in calls(engine_dir))


@pytest.mark.parametrize("missing", ["volume", "container"])
def test_missing_resources_refuse_duplicate_instance(installed, missing, capsys):
    installation, _, engine_dir = installed
    alter(engine_dir, lambda state: state.update({missing: None}))
    assert run(installation, "start") == 1
    assert "missing" in capsys.readouterr().err
    assert all(x["argv"][2] not in {"start", "run", "create"} for x in calls(engine_dir))


def test_url_and_help_work_without_runtime_and_symlink_entrypoint(installed, tmp_path, capsys):
    installation, manifest, engine_dir = installed
    alter(engine_dir, lambda state: state.update(fail=True))
    assert run(installation, "show-url") == 0
    assert capsys.readouterr().out.strip() == manifest.url
    assert calls(engine_dir) == []
    wrapper = tmp_path / "internship-pipeline"
    wrapper.symlink_to(DEPLOY / "internship-pipeline")
    result = subprocess.run(
        [sys.executable, str(wrapper), "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0 and "start" in result.stdout and "diagnostics" in result.stdout
    assert calls(engine_dir) == []


def test_missing_manifest_and_engine_errors_are_actionable_without_private_output(
    installed, tmp_path, capsys
):
    installation, _, engine_dir = installed
    assert run(tmp_path / "missing", "status") == 1
    assert "installer" in capsys.readouterr().err
    assert calls(engine_dir) == []
    alter(engine_dir, lambda state: state.update(fail=True))
    assert run(installation, "status") == 1
    output = capsys.readouterr()
    assert "saved runtime" in output.err and "must-not-print" not in output.err + output.out


def test_runtime_logs_omit_secrets_and_arbitrary_exceptions(installed, capsys):
    installation, _, engine_dir = installed
    alter(
        engine_dir,
        lambda state: state.update(
            logs=(
                "Owner setup token: synthetic-secret\nBearer synthetic-secret\n"
                "Worker collector exited unexpectedly: 1\n"
                "Worker matcher could not start: OSError\n"
                "Worker private-token exited unexpectedly: 2\n"
                "Traceback private/resume.pdf synthetic-secret"
            )
        ),
    )
    assert run(installation, "logs", "--lines", "20") == 0
    output = capsys.readouterr().out
    assert "secret" not in output and "resume" not in output and "private-token" not in output
    data = json.loads(output)
    assert len(data["events"]) == 2 and data["omitted_lines"] == 4
    assert calls(engine_dir)[-1]["argv"][2:4] == ["logs", "--tail"]


def test_runtime_stderr_lifecycle_events_are_preserved_and_sanitized(installed, capsys):
    installation, _, engine_dir = installed
    alter(
        engine_dir,
        lambda state: state.update(
            logs="Worker collector exited unexpectedly: 1\nOwner setup token: stdout-secret",
            stderr_logs="Worker matcher could not start: OSError\nBearer stderr-secret\n",
        ),
    )
    assert run(installation, "logs") == 0
    output = capsys.readouterr()
    assert "secret" not in output.out + output.err
    summary = json.loads(output.out)
    assert summary["events"] == [
        {"event": "worker_exited", "role": "collector", "exit_code": 1},
        {"event": "worker_start_failed", "role": "matcher"},
    ]
    assert summary["omitted_lines"] == 2


@pytest.mark.parametrize("command", ["setup-token", "recover-owner"])
def test_offline_recovery_exact_image_volume_saved_endpoint(
    installed, monkeypatch, capsys, command
):
    installation, manifest, engine_dir = installed
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    assert run(installation, command) == 0
    capsys.readouterr()
    operation = calls(engine_dir)[-1]["argv"]
    assert (
        operation
        == runtime_module.Runtime(manifest.runtime).argv(
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "-it",
            "--entrypoint",
            "internship-pipeline",
            "--mount",
            f"type=volume,src={manifest.volume_name},dst=/var/data",
            "sha256:" + "a" * 64,
            command,
            "--data-dir",
            "/var/data",
        )[1:]
    )
    assert all(entry["connection_env"] == {} for entry in calls(engine_dir))
    alter(engine_dir, lambda state: state["container"]["State"].update(Running=True))
    before = len(calls(engine_dir))
    assert run(installation, command) == 1
    assert "Stop" in capsys.readouterr().err
    assert all(entry["argv"][2] != "run" for entry in calls(engine_dir)[before:])


def test_json_runtime_output_ignores_bounded_stderr_and_rejects_combined_overflow(
    installed, monkeypatch
):
    _, manifest, _ = installed
    runtime = runtime_module.Runtime(manifest.runtime)
    monkeypatch.setattr(
        runtime_module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, '{"OSType":"linux"}', "notice"),
    )
    runtime.check()
    monkeypatch.setattr(
        runtime_module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 0, "x" * 1024**2, "y" * (1024**2 + 1)
        ),
    )
    with pytest.raises(runtime_module.Failure, match="inspection limit"):
        runtime.run("logs", include_stderr=True)


@pytest.mark.parametrize("command", ["setup-token", "recover-owner"])
def test_offline_recovery_noninteractive_refusal_preserves_volume(installed, capsys, command):
    installation, _, engine_dir = installed
    assert run(installation, command) == 1
    assert "private interactive terminal" in capsys.readouterr().err
    assert all(entry["argv"][2] != "run" for entry in calls(engine_dir))


def test_restored_data_root_is_required_for_owner_recovery(installed, monkeypatch):
    from dataclasses import replace

    installation, original, engine_dir = installed
    restored = replace(original, data_dir="/var/data/restored")
    (installation / "installation.json").unlink()
    runtime_module.write_manifest(installation / "installation.json", restored)
    marker = installation / ".restore-completed"
    marker.write_text(restored.install_id + "\n")
    marker.chmod(0o600)
    alter(
        engine_dir,
        lambda state: state["container"]["Config"].update(
            Env=[
                "PIPELINE_DATA_DIR=/var/data/restored",
                "PIPELINE_CONFIG=/var/data/restored/config/settings.yaml",
            ]
        ),
    )
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    assert run(installation, "recover-owner") == 0
    assert calls(engine_dir)[-1]["argv"][-2:] == ["--data-dir", restored.data_dir]
    marker.unlink()
    before = len(calls(engine_dir))
    assert run(installation, "start") == 1
    assert len(calls(engine_dir)) == before


@pytest.mark.parametrize(
    "environment",
    [
        None,
        [],
        ["PIPELINE_DATA_DIR=/var/data/restored"],
        ["PIPELINE_DATA_DIR=/var/data", "PIPELINE_DATA_DIR=/tmp"],
    ],
)
def test_changed_data_root_refuses_lifecycle_mutation(installed, environment):
    installation, _, engine_dir = installed
    if isinstance(environment, list):
        environment = [*environment, "PIPELINE_CONFIG=/var/data/config/settings.yaml"]
    alter(engine_dir, lambda state: state["container"]["Config"].update(Env=environment))
    assert run(installation, "start") == 1
    assert all(entry["argv"][2] not in {"run", "start", "stop"} for entry in calls(engine_dir))


def test_nested_mount_cannot_redirect_data_root(installed):
    installation, _, engine_dir = installed
    alter(
        engine_dir,
        lambda state: state["container"]["Mounts"].append(
            {"Destination": "/var/data/restored", "Name": "unrelated-volume"}
        ),
    )
    assert run(installation, "start") == 1
    assert all(entry["argv"][2] != "start" for entry in calls(engine_dir))


def test_changed_config_cannot_redirect_restored_storage(installed):
    installation, _, engine_dir = installed
    alter(
        engine_dir,
        lambda state: state["container"]["Config"].update(
            Env=["PIPELINE_DATA_DIR=/var/data", "PIPELINE_CONFIG=/tmp/foreign-settings.yaml"]
        ),
    )
    assert run(installation, "start") == 1
    assert all(entry["argv"][2] != "start" for entry in calls(engine_dir))


def test_readiness_deadline_and_runtime_timeout_are_bounded(installed, capsys):
    installation, manifest, engine_dir = installed
    alter(engine_dir, lambda state: state.update(health="starting"))
    started = time.monotonic()
    assert run(installation, "start", "--wait", "1") == 1
    assert time.monotonic() - started < 3
    assert "timed out" in capsys.readouterr().err
    alter(engine_dir, lambda state: state.update(delay=1))
    started = time.monotonic()
    with pytest.raises(runtime_module.Failure, match="could not complete"):
        runtime_module.Runtime(manifest.runtime).run("info", timeout=0.05)
    assert time.monotonic() - started < 0.5


@pytest.mark.parametrize(
    "argument",
    [
        ("start", "--wait", "nan"),
        ("start", "--wait", "121"),
        ("logs", "--lines", "201"),
        ("logs", "--lines", "0"),
    ],
)
def test_invalid_limits_rejected_before_any_runtime_action(installed, argument):
    installation, _, engine_dir = installed
    with pytest.raises(SystemExit) as exc:
        run(installation, *argument)
    assert exc.value.code == 2
    assert calls(engine_dir) == []


def test_manifest_safety_failure_precedes_runtime(installed, capsys):
    installation, _, engine_dir = installed
    path = installation / "installation.json"
    data = json.loads(path.read_text())
    data["container_name"] = "--malicious-option"
    path.write_text(json.dumps(data))
    assert run(installation, "start") == 1
    assert "Invalid installation manifest" in capsys.readouterr().err
    assert calls(engine_dir) == []


def test_diagnostic_summary_cannot_echo_unknown_auth_payloads():
    data = {
        "at": 10**400,
        "token": "synthetic-secret",
        "queue": [{"kind": ["secret"], "status": "secret", "count": 4}],
        "workers": {"roles": ["collector", "synthetic-secret"], "healthy": True},
        "failed": [{"error": "synthetic-secret", "id": 2}],
        "sources": [{"id": "private resume", "error": "synthetic-secret"}],
        "models": [{"operation": {"secret": 1}, "status": "synthetic-secret"}],
    }
    output = json.dumps(management.diagnostic_summary(data))
    assert "synthetic-secret" not in output and "private resume" not in output
    assert "collector" in output and "work_failed_check_settings" in output


@pytest.mark.parametrize("token", [None, ["private-token"], "invalid\r\nprivate-token"])
def test_diagnostics_reject_malformed_session_without_sending_password(token, monkeypatch):
    http = management.DiagnosticsClient("http://localhost:8080")
    requested = []

    def request(path, body=None):
        requested.append(path)
        return {"csrf": token}

    monkeypatch.setattr(http, "request", request)
    with pytest.raises(runtime_module.Failure, match="Unexpected authentication response"):
        http.fetch("owner", "synthetic-password")
    assert requested == ["/api/session"]
    assert http.csrf is None and len(http.cookies) == 0


def test_explicit_diagnostics_use_real_owner_auth_csrf_logout_and_sanitized_data(
    tmp_path, monkeypatch
):
    root = tmp_path / "data"
    root.mkdir()
    identity = Identity(root / "identity.sqlite3")
    identity.claim(identity.setup_token(), "owner", "synthetic-password")
    app = create_app(root, origin="http://localhost:8080")
    with TestClient(app, base_url="http://localhost:8080") as client:
        store = Store(root / "state.sqlite3")
        with store.transaction() as db:
            enqueue(db, "evaluate", "synthetic-failure", {}, time.time())
            db.execute(
                "UPDATE tasks SET status='failed',error='synthetic-secret private/resume.pdf'"
            )
        assert client.get("/api/diagnostics").status_code == 401
        seen = []
        http = management.DiagnosticsClient("http://localhost:8080")

        def open_request(request, *, timeout):
            assert timeout == 5
            headers = dict(request.header_items())
            assert headers["Origin"] == http.origin
            path = request.full_url.removeprefix(http.origin)
            response = client.request(
                request.get_method(), path, content=request.data, headers=headers
            )
            seen.append((path, response.status_code))
            if response.status_code != 200:
                raise urllib.error.HTTPError(
                    request.full_url, response.status_code, "private error", {}, None
                )
            return io.BytesIO(response.content)

        monkeypatch.setattr(http.opener, "open", open_request)
        summary = management.diagnostic_summary(http.fetch("owner", "synthetic-password"))
        assert [path for path, _ in seen] == [
            "/api/session",
            "/api/login",
            "/api/diagnostics",
            "/api/logout",
        ]
        assert all(status == 200 for _, status in seen)
        assert "synthetic-secret" not in json.dumps(summary)
        assert summary["failed"][0]["error"] == "work_failed_check_settings"
        assert client.get("/api/diagnostics").status_code == 401
        assert http.csrf is None and len(http.cookies) == 0


def test_diagnostics_refuse_redirects_and_hide_error_body(monkeypatch):
    http = management.DiagnosticsClient("http://localhost:8080")

    def failed(*args, **kwargs):
        raise urllib.error.HTTPError("http://localhost:8080", 302, "synthetic-secret", {}, None)

    monkeypatch.setattr(http.opener, "open", failed)
    with pytest.raises(runtime_module.Failure) as exc:
        http.request("/api/session")
    assert "synthetic-secret" not in str(exc.value)
    assert management.NoRedirect().redirect_request(None, None, None, None, None, None) is None


def test_diagnostics_do_not_accept_credentials_from_noninteractive_stdin(installed, capsys):
    installation, _, engine_dir = installed
    alter(engine_dir, lambda state: state["container"]["State"].update(Running=True))
    assert run(installation, "status", "--diagnostics") == 1
    assert "interactive terminal" in capsys.readouterr().err


def test_diagnostics_refuse_echoing_password_prompt(installed, monkeypatch, capsys):
    installation, _, engine_dir = installed
    alter(engine_dir, lambda state: state["container"]["State"].update(Running=True))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "owner")

    def insecure_prompt(prompt):
        warnings.warn("Cannot hide password", management.getpass.GetPassWarning, stacklevel=2)
        pytest.fail("Password input must never proceed when echo cannot be suppressed")

    monkeypatch.setattr(management.getpass, "getpass", insecure_prompt)
    assert run(installation, "status", "--diagnostics") == 1
    assert "Secure password prompt unavailable" in capsys.readouterr().err


def test_open_issues_private_setup_link_but_url_stays_offline(installed, monkeypatch, capsys):
    installation, manifest, engine_dir = installed
    opened = []
    monkeypatch.setattr(management.webbrowser, "open", lambda url: opened.append(url) or True)
    assert run(installation, "url") == 0
    assert opened == []
    alter(engine_dir, lambda state: state["container"]["State"].update(Running=True))
    assert run(installation, "open") == 0
    assert opened == [manifest.url + "/#setup=" + "s" * 43]
    assert any("setup-link" in call["argv"] for call in calls(engine_dir))


@pytest.mark.parametrize(
    "url", ["https://foreign.example/#setup=secret", "http://localhost:8080/#setup=short"]
)
def test_open_rejects_invalid_private_link_without_launching(installed, monkeypatch, capsys, url):
    installation, _, engine_dir = installed
    alter(engine_dir, lambda state: state["container"]["State"].update(Running=True))
    alter(engine_dir, lambda state: state.update(browser_url=url))
    opened = []
    monkeypatch.setattr(management.webbrowser, "open", lambda url: opened.append(url) or True)
    assert run(installation, "open") == 1
    output = capsys.readouterr()
    assert "invalid setup link" in output.err
    assert url not in output.out + output.err
    assert opened == []


def test_open_claimed_instance_uses_normal_sign_in_and_prints_link_if_browser_unavailable(
    installed, monkeypatch, capsys
):
    installation, manifest, engine_dir = installed
    alter(engine_dir, lambda state: state["container"]["State"].update(Running=True))
    alter(engine_dir, lambda state: state.update(browser_url=manifest.origin + "/"))
    monkeypatch.setattr(management.webbrowser, "open", lambda url: False)
    assert run(installation, "open") == 0
    output = capsys.readouterr().out
    assert "Browser could not open automatically" in output
    assert manifest.origin + "/" in output
    assert "#setup=" not in output
