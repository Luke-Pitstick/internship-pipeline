#!/usr/bin/env python3
"""Local installer candidate. Hosting and release image publication are pending."""

from __future__ import annotations

import argparse
import fcntl
import os
import platform
import shlex
import shutil
import socket
import sys
from pathlib import Path
from uuid import uuid4

from pipeline_runtime import (
    LABEL,
    Failure,
    Manifest,
    Runtime,
    RuntimeSpec,
    default_install_dir,
    discover_runtime,
    load_manifest,
    validate_image,
    wait_ready,
    write_manifest,
)

BUNDLE_FILES = ("internship-pipeline", "pipeline_runtime.py", "pipeline_management.py")


def select_runtime(requested: str | None) -> RuntimeSpec:
    if requested:
        return discover_runtime(requested)
    candidates = []
    for name in ("docker", "podman"):
        try:
            candidates.append(discover_runtime(name))
        except Failure:
            continue
    if not candidates:
        raise Failure(
            "No healthy local Linux container engine was found. Install or "
            "start Docker Desktop/Docker Engine or Podman, then rerun; the "
            "installer does not install or start runtime software."
        )
    if len(candidates) > 1:
        raise Failure(
            "Several healthy runtimes are available. Rerun with --runtime "
            "docker or --runtime podman to choose one."
        )
    return candidates[0]


def check_host() -> None:
    if platform.system() not in {"Linux", "Darwin"} or platform.machine().lower() not in {
        "x86_64",
        "amd64",
        "aarch64",
        "arm64",
    }:
        raise Failure(
            "Installer preparation targets Linux/macOS on amd64/arm64 only; "
            "this host is outside the candidate matrix."
        )


def check_port(port: int) -> None:
    if not 1024 <= port <= 65535:
        raise Failure("Choose an unprivileged port from 1024 through 65535.")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", port))
    except OSError as exc:
        raise Failure(
            f"Port {port} is unavailable. Choose --port with a free port before installation."
        ) from exc


def secure_directory(path: Path, *, allow_nonempty: bool = False) -> None:
    if path.is_symlink():
        raise Failure(f"Refusing a symlink installation directory: {path}")
    if path.exists():
        if not path.is_dir() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o022:
            raise Failure(f"Directory must be owned by you and not writable by others: {path}")
        if not allow_nonempty and any(path.iterdir()):
            raise Failure(
                f"Directory already contains unrecognized files: {path}. "
                f"Choose an empty --install-dir."
            )
    else:
        path.mkdir(parents=True, mode=0o700)


def command_target(install_dir: Path, command_dir: Path) -> tuple[Path, Path]:
    return install_dir / "command/internship-pipeline", command_dir / "internship-pipeline"


def check_command_path(install_dir: Path, command_dir: Path) -> None:
    secure_directory(command_dir, allow_nonempty=True)
    target, command = command_target(install_dir, command_dir)
    if command.is_symlink():
        if os.readlink(command) != str(target):
            raise Failure(
                f"An unrelated command already exists at {command}; choose --command-dir."
            )
    elif command.exists():
        raise Failure(f"An unrelated command already exists at {command}; choose --command-dir.")


def install_command(install_dir: Path, command_dir: Path, install_id: str) -> None:
    source_dir = Path(__file__).resolve().parent
    target, command = command_target(install_dir, command_dir)
    bundle = target.parent
    marker = bundle / ".installation-id"
    if bundle.exists():
        secure_directory(bundle, allow_nonempty=True)
        if marker.is_symlink() or not marker.is_file() or marker.read_text().strip() != install_id:
            raise Failure(
                "Installed command bundle is unrecognized; leave it "
                "untouched and inspect the installation."
            )
        for filename in BUNDLE_FILES:
            item = bundle / filename
            if (
                item.is_symlink()
                or not item.is_file()
                or item.stat().st_uid != os.getuid()
                or item.stat().st_mode & 0o022
            ):
                raise Failure(
                    "Installed command file is unsafe or missing; restore "
                    "the matching command bundle."
                )
    else:
        missing = [name for name in BUNDLE_FILES if not (source_dir / name).is_file()]
        if missing:
            raise Failure(
                "Installer bundle is incomplete; obtain all files from the same reviewed release."
            )
        bundle.mkdir(mode=0o700)
        for filename in BUNDLE_FILES:
            destination = bundle / filename
            shutil.copyfile(source_dir / filename, destination)
            destination.chmod(0o700 if filename == "internship-pipeline" else 0o600)
        marker.write_text(install_id + "\n")
        marker.chmod(0o600)
    if command.is_symlink():
        if os.readlink(command) != str(target):
            raise Failure("Management command changed during installation; inspect its target.")
    else:
        command.symlink_to(target)


def provision(runtime: Runtime, manifest: Manifest, install_dir: Path) -> None:
    marker = install_dir / ".volume-created"
    if marker.exists() and (
        marker.is_symlink() or marker.read_text().strip() != manifest.install_id
    ):
        raise Failure("Volume creation marker is unrecognized; inspect the saved installation.")
    volume = runtime.inspect_volume(manifest)
    container = runtime.inspect_container(manifest)
    if volume is None:
        if marker.exists() or container is not None:
            raise Failure(
                "Saved data volume is missing; restore it before retrying. "
                "A rerun never replaces a missing data volume."
            )
        runtime.run(
            "volume", "create", "--label", f"{LABEL}={manifest.install_id}", manifest.volume_name
        )
        if runtime.inspect_volume(manifest) is None:
            raise Failure(
                "Runtime did not retain the new volume; check its storage before retrying."
            )
    if not marker.exists():
        with marker.open("x") as stream:
            os.chmod(marker, 0o600)
            stream.write(manifest.install_id + "\n")
    if container is None:
        check_port(manifest.port)
        runtime.run("pull", manifest.image, timeout=600)
        runtime.run(
            "create",
            "--name",
            manifest.container_name,
            "--label",
            f"{LABEL}={manifest.install_id}",
            "--init",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--restart",
            "unless-stopped",
            "--stop-timeout",
            "45",
            "--publish",
            f"127.0.0.1:{manifest.port}:8080",
            "--env",
            f"PIPELINE_ORIGIN={manifest.origin}",
            "--mount",
            f"type=volume,src={manifest.volume_name},dst=/var/data",
            manifest.image,
            timeout=60,
        )
        container = runtime.require_owned(manifest)
    if not (container.get("State") or {}).get("Running"):
        runtime.run("start", manifest.container_name, timeout=30)


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(
        description=(
            "Prepare a local Internship Pipeline installation using an explicit released image. "
            "No image/host matrix is certified yet."
        )
    )
    cli.add_argument(
        "--image", help="explicit version tag or sha256 digest; required for first installation"
    )
    cli.add_argument(
        "--runtime",
        choices=("docker", "podman"),
        help="choose when several healthy local engines exist",
    )
    cli.add_argument("--port", type=int, help="loopback HTTP port (default 8080 on first install)")
    cli.add_argument("--install-dir", type=Path, default=default_install_dir())
    cli.add_argument("--command-dir", type=Path, default=Path.home() / ".local/bin")
    cli.add_argument("--ready-timeout", type=int, default=60, help="readiness wait seconds (1–300)")
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        check_host()
        if not 1 <= args.ready_timeout <= 300:
            raise Failure("Readiness timeout must be between 1 and 300 seconds.")
        install_dir = args.install_dir.expanduser().absolute()
        command_dir = args.command_dir.expanduser().absolute()
        manifest_path = install_dir / "installation.json"
        existing = manifest_path.exists() or manifest_path.is_symlink()
        secure_directory(install_dir, allow_nonempty=True)
        if not existing and any(item.name != ".installer.lock" for item in install_dir.iterdir()):
            raise Failure(
                "Installation directory contains unrecognized files; choose an empty --install-dir."
            )
        check_command_path(install_dir, command_dir)
        lock_path = install_dir / ".installer.lock"
        # Refuse a preexisting symlink rather than locking or writing another file.
        if lock_path.is_symlink():
            raise Failure("Installer lock is a symlink; inspect the installation directory.")
        with lock_path.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Failure(
                    "Another installer is using this directory; wait for it to finish."
                ) from exc
            if existing:
                manifest = load_manifest(manifest_path)
                if (
                    (args.image and args.image != manifest.image)
                    or (args.runtime and args.runtime != manifest.runtime.name)
                    or (args.port is not None and args.port != manifest.port)
                ):
                    raise Failure(
                        "Reruns retain the saved image, runtime and port. "
                        "Restore/review an explicit update separately."
                    )
                runtime = Runtime(manifest.runtime)
                runtime.check()
            else:
                if not args.image:
                    raise Failure(
                        "First installation requires --image with a "
                        "verified release version or digest. No release "
                        "image is supplied automatically."
                    )
                validate_image(args.image)
                check_port(args.port if args.port is not None else 8080)
                spec = select_runtime(args.runtime)
                install_id = str(uuid4())
                stem = "internship-pipeline-" + install_id
                port = args.port if args.port is not None else 8080
                origin = f"http://localhost:{port}"
                manifest = Manifest(
                    1, install_id, spec, stem, stem + "-data", args.image, port, origin, origin
                )
                # Record identity before engine resources; failed operations never erase state.
                write_manifest(manifest_path, manifest)
                runtime = Runtime(spec)
            install_command(install_dir, command_dir, manifest.install_id)
            provision(runtime, manifest, install_dir)
            wait_ready(runtime, manifest, timeout=args.ready_timeout)
        print(f"Ready: {manifest.url}\nManagement command: {command_dir / 'internship-pipeline'}")
        print(f"Manifest: {manifest_path}\nData volume: {manifest.volume_name}")
        print("For an unclaimed instance, read the Owner setup token in a private terminal:")
        print(shlex.join(runtime.argv("logs", "--tail", "200", manifest.container_name)))
        print(
            "Open the URL, enter that token, create your owner account, then follow guided setup."
        )
        print(
            "Add the command directory to PATH if needed. Use the printed "
            "command with --help or status."
        )
        return 0
    except (Failure, OSError) as exc:
        print(f"Installation stopped: {exc}", file=sys.stderr)
        print(
            "Existing data and configuration are retained. Rerun the same "
            "command after resolving the error.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
