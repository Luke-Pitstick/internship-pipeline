"""Explicit same-format updates with isolated candidate storage and durable recovery."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, replace
from functools import partial
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from install import BUNDLE_FILES, create_container, secure_directory
from installer_ui import InstallProgress
from pipeline_release import VERSION, Release, latest, version_key
from pipeline_runtime import (
    LABEL,
    Failure,
    Manifest,
    Runtime,
    RuntimeCommandFailure,
    atomic_json,
    atomic_text,
    load_manifest,
    private_json,
    require_complete_restore,
    sync_directory,
    wait_ready,
)

CLOSED = {"complete", "rolled_back"}
PHASES = {
    "prepared",
    "stopping",
    "snapshot",
    "restoring",
    "validating",
    "committing",
    "activating",
    *CLOSED,
}


def image_run(
    runtime: Runtime,
    image: str,
    *args: str,
    mounts: tuple[str, ...] = (),
    environment: tuple[str, ...] = (),
    timeout: float = 600,
    name: str | None = None,
    owner: str | None = None,
) -> str:
    argv = [
        "run",
        "--rm",
        "--pull",
        "never",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp",
        "--entrypoint",
        "python",
    ]
    for mount in mounts:
        argv += ["--mount", mount]
    for value in environment:
        argv += ["--env", value]
    if name is not None:
        if owner is None:
            raise Failure("Named maintenance requires installation ownership.")
        argv += ["--name", name, "--label", f"{LABEL}={owner}"]
    return runtime.run(*argv, image, "-B", *args, timeout=timeout)


def image_format(runtime: Runtime, image: str) -> int:
    try:
        value = json.loads(
            image_run(runtime, image, "-m", "internship_pipeline.storage_format", timeout=30)
        )
        if not isinstance(value, dict) or set(value) != {"storage_format"}:
            raise ValueError
        if type(value["storage_format"]) is not int or value["storage_format"] < 1:
            raise ValueError
        return int(value["storage_format"])
    except (Failure, ValueError, KeyError, TypeError):
        raise Failure(
            "The exact image has no valid storage-format declaration; update refused."
        ) from None


def source_identity(runtime: Runtime, manifest: Manifest) -> tuple[dict[str, Any], str]:
    container = runtime.require_owned(manifest)
    image = container.get("Image")
    if not isinstance(image, str) or not re.fullmatch(r"(?:sha256:)?[a-f0-9]{64}", image):
        raise Failure("The exact installed image is unavailable; preserve the installation.")
    return container, "sha256:" + image.removeprefix("sha256:")


def receipt(root: Path) -> dict[str, Any]:
    path = root / "release.json"
    return private_json(path) if path.exists() or path.is_symlink() else {}


def check(root: Path, manifest: Manifest, release: Release) -> dict[str, Any]:
    require_complete_restore(root, manifest)
    runtime = Runtime(manifest.runtime)
    runtime.check()
    _, source_image = source_identity(runtime, manifest)
    installed = receipt(root)
    if installed and installed.get("image") != manifest.image:
        raise Failure(
            "Saved release identity differs from the active image; preserve the installation."
        )
    reason = None
    current_format = None
    try:
        current_format = image_format(runtime, source_image)
        if current_format != release.storage_format:
            reason = (
                f"Storage format {current_format} differs from release format "
                f"{release.storage_format}."
            )
    except Failure as exc:
        reason = str(exc)
    installed_version = installed.get("version")
    if isinstance(installed_version, str) and re.fullmatch(VERSION, installed_version):
        if version_key(release.version) < version_key(installed_version):
            reason = "Latest release is older than the installed release; downgrade refused."
    return {
        "installed_version": installed_version,
        "installed_image": manifest.image,
        "available_version": release.version,
        "available_image": release.image,
        "storage_format": current_format,
        "available_storage_format": release.storage_format,
        "update_available": manifest.image != release.image or installed_version != release.version,
        "eligible": reason is None,
        "reason": reason,
    }


def pending(root: Path) -> bool:
    path = root / "update.json"
    if not path.exists() and not path.is_symlink():
        return False
    phase = private_json(path).get("phase")
    if not isinstance(phase, str) or phase not in PHASES:
        raise Failure("Update journal is invalid; preserve all installation resources.")
    return phase not in CLOSED


def require_idle(root: Path) -> None:
    if pending(root):
        raise Failure("An interrupted update needs recovery. Run internship-pipeline update first.")


def set_phase(root: Path, journal: dict[str, Any], phase: str) -> None:
    journal["phase"] = phase
    atomic_json(root / "updates" / journal["transaction"] / "journal.json", journal)
    atomic_json(root / "update.json", journal)
    labels = {
        "prepared": "Preparing the update",
        "stopping": "Stopping the app",
        "snapshot": "Saving a verified backup",
        "restoring": "Preparing your saved data",
        "validating": "Migrating saved data and checking the new version",
        "committing": "Selecting the new version",
        "activating": "Completing the update",
        "complete": "Update complete",
        "rolled_back": "Original installation restored",
    }
    print(InstallProgress().style(f"  {labels[phase]}", "36"), file=sys.stderr)


def transaction(root: Path) -> tuple[dict[str, Any], Path, Manifest, Manifest]:
    journal = private_json(root / "update.json")
    try:
        token = journal["transaction"]
        if not isinstance(token, str) or UUID(token).hex != token:
            raise ValueError
        if journal["phase"] not in PHASES or type(journal["was_running"]) is not bool:
            raise ValueError
        if not isinstance(journal["source_image"], str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", journal["source_image"]
        ):
            raise ValueError
        folder = root / "updates" / token
        if not folder.is_dir():
            raise ValueError
        secure_directory(root / "updates", allow_nonempty=True)
        secure_directory(folder, allow_nonempty=True)
        source = load_manifest(folder / "source.json")
        target = load_manifest(folder / "target.json")
        if (
            source.install_id != target.install_id
            or source.runtime != target.runtime
            or source.origin != target.origin
            or source.port != target.port
            or target.container_name != f"internship-pipeline-{source.install_id}-update-{token}"
            or target.data_dir != "/var/data/restored"
        ):
            raise ValueError
        bundle = Path(journal["source_bundle"])
        if bundle.is_absolute() or ".." in bundle.parts or not bundle.parts:
            raise ValueError
        if bundle != Path("updates") / token / "source-command" and not (
            len(bundle.parts) == 3
            and bundle.parts[0] == "updates"
            and UUID(bundle.parts[1]).hex == bundle.parts[1]
            and bundle.parts[2].startswith("internship-pipeline-installer-")
        ):
            raise ValueError
        release = Release.parse(private_json(folder / "release.json"), journal["version"])
        if target.image != release.image:
            raise ValueError
        return journal, folder, source, target
    except (KeyError, ValueError, TypeError):
        raise Failure("Update journal is invalid; preserve all installation resources.") from None


def replace_command(root: Path, target: Path) -> None:
    temporary = root / ".command-next"
    if temporary.exists() or temporary.is_symlink():
        if not temporary.is_symlink():
            raise Failure("Unrecognized command staging file; preserve the installation.")
        temporary.unlink()
    temporary.symlink_to(target)
    os.replace(temporary, root / "command")
    sync_directory(root)


def commit(root: Path, journal: dict[str, Any], folder: Path, target: Manifest) -> None:
    release = Release.parse(private_json(folder / "release.json"), journal["version"])
    bundle = folder / f"internship-pipeline-installer-{release.version}"
    secure_directory(bundle, allow_nonempty=True)
    hashes = private_json(folder / "bundle-files.json")
    if set(hashes) != set(BUNDLE_FILES):
        raise Failure("Saved target command verification is incomplete.")
    for name in BUNDLE_FILES:
        path = bundle / name
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_mode & 0o022
            or path.stat().st_uid != os.getuid()
            or (name == "internship-pipeline" and not path.stat().st_mode & 0o100)
        ):
            raise Failure("Verified target command bundle is incomplete or unsafe.")
        if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[name]:
            raise Failure("Target command bytes changed; preserve the installation.")
    atomic_json(bundle / ".installation-root", {"path": str(root), "install_id": target.install_id})
    marker = bundle / ".installation-id"
    atomic_text(marker, target.install_id + "\n")
    current = root / "command"
    if not current.is_symlink() and current.is_dir():
        # A first update must move the original directory before replacing its pointer.
        destination = folder / "source-command"
        if destination.exists():
            raise Failure("Original command archive already exists; preserve both directories.")
        os.rename(current, destination)
        sync_directory(folder)
        sync_directory(root)
    replace_command(root, bundle)
    atomic_json(root / "installation.json", asdict(target))
    atomic_json(
        root / "release.json",
        {**asdict(release), "repository": "Luke-Pitstick/internship-pipeline", "schema": 1},
    )
    # The staged restore has been fully verified before any active pointer changes.
    for name in (".restore-started", ".restore-completed"):
        path = root / name
        atomic_text(path, target.install_id + "\n")
    sync_directory(root)


def stop(runtime: Runtime, manifest: Manifest) -> None:
    container = runtime.require_owned(manifest)
    if (container.get("State") or {}).get("Running"):
        runtime.run("stop", "--time", "30", manifest.container_name, timeout=40)
    if (runtime.require_owned(manifest).get("State") or {}).get("Running"):
        raise Failure("Container did not stop; update cannot continue.")


def rollback(
    root: Path, journal: dict[str, Any], folder: Path, source: Manifest, target: Manifest
) -> None:
    runtime = Runtime(source.runtime)
    runtime.check()
    cleanup_maintenance(runtime, journal, source, target)
    if runtime.inspect_container(target) is not None:
        stop(runtime, target)
    source_bundle = root / journal["source_bundle"]
    current = root / "command"
    if source_bundle.exists():
        if source_bundle == folder / "source-command":
            if current.is_symlink():
                current.unlink()
            if current.exists():
                raise Failure("Cannot restore command directory over an unrelated path.")
            os.rename(source_bundle, current)
            sync_directory(folder)
            sync_directory(root)
        else:
            replace_command(root, source_bundle)
    elif not current.is_dir() or current.is_symlink():
        raise Failure(
            "Original command bundle is unavailable; preserve all data and retry recovery."
        )
    atomic_json(root / "installation.json", asdict(source))
    previous = private_json(folder / "source-release.json")
    if previous:
        atomic_json(root / "release.json", previous)
    elif (root / "release.json").exists():
        private_json(root / "release.json")
        (root / "release.json").unlink()
        sync_directory(root)
    if journal["was_running"]:
        if not (runtime.require_owned(source).get("State") or {}).get("Running"):
            runtime.run("start", source.container_name, timeout=30)
        if not (runtime.require_owned(source).get("State") or {}).get("Running"):
            raise Failure("Original application could not restart; preserve the source data.")
        wait_ready(runtime, source, timeout=120)
    else:
        stop(runtime, source)
    set_phase(root, journal, "rolled_back")


def cleanup_maintenance(
    runtime: Runtime, journal: dict[str, Any], source: Manifest, target: Manifest
) -> None:
    """Stop a surviving one-off process before releasing its data locks to the app."""
    name = target.container_name + "-maintenance"
    container = runtime._inspect("container", name)
    if container is None:
        return
    config = container.get("Config") or {}
    mounts = container.get("Mounts")
    identifier = container.get("Id")
    if (
        not isinstance(config, dict)
        or not isinstance(config.get("Labels"), dict)
        or config["Labels"].get(LABEL) != source.install_id
        or not isinstance(config.get("Image"), str)
        or config.get("Image") not in {journal["source_image"], target.image}
        or not isinstance(mounts, list)
        or not isinstance(container.get("State"), dict)
        or not isinstance(identifier, str)
        or not re.fullmatch(r"[0-9a-f]{64}", identifier)
    ):
        raise Failure("Maintenance container ownership changed; preserve it for review.")
    for mount in mounts:
        if not isinstance(mount, dict):
            raise Failure("Maintenance mounts are invalid; preserve the container.")
        if mount.get("Type") == "tmpfs" and mount.get("Destination") == "/tmp":
            continue
        if (
            mount.get("Type") != "volume"
            or not isinstance(mount.get("Name"), str)
            or mount.get("Name") not in {source.volume_name, target.volume_name}
            or not isinstance(mount.get("Destination"), str)
            or mount.get("Destination") not in {"/var/data", "/recovery"}
        ):
            raise Failure("Maintenance storage changed; preserve the container for review.")
    if (container.get("State") or {}).get("Running"):
        runtime.run("stop", "--time", "10", name, timeout=20)
    remaining = runtime._inspect("container", name)
    if remaining is not None:
        if remaining.get("Id") != identifier:
            raise Failure("Maintenance identity changed while stopping; preserve the container.")
        if not isinstance(remaining.get("State"), dict):
            raise Failure("Maintenance state is invalid; preserve the container.")
        if (remaining.get("State") or {}).get("Running"):
            raise Failure("Maintenance is still running; preserve data and retry recovery.")
        runtime.run("rm", name)


def activate(
    root: Path, journal: dict[str, Any], folder: Path, source: Manifest, target: Manifest
) -> dict[str, Any]:
    runtime = Runtime(target.runtime)
    runtime.check()
    commit(root, journal, folder, target)
    # Retire executable source state only after the durable activation boundary.
    # Its original data/image remain retained, but reboot services cannot launch
    # stale collection/delivery work alongside the new application.
    if runtime.inspect_container(source) is not None:
        stop(runtime, source)
        runtime.run("rm", source.container_name)
    if journal["was_running"]:
        activate_container(runtime, target)
        container = runtime.require_owned(target)
        if not (container.get("State") or {}).get("Running"):
            runtime.run("start", target.container_name, timeout=30)
        wait_ready(runtime, target, timeout=120)
    else:
        stop(runtime, target)
    if load_manifest(root / "installation.json") != target:
        raise Failure("Active installation differs from the committed update.")
    set_phase(root, journal, "complete")
    return {
        "updated": True,
        "version": journal["version"],
        "running": journal["was_running"],
        "url": target.url,
        "backup_volume": target.volume_name,
        "original_volume": source.volume_name,
    }


def activate_container(runtime: Runtime, manifest: Manifest) -> None:
    """Create ordinary app execution only after commit or an explicit later start.

    A stopped validation container has restart disabled, including across host
    reboots. Recreate it with the ordinary restart policy at activation; this also
    resumes a crash between removing validation and creating the app container.
    """
    if runtime.inspect_volume(manifest) is None:
        raise Failure("Committed update volume is missing; preserve the installation.")
    container = runtime.inspect_container(manifest)
    if container is not None and (container.get("Config") or {}).get("Cmd") == [
        "-m",
        "internship_pipeline.update_validation",
    ]:
        stop(runtime, manifest)
        runtime.run("rm", manifest.container_name)
        container = None
    if container is None:
        create_container(runtime, manifest)
        runtime.require_owned(manifest)


def recover(root: Path) -> dict[str, Any]:
    journal, folder, source, target = transaction(root)
    if journal["phase"] == "activating":
        runtime = Runtime(target.runtime)
        runtime.check()
        cleanup_maintenance(runtime, journal, source, target)
        # Once normal work may have started, the candidate is the only current data.
        return activate(root, journal, folder, source, target)
    rollback(root, journal, folder, source, target)
    return {
        "updated": False,
        "recovered": True,
        "message": "Original installation restored after interruption. Rerun update to try again.",
    }


def apply(root: Path, release: Release | None = None) -> dict[str, Any]:
    if pending(root):
        return recover(root)
    manifest = load_manifest(root / "installation.json")
    require_complete_restore(root, manifest)
    release = release or latest()
    result = check(root, manifest, release)
    if not result["eligible"]:
        raise Failure(str(result["reason"]))
    if not result["update_available"]:
        return {
            "updated": False,
            "message": f"Already running the latest release ({release.version}).",
        }
    runtime = Runtime(manifest.runtime)
    container, source_image = source_identity(runtime, manifest)
    current_bundle = root / "command"
    original_bundle = current_bundle.resolve()
    if not original_bundle.is_dir():
        raise Failure("Saved command bundle is missing; preserve the installation.")
    if current_bundle.is_symlink() and not original_bundle.is_relative_to(
        (root / "updates").resolve()
    ):
        raise Failure("Saved command points outside this installation; nothing was stopped.")
    secure_directory(original_bundle, allow_nonempty=True)
    marker = original_bundle / ".installation-id"
    if (
        marker.is_symlink()
        or not marker.is_file()
        or marker.read_text().strip() != manifest.install_id
    ):
        raise Failure("Saved command ownership is unrecognized; nothing was stopped.")
    for name in ("internship-pipeline", "pipeline_management.py", "pipeline_runtime.py", "LICENSE"):
        path = original_bundle / name
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_uid != os.getuid()
            or path.stat().st_mode & 0o022
        ):
            raise Failure("Saved command bundle is unsafe; nothing was stopped.")
    token = uuid4().hex
    updates = root / "updates"
    secure_directory(updates, allow_nonempty=True)
    folder = updates / token
    folder.mkdir(mode=0o700)
    sync_directory(updates)
    # Downloads and pulls happen while the original app remains available.
    bundle = release.stage(folder)
    hashes = {}
    for name in BUNDLE_FILES:
        path = bundle / name
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 1024 * 1024:
            raise Failure("Verified target command file is missing or unsafe.")
        with path.open("rb") as stream:
            hashes[name] = hashlib.file_digest(stream, "sha256").hexdigest()
            os.fsync(stream.fileno())
    sync_directory(bundle)
    atomic_json(folder / "bundle-files.json", hashes)
    progress = InstallProgress(total=1)
    progress.start(f"Downloading app {release.version}")
    try:
        runtime.run("pull", release.image, timeout=600)
    except BaseException:
        progress.finish(success=False)
        raise
    else:
        progress.finish()
    if image_format(runtime, release.image) != release.storage_format:
        raise Failure("Target image storage format differs from its release metadata.")
    target = replace(
        manifest,
        container_name=f"internship-pipeline-{manifest.install_id}-update-{token}",
        volume_name=f"internship-pipeline-{manifest.install_id}-update-{token}-data",
        image=release.image,
        data_dir="/var/data/restored",
    )
    if runtime.inspect_volume(target) is not None or runtime.inspect_container(target) is not None:
        raise Failure("Update candidate resources already exist; nothing was stopped.")
    maintenance_name = target.container_name + "-maintenance"
    if runtime._inspect("container", maintenance_name) is not None:
        raise Failure("Update maintenance name already exists; nothing was stopped.")
    if current_bundle.is_symlink():
        source_bundle = current_bundle.resolve().relative_to(root.resolve())
    else:
        source_bundle = Path("updates") / token / "source-command"
    journal = {
        "transaction": token,
        "phase": "prepared",
        "was_running": bool((container.get("State") or {}).get("Running")),
        "version": release.version,
        "source_bundle": str(source_bundle),
        "source_image": source_image,
    }
    atomic_json(folder / "source.json", asdict(manifest))
    atomic_json(folder / "target.json", asdict(target))
    atomic_json(
        folder / "release.json",
        {**asdict(release), "schema": 1, "repository": "Luke-Pitstick/internship-pipeline"},
    )
    atomic_json(folder / "source-release.json", receipt(root))
    set_phase(root, journal, "prepared")
    maintenance = partial(image_run, name=maintenance_name, owner=manifest.install_id)
    try:
        runtime.run(
            "volume", "create", "--label", f"{LABEL}={manifest.install_id}", target.volume_name
        )
        if runtime.inspect_volume(target) is None:
            raise Failure("Candidate storage was not created; update stopped.")
        mount = f"type=volume,src={target.volume_name},dst=/var/data"
        maintenance(
            runtime,
            source_image,
            "-c",
            "from pathlib import Path; Path('/var/data/reserved').touch()",
            mounts=(mount,),
        )
        space_json = maintenance(
            runtime,
            source_image,
            "-c",
            "import json,pathlib,shutil,sys; root=pathlib.Path(sys.argv[1]); "
            "needed=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())*2+67108864; "
            "print(json.dumps({'needed':needed,'free':shutil.disk_usage('/recovery').free}))",
            manifest.data_dir,
            mounts=(
                f"type=volume,src={manifest.volume_name},dst=/var/data,readonly",
                f"type=volume,src={target.volume_name},dst=/recovery",
            ),
        )
        space = json.loads(space_json)
        if not isinstance(space, dict) or any(
            type(space.get(key)) is not int or space[key] < 0 for key in ("needed", "free")
        ):
            raise Failure("Storage estimate is invalid; update stopped before downtime.")
        if space["free"] < space["needed"]:
            raise Failure(
                f"Insufficient container storage: need {space['needed']:,} bytes, "
                f"but only {space['free']:,} bytes are free. Free space and rerun update."
            )
        set_phase(root, journal, "stopping")
        stop(runtime, manifest)
        set_phase(root, journal, "snapshot")
        maintenance(
            runtime,
            source_image,
            "-m",
            "internship_pipeline.cli",
            "--config",
            f"{manifest.data_dir}/config/settings.yaml",
            "backup",
            "/recovery/backup",
            "--data-dir",
            manifest.data_dir,
            mounts=(
                f"type=volume,src={manifest.volume_name},dst=/var/data",
                f"type=volume,src={target.volume_name},dst=/recovery",
            ),
        )
        set_phase(root, journal, "restoring")
        maintenance(
            runtime,
            source_image,
            "-m",
            "internship_pipeline.cli",
            "restore",
            "/var/data/backup",
            "/var/data/restored",
            mounts=(mount,),
        )
        set_phase(root, journal, "validating")
        maintenance(
            runtime,
            release.image,
            "-m",
            "internship_pipeline.update_validation",
            "--check",
            mounts=(mount,),
            environment=(
                "PIPELINE_DATA_DIR=/var/data/restored",
                f"PIPELINE_ORIGIN={target.origin}",
            ),
        )
        create_container(runtime, target, validation=True)
        runtime.run("start", target.container_name, timeout=30)
        wait_ready(runtime, target, timeout=120)
        stop(runtime, target)
        runtime.require_owned(target)
        set_phase(root, journal, "committing")
        commit(root, journal, folder, target)
        # Persist the no-rollback boundary before admitting normal work or user writes.
        set_phase(root, journal, "activating")
        return activate(root, journal, folder, manifest, target)
    except (Failure, OSError, ValueError, KeyboardInterrupt) as exc:
        failed_phase = journal["phase"]
        diagnostic: dict[str, Any] = {
            "phase": failed_phase,
            "version": release.version,
            "error": str(exc),
        }
        if isinstance(exc, RuntimeCommandFailure):
            diagnostic.update(exit_code=exc.returncode, stdout=exc.stdout, stderr=exc.stderr)
        diagnostic_path = folder / "failure.json"
        try:
            atomic_json(diagnostic_path, diagnostic)
            details = f"Private diagnostics: {diagnostic_path}"
        except (OSError, Failure):
            # A full/unavailable disk must not prevent rollback.
            details = "Private diagnostics could not be saved; preserve the update directory."
        context = f"Failed during {failed_phase}: {exc} {details}"
        if journal["phase"] != "activating":
            try:
                rollback(root, journal, folder, manifest, target)
            except (Failure, OSError, ValueError) as recovery_error:
                raise Failure(
                    "Recovery is incomplete. Preserve all data and rerun "
                    f"internship-pipeline update. {recovery_error} {context}"
                ) from None
            raise Failure(
                "Update failed before activation; the original installation was restored. "
                + context
            ) from None
        raise Failure(
            "Update is committed. Preserve candidate data and rerun "
            "internship-pipeline update to finish starting it. " + context
        ) from None
