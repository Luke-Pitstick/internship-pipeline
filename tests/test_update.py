"""Update transactions use synthetic engines and retain original data across failures."""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
sys.path.insert(0, str(DEPLOY))
import install  # noqa: E402
import pipeline_management as management  # noqa: E402
import pipeline_update as update  # noqa: E402
from pipeline_release import Release  # noqa: E402
from pipeline_runtime import (  # noqa: E402
    LABEL,
    Failure,
    Manifest,
    RuntimeCommandFailure,
    RuntimeSpec,
    atomic_json,
    host_lock,
    load_manifest,
    private_json,
)

OLD_IMAGE = "ghcr.io/luke-pitstick/internship-pipeline@sha256:" + "a" * 64
NEW_IMAGE = "ghcr.io/luke-pitstick/internship-pipeline@sha256:" + "b" * 64
LOCAL_IMAGE = "sha256:" + "c" * 64
RELEASE = Release("v0.1.0-rc.2", "d" * 40, NEW_IMAGE, 1, "e" * 64, "f" * 64, "0" * 64)


class Crash(BaseException):
    pass


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "installation"
    root.mkdir(mode=0o700)
    command = tmp_path / "bin"
    command.mkdir()
    identifier = str(uuid4())
    stem = "internship-pipeline-" + identifier
    source = Manifest(
        1,
        identifier,
        RuntimeSpec("docker", "/synthetic/docker", "unix:///saved.sock"),
        stem,
        stem + "-data",
        OLD_IMAGE,
        18080,
        "http://localhost:18080",
        "http://localhost:18080",
        "/var/data",
    )
    atomic_json(root / "installation.json", asdict(source))
    install.install_command(root, command, identifier)
    state = {
        "containers": {stem: {"Image": LOCAL_IMAGE, "State": {"Running": True}, "mode": "normal"}},
        "volumes": {
            source.volume_name: {
                "jobs": ["synthetic"],
                "credentials": "encrypted",
                "pdf": "synthetic-bytes",
            }
        },
        "calls": [],
        "fail": None,
        "format": 1,
    }

    class Engine:
        def __init__(self, spec):
            assert spec == source.runtime
            self.spec = spec

        def check(self):
            pass

        def browser_url(self, manifest):
            return manifest.url

        def is_ready(self, container):
            return container["State"]["Running"]

        def inspect_volume(self, manifest):
            return state["volumes"].get(manifest.volume_name)

        def inspect_container(self, manifest):
            return state["containers"].get(manifest.container_name)

        def _inspect(self, kind, name):
            return state["containers"].get(name)

        def require_owned(self, manifest, *args, **kwargs):
            assert manifest.volume_name in state["volumes"]
            return state["containers"][manifest.container_name]

        def run(self, *args, **kwargs):
            state["calls"].append(args)
            operation = args[0]
            if operation == "pull":
                if state["fail"] == "pull":
                    raise Failure("Synthetic download failure")
            elif args[:2] == ("volume", "create"):
                state["volumes"][args[-1]] = {}
            elif operation == "start":
                record = state["containers"][args[-1]]
                journal = private_json(root / "update.json")
                previous = load_manifest(root / "updates" / journal["transaction"] / "source.json")
                if args[-1] != previous.container_name and record["mode"] == "normal":
                    assert private_json(root / "update.json")["phase"] in {"activating", "complete"}
                    assert record["restart"] == "unless-stopped"
                    if state["fail"] == "activation":
                        raise Failure("Synthetic activation failure")
                    state["volumes"][record["volume"]]["new-work"] = "must-retain"
                record["State"]["Running"] = True
            elif operation == "stop":
                state["containers"][args[-1]]["State"]["Running"] = False
            elif operation == "rm":
                assert not state["containers"][args[-1]]["State"]["Running"]
                del state["containers"][args[-1]]
            elif operation == "run":
                assert "--network" in args and args[args.index("--network") + 1] == "none"
                assert args[args.index("--pull") + 1] == "never"
                images = [
                    item
                    for item in args
                    if item.startswith("ghcr.io/") or re.fullmatch(r"sha256:[0-9a-f]{64}", item)
                ]
                assert len(images) == 1
                mounts = [args[i + 1] for i, value in enumerate(args) if value == "--mount"]
                if images[0] == NEW_IMAGE:
                    assert not any(f"src={source.volume_name}," in value for value in mounts)
                if "internship_pipeline.storage_format" in args:
                    return json.dumps({"storage_format": state["format"]})
                if any("shutil.disk_usage" in value for value in args):
                    return json.dumps(
                        {"needed": 67108864, "free": 0 if state["fail"] == "space" else 2**30}
                    )
                if "backup" in args:
                    previous = load_manifest(root / "installation.json")
                    assert not state["containers"][previous.container_name]["State"]["Running"]
                    if state["fail"] == "backup" or state.get("crash_backup"):
                        name = args[args.index("--name") + 1]
                        state["containers"][name] = {
                            "Id": "1" * 64,
                            "Config": {"Labels": {LABEL: previous.install_id}, "Image": images[0]},
                            "State": {"Running": True},
                            "Mounts": [
                                {
                                    "Type": "volume",
                                    "Name": mount.split("src=", 1)[1].split(",", 1)[0],
                                    "Destination": mount.split("dst=", 1)[1].split(",", 1)[0],
                                }
                                for mount in mounts
                            ],
                        }
                        if state.get("maintenance_tamper"):
                            state["containers"][name]["Config"]["Labels"][LABEL] = str(uuid4())
                        if state.get("crash_backup"):
                            raise Crash
                        raise Failure("Synthetic backup timeout; receiver remains running")
                    candidate_mount = next(value for value in mounts if "dst=/recovery" in value)
                    candidate = candidate_mount.split("src=", 1)[1].split(",", 1)[0]
                    state["volumes"][candidate] = copy.deepcopy(
                        state["volumes"][previous.volume_name]
                    )
                if "restore" in args and state["fail"] == "restore":
                    raise Failure("Synthetic restore failure")
                if (
                    "internship_pipeline.update_validation" in args
                    and state["fail"] == "validation"
                ):
                    raise Failure("Synthetic data validation failure")
            return ""

    def stage(release, folder):
        bundle = folder / f"internship-pipeline-installer-{release.version}"
        bundle.mkdir(mode=0o700)
        for name in install.BUNDLE_FILES:
            path = DEPLOY.parent / "LICENSE" if name == "LICENSE" else DEPLOY / name
            (bundle / name).write_bytes(path.read_bytes())
            (bundle / name).chmod(0o700 if name == "internship-pipeline" else 0o600)
        return bundle

    def create(engine, manifest, *, validation=False):
        journal = private_json(root / "update.json")
        previous = load_manifest(root / "updates" / journal["transaction"] / "source.json")
        assert (
            previous.container_name not in state["containers"]
            or not state["containers"][previous.container_name]["State"]["Running"]
        )
        state["containers"][manifest.container_name] = {
            "Image": "sha256:" + "b" * 64,
            "State": {"Running": False},
            "mode": "validation" if validation else "normal",
            "volume": manifest.volume_name,
            "restart": "no" if validation else "unless-stopped",
            "Config": {
                "Cmd": ["-m", "internship_pipeline.update_validation"] if validation else None
            },
        }

    def ready(engine, manifest, **kwargs):
        record = engine.require_owned(manifest)
        assert record["State"]["Running"]
        if manifest != source and state["fail"] == "readiness":
            raise Failure("Synthetic readiness timeout")

    monkeypatch.setattr(update, "Runtime", Engine)
    monkeypatch.setattr(management, "Runtime", Engine)
    monkeypatch.setattr(update, "create_container", create)
    monkeypatch.setattr(update, "wait_ready", ready)
    monkeypatch.setattr(Release, "stage", stage)
    monkeypatch.setattr(update, "latest", lambda: RELEASE)
    return root, source, state


@pytest.mark.parametrize("running", [True, False])
def test_update_preserves_original_data_and_requested_running_state(workspace, running):
    root, source, state = workspace
    state["containers"][source.container_name]["State"]["Running"] = running
    original = copy.deepcopy(state["volumes"][source.volume_name])
    result = update.apply(root)
    target = load_manifest(root / "installation.json")
    assert result["updated"] and result["running"] is running
    assert target.image == NEW_IMAGE and target.data_dir == "/var/data/restored"
    assert target.install_id == source.install_id and target.runtime == source.runtime
    assert target.port == source.port and target.origin == source.origin
    assert state["volumes"][source.volume_name] == original
    assert source.container_name not in state["containers"]
    assert state["containers"][target.container_name]["State"]["Running"] is running
    assert (root / "command").is_symlink()
    assert private_json((root / "command").resolve() / ".installation-root")["path"] == str(root)
    assert not update.pending(root)
    before = copy.deepcopy(state)
    assert not update.apply(root)["updated"]
    assert state["volumes"] == before["volumes"]


@pytest.mark.parametrize(
    "failure", ["pull", "space", "backup", "restore", "validation", "readiness"]
)
def test_pre_activation_failure_preserves_original_and_restores_availability(workspace, failure):
    root, source, state = workspace
    state["fail"] = failure
    original = copy.deepcopy(state["volumes"][source.volume_name])
    with pytest.raises(Failure):
        update.apply(root)
    assert load_manifest(root / "installation.json") == source
    assert state["containers"][source.container_name]["State"]["Running"]
    assert state["volumes"][source.volume_name] == original
    assert not (root / "command").is_symlink()
    assert not update.pending(root)


def test_failed_preflight_saves_private_engine_evidence_before_rollback(workspace, monkeypatch):
    root, source, state = workspace
    original = update.image_run

    def fail_validation(*args, **kwargs):
        if "internship_pipeline.update_validation" in args:
            raise RuntimeCommandFailure(
                "docker",
                "run",
                subprocess.CompletedProcess([], 1, "", "private synthetic validation traceback"),
            )
        return original(*args, **kwargs)

    monkeypatch.setattr(update, "image_run", fail_validation)
    with pytest.raises(Failure, match="Failed during validating") as caught:
        update.apply(root)
    assert "private synthetic" not in str(caught.value)
    folder = root / "updates" / private_json(root / "update.json")["transaction"]
    log = folder / "failure.json"
    diagnostic = private_json(log)
    assert str(log) in str(caught.value)
    assert diagnostic["phase"] == "validating"
    assert diagnostic["exit_code"] == 1
    assert diagnostic["stderr"] == "private synthetic validation traceback"
    assert log.stat().st_mode & 0o077 == 0
    assert state["containers"][source.container_name]["State"]["Running"]
    assert not update.pending(root)


def test_unhealthy_rollback_remains_pending_until_original_is_ready(workspace, monkeypatch):
    root, source, state = workspace
    state["fail"] = "validation"
    original = update.wait_ready

    def unhealthy(runtime, manifest, **kwargs):
        if manifest == source:
            raise Failure("Original app is not ready")
        return original(runtime, manifest, **kwargs)

    monkeypatch.setattr(update, "wait_ready", unhealthy)
    with pytest.raises(Failure, match="Recovery is incomplete.*Original app is not ready"):
        update.apply(root)
    assert update.pending(root)
    monkeypatch.setattr(update, "wait_ready", original)
    assert update.apply(root)["recovered"]
    assert not update.pending(root)


def test_failure_to_write_diagnostics_does_not_prevent_rollback(workspace, monkeypatch):
    root, source, state = workspace
    state["fail"] = "validation"
    original = update.atomic_json

    def no_space(path, value):
        if path.name == "failure.json":
            raise OSError("No space left")
        return original(path, value)

    monkeypatch.setattr(update, "atomic_json", no_space)
    with pytest.raises(Failure, match="diagnostics could not be saved"):
        update.apply(root)
    assert not update.pending(root)
    assert load_manifest(root / "installation.json") == source
    assert state["containers"][source.container_name]["State"]["Running"]


@pytest.mark.parametrize(
    "phase", ["prepared", "stopping", "snapshot", "restoring", "validating", "committing"]
)
def test_process_interruption_before_activation_recovers_without_repeating_restore(
    workspace, monkeypatch, phase
):
    root, source, state = workspace
    real = update.set_phase

    def crash(root, journal, current):
        real(root, journal, current)
        if current == phase:
            raise Crash

    monkeypatch.setattr(update, "set_phase", crash)
    with pytest.raises(Crash):
        update.apply(root)
    assert update.pending(root)
    with pytest.raises(Failure, match="interrupted update"):
        update.require_idle(root)
    monkeypatch.setattr(update, "set_phase", real)
    old_restores = sum("restore" in call for call in state["calls"])
    assert update.apply(root)["recovered"]
    assert sum("restore" in call for call in state["calls"]) == old_restores
    assert load_manifest(root / "installation.json") == source
    assert state["containers"][source.container_name]["State"]["Running"]


def test_partial_manifest_command_switch_recovers_original_bundle(workspace, monkeypatch):
    root, source, state = workspace
    real = update.atomic_json

    def crash(path, value):
        real(path, value)
        if path == root / "installation.json" and value["image"] == NEW_IMAGE:
            raise Crash

    monkeypatch.setattr(update, "atomic_json", crash)
    with pytest.raises(Crash):
        update.apply(root)
    assert (root / "command").is_symlink()
    monkeypatch.setattr(update, "atomic_json", real)
    assert update.apply(root)["recovered"]
    assert load_manifest(root / "installation.json") == source
    assert not (root / "command").is_symlink()


def test_activation_failure_never_reverts_candidate_data(workspace):
    root, source, state = workspace
    state["fail"] = "activation"
    with pytest.raises(Failure, match="committed"):
        update.apply(root)
    target = load_manifest(root / "installation.json")
    state["volumes"][target.volume_name]["new-user-work"] = "must-survive"
    assert update.pending(root)
    state["fail"] = None
    assert update.apply(root)["updated"]
    assert state["volumes"][target.volume_name]["new-user-work"] == "must-survive"
    assert load_manifest(root / "installation.json") == target
    assert source.container_name not in state["containers"]


def test_storage_mismatch_and_check_leave_application_untouched(workspace, monkeypatch, capsys):
    root, source, state = workspace
    state["format"] = 2
    import pipeline_release

    monkeypatch.setattr(pipeline_release, "latest", lambda: RELEASE)
    assert management.main(["update", "--check", "--json", "--install-dir", str(root)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["update_available"] and not result["eligible"]
    assert "Storage format" in result["reason"]
    assert load_manifest(root / "installation.json") == source
    assert not (root / "updates").exists()
    assert not any(call[0] in {"stop", "pull", "create"} for call in state["calls"])
    with pytest.raises(Failure, match="Storage format"):
        update.apply(root)


def test_lifecycle_operations_share_one_host_lock(workspace, capsys):
    root, source, state = workspace
    with host_lock(root):
        assert management.main(["stop", "--install-dir", str(root)]) == 1
    assert "Another installation command" in capsys.readouterr().err
    assert state["containers"][source.container_name]["State"]["Running"]


def test_second_update_keeps_data_written_since_first_update(workspace):
    root, source, state = workspace
    update.apply(root)
    first = load_manifest(root / "installation.json")
    state["volumes"][first.volume_name]["user-added-job"] = "keep-me"
    third = replace(RELEASE, version="v0.1.0-rc.3", image=NEW_IMAGE.replace("b" * 64, "9" * 64))
    update.apply(root, third)
    second = load_manifest(root / "installation.json")
    assert second.volume_name != first.volume_name
    assert state["volumes"][second.volume_name]["user-added-job"] == "keep-me"
    assert first.container_name not in state["containers"]
    assert (root / "command").resolve().parent.name == private_json(root / "update.json")[
        "transaction"
    ]


def test_second_update_failure_restores_previous_generation_command(workspace):
    root, source, state = workspace
    update.apply(root)
    first = load_manifest(root / "installation.json")
    original_command = (root / "command").resolve()
    state["fail"] = "restore"
    third = replace(RELEASE, version="v0.1.0-rc.3", image=NEW_IMAGE.replace("b" * 64, "9" * 64))
    with pytest.raises(Failure, match="original installation was restored"):
        update.apply(root, third)
    assert load_manifest(root / "installation.json") == first
    assert (root / "command").resolve() == original_command
    assert state["containers"][first.container_name]["State"]["Running"]


def test_update_through_parent_directory_alias_keeps_stable_identity(workspace):
    root, source, state = workspace
    alias = root.parent / "parent-alias"
    alias.symlink_to(root.parent, target_is_directory=True)
    selected_root = alias / root.name
    assert update.apply(selected_root)["updated"]
    assert not update.apply(selected_root)["updated"]
    assert load_manifest(root / "installation.json").install_id == source.install_id


@pytest.mark.parametrize("validation", [False, True])
def test_container_creation_keeps_validation_restart_disabled(workspace, validation):
    root, source, state = workspace
    calls = []

    class Recorder:
        def run(self, *args, **kwargs):
            calls.append(args)

    target = replace(source, image=NEW_IMAGE, data_dir="/var/data/restored")
    install.create_container(Recorder(), target, validation=validation)
    args = calls[0]
    assert args[args.index("--restart") + 1] == ("no" if validation else "unless-stopped")
    assert f"type=volume,src={target.volume_name},dst=/var/data" in args
    if validation:
        assert args[-3:] == (NEW_IMAGE, "-m", "internship_pipeline.update_validation")
    else:
        assert args[-1] == NEW_IMAGE


def test_public_bootstrap_recovers_when_command_pointer_was_interrupted(workspace, monkeypatch):
    root, source, state = workspace
    real = update.replace_command
    monkeypatch.setattr(update, "replace_command", lambda *args: (_ for _ in ()).throw(Crash()))
    with pytest.raises(Crash):
        update.apply(root)
    assert not (root / "command").exists()
    monkeypatch.setattr(update, "replace_command", real)
    assert install.main(["--update", "--install-dir", str(root)]) == 0
    assert (root / "command/internship-pipeline").is_file()
    assert load_manifest(root / "installation.json") == source


def test_crash_at_activation_boundary_keeps_candidate_and_resumes(workspace, monkeypatch):
    root, source, state = workspace
    real = update.set_phase

    def crash(root, journal, phase):
        real(root, journal, phase)
        if phase == "activating":
            raise Crash

    monkeypatch.setattr(update, "set_phase", crash)
    with pytest.raises(Crash):
        update.apply(root)
    candidate = load_manifest(root / "installation.json")
    state["volumes"][candidate.volume_name]["new-state"] = "preserve"
    monkeypatch.setattr(update, "set_phase", real)
    assert update.apply(root)["updated"]
    assert state["volumes"][candidate.volume_name]["new-state"] == "preserve"


def test_target_image_declaration_must_match_metadata_before_downtime(workspace, monkeypatch):
    root, source, state = workspace
    monkeypatch.setattr(
        update, "image_format", lambda runtime, image: 2 if image == NEW_IMAGE else 1
    )
    with pytest.raises(Failure, match="Target image storage format differs"):
        update.apply(root)
    assert state["containers"][source.container_name]["State"]["Running"]
    assert not any(call[0] == "stop" for call in state["calls"])


def test_known_older_source_is_not_a_downgrade_path(workspace, monkeypatch):
    root, source, state = workspace
    atomic_json(
        root / "release.json",
        {
            **asdict(RELEASE),
            "version": "v0.1.0-rc.3",
            "image": OLD_IMAGE,
            "source_commit": "a" * 40,
        },
    )
    monkeypatch.setattr(
        "pipeline_release.fetch",
        lambda url: json.dumps(
            {
                "status": "behind",
                "base_commit": {"sha": "a" * 40},
                "merge_base_commit": {"sha": "d" * 40},
            }
        ).encode(),
    )
    result = update.check(root, source, RELEASE)
    assert not result["eligible"] and "downgrade" in result["reason"]
    with pytest.raises(Failure, match="downgrade"):
        update.apply(root)
    assert not (root / "updates").exists()


def test_numbering_reset_updates_newer_source_and_preserves_storage(workspace, monkeypatch):
    root, source, _ = workspace
    atomic_json(
        root / "release.json",
        {**asdict(RELEASE), "version": "v1.0.3", "image": OLD_IMAGE, "source_commit": "a" * 40},
    )
    monkeypatch.setattr(
        "pipeline_release.fetch",
        lambda url: json.dumps(
            {
                "status": "ahead",
                "base_commit": {"sha": "a" * 40},
                "merge_base_commit": {"sha": "a" * 40},
            }
        ).encode(),
    )
    target = replace(RELEASE, version="v0.1.4")
    result = update.check(root, source, target)
    assert result["eligible"] and result["update_available"]
    assert update.apply(root, target)["updated"]
    assert private_json(root / "release.json")["version"] == "v0.1.4"


def test_stable_promotion_of_same_image_updates_bundle_and_receipt(workspace):
    root, source, _ = workspace
    update.apply(root)
    preview = load_manifest(root / "installation.json")
    stable = replace(RELEASE, version="v0.1.0")
    assert update.check(root, preview, stable)["update_available"]
    assert update.apply(root, stable)["updated"]
    active = load_manifest(root / "installation.json")
    assert active.image == preview.image and active.volume_name != preview.volume_name
    assert private_json(root / "release.json")["version"] == "v0.1.0"
    assert not update.apply(root, stable)["updated"]


def test_matching_image_without_release_receipt_still_verifies_and_installs_bundle(workspace):
    root, _, _ = workspace
    update.apply(root)
    (root / "release.json").unlink()
    manifest = load_manifest(root / "installation.json")
    assert update.check(root, manifest, RELEASE)["update_available"]
    assert update.apply(root)["updated"]
    assert not update.apply(root)["updated"]


def test_installed_command_and_ordinary_installer_rerun_follow_active_generation(
    workspace, monkeypatch
):
    root, source, state = workspace
    update.apply(root)
    target = load_manifest(root / "installation.json")
    result = subprocess.run(
        [str(root / "command/internship-pipeline"), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
        env={
            **os.environ,
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
        },
    )
    assert "update" in result.stdout
    monkeypatch.setattr(install, "ensure_runtime", update.Runtime)
    monkeypatch.setattr(install, "wait_ready", lambda *args, **kwargs: None)
    before = len([call for call in state["calls"] if call[0] == "pull"])
    assert (
        install.main(
            [
                "--install-dir",
                str(root),
                "--command-dir",
                str(root.parent / "bin"),
                "--default-image",
                OLD_IMAGE,
                "--no-open",
            ]
        )
        == 0
    )
    assert load_manifest(root / "installation.json") == target
    assert len([call for call in state["calls"] if call[0] == "pull"]) == before


def test_changed_target_command_bytes_prevent_cutover(workspace, monkeypatch):
    root, source, state = workspace
    real = update.set_phase

    def tamper(root, journal, phase):
        real(root, journal, phase)
        if phase == "committing":
            target = (
                root
                / "updates"
                / journal["transaction"]
                / f"internship-pipeline-installer-{RELEASE.version}"
            )
            (target / "pipeline_management.py").write_text("# damaged command bytes")

    monkeypatch.setattr(update, "set_phase", tamper)
    with pytest.raises(Failure, match="bytes changed"):
        update.apply(root)
    assert load_manifest(root / "installation.json") == source
    assert state["containers"][source.container_name]["State"]["Running"]


def test_invalid_or_symlinked_journal_never_adopts_resources(workspace):
    root, source, state = workspace
    (root / "update.json").symlink_to(root / "installation.json")
    with pytest.raises(Failure, match="regular private file"):
        update.apply(root)
    assert not state["calls"]
    (root / "update.json").unlink()
    atomic_json(root / "update.json", {"transaction": "../foreign", "phase": "activating"})
    with pytest.raises(Failure, match="journal is invalid"):
        update.apply(root)
    assert not state["calls"]


def test_stopped_update_has_no_auto_restart_until_explicit_start(workspace, capsys):
    root, source, state = workspace
    state["containers"][source.container_name]["State"]["Running"] = False
    update.apply(root)
    target = load_manifest(root / "installation.json")
    assert state["containers"][target.container_name]["restart"] == "no"
    assert state["containers"][target.container_name]["mode"] == "validation"
    assert management.main(["start", "--install-dir", str(root)]) == 0
    assert state["containers"][target.container_name]["mode"] == "normal"
    assert state["containers"][target.container_name]["restart"] == "unless-stopped"
    assert state["containers"][target.container_name]["State"]["Running"]


def test_installer_update_uses_bootstrap_selected_identity(workspace, tmp_path, monkeypatch):
    root, source, state = workspace
    executor = tmp_path / "executor"
    executor.mkdir()
    atomic_json(
        executor / ".selected-release.json",
        {**asdict(RELEASE), "schema": 1, "repository": "Luke-Pitstick/internship-pipeline"},
    )
    monkeypatch.setattr(install, "__file__", str(executor / "install.py"))
    selected = []

    def apply(root, release):
        selected.append(release)
        return {"updated": False, "message": "Pinned release"}

    monkeypatch.setattr(update, "apply", apply)
    assert (
        install.main(["--update", "--default-image", RELEASE.image, "--install-dir", str(root)])
        == 0
    )
    assert selected == [RELEASE]


def test_recovery_resumes_after_retiring_source_and_removing_validation(workspace, monkeypatch):
    root, source, state = workspace
    real = update.create_container

    def crash(runtime, manifest, *, validation=False):
        if not validation:
            raise Crash
        real(runtime, manifest, validation=True)

    monkeypatch.setattr(update, "create_container", crash)
    with pytest.raises(Crash):
        update.apply(root)
    target = load_manifest(root / "installation.json")
    assert source.container_name not in state["containers"]
    assert target.container_name not in state["containers"]
    assert source.volume_name in state["volumes"] and target.volume_name in state["volumes"]
    monkeypatch.setattr(update, "create_container", real)
    assert update.apply(root)["updated"]
    assert state["containers"][target.container_name]["State"]["Running"]


def test_recovery_stops_orphaned_copy_before_restarting_original(workspace):
    root, source, state = workspace
    state["crash_backup"] = True
    with pytest.raises(Crash):
        update.apply(root)
    journal = private_json(root / "update.json")
    helper = f"internship-pipeline-{source.install_id}-update-{journal['transaction']}-maintenance"
    assert state["containers"][helper]["State"]["Running"]
    assert not state["containers"][source.container_name]["State"]["Running"]
    assert update.apply(root)["recovered"]
    assert helper not in state["containers"]
    stops = [i for i, call in enumerate(state["calls"]) if call[0] == "stop" and call[-1] == helper]
    starts = [
        i
        for i, call in enumerate(state["calls"])
        if call[0] == "start" and call[-1] == source.container_name
    ]
    assert stops and starts and stops[-1] < starts[-1]
    assert state["volumes"][source.volume_name]["jobs"] == ["synthetic"]


def test_recovery_does_not_stop_a_helper_with_foreign_ownership(workspace):
    root, source, state = workspace
    state["fail"] = "backup"
    state["maintenance_tamper"] = True
    with pytest.raises(Failure, match="ownership changed"):
        update.apply(root)
    journal = private_json(root / "update.json")
    helper = f"internship-pipeline-{source.install_id}-update-{journal['transaction']}-maintenance"
    assert update.pending(root)
    assert state["containers"][helper]["State"]["Running"]
    assert not any(call[0] in {"stop", "rm"} and call[-1] == helper for call in state["calls"])
