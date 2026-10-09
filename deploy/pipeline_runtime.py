"""Shared host runtime and installation contract; no engine context mutations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, BinaryIO, cast
from urllib.parse import urlsplit
from uuid import UUID

LABEL = "io.internship-pipeline.install-id"

RESTORE_STREAM = """\
import hashlib, os, pathlib, sys, tarfile
from internship_pipeline.operations import restore_installation
os.umask(0o077)
def private_member(member, destination):
    if not (member.isfile() or member.isdir()):
        raise RuntimeError('Backup transfer accepts only regular files and directories')
    return tarfile.data_filter(member, destination)
backup = pathlib.Path('/var/data/backup')
backup.mkdir(mode=0o700)
with tarfile.open(fileobj=sys.stdin.buffer, mode='r|') as archive:
    archive.extractall(backup, filter=private_member)
if hashlib.sha256((backup / 'manifest.json').read_bytes()).hexdigest() != sys.argv[1]:
    raise RuntimeError('Backup identity changed during transfer')
restore_installation(backup, pathlib.Path('/var/data/restored'))
"""


class DeadlineReader:
    def __init__(self, source: BinaryIO, deadline: float) -> None:
        self.source = source
        self.deadline = deadline

    def read(self, size: int) -> bytes:
        if time.monotonic() >= self.deadline:
            raise Failure("Private backup transfer timed out; destination remains stopped.")
        return self.source.read(size)


def archive_backup(backup: Path, stream: BinaryIO, deadline: float) -> str:
    """Copy owner-readable private files without exposing them through host mounts."""
    manifest = backup / "manifest.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise Failure("A complete regular T17 backup manifest is required.")
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    paths = sorted(backup.rglob("*"))
    required_bytes = sum(path.lstat().st_size + 1024 for path in paths) + 1024 * 1024
    if shutil.disk_usage(tempfile.gettempdir()).free < required_bytes:
        raise Failure("Insufficient temporary disk for private backup transfer; preserve all data.")
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for path in paths:
            if time.monotonic() >= deadline:
                raise Failure("Private backup transfer timed out; destination remains stopped.")
            before = path.lstat()
            if (
                stat.S_ISLNK(before.st_mode)
                or not (stat.S_ISREG(before.st_mode) or stat.S_ISDIR(before.st_mode))
                or (stat.S_ISREG(before.st_mode) and before.st_nlink != 1)
            ):
                raise Failure("Backup contains an unsafe file; preserve it and inspect locally.")
            info = archive.gettarinfo(str(path), arcname=str(path.relative_to(backup)))
            info.uid = info.gid = 10001
            info.uname = info.gname = ""
            info.mode = 0o700 if info.isdir() else 0o600
            if info.isfile():
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "rb") as source:
                    current = os.fstat(source.fileno())
                    if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                        before.st_dev,
                        before.st_ino,
                        before.st_size,
                        before.st_mtime_ns,
                    ):
                        raise Failure(
                            "Backup changed during transfer; preserve it and retry fresh."
                        )
                    archive.addfile(info, cast(BinaryIO, DeadlineReader(source, deadline)))
                    after = os.fstat(source.fileno())
                    if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
                        raise Failure(
                            "Backup changed during transfer; preserve it and retry fresh."
                        )
            else:
                archive.addfile(info)
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != digest:
        raise Failure("Backup manifest changed during transfer; preserve it and retry fresh.")
    stream.seek(0)
    return digest


class Failure(Exception):
    """An actionable error safe to display without engine output or secrets."""


@dataclass(frozen=True)
class RuntimeSpec:
    name: str
    executable: str
    endpoint: str
    identity: str = ""


@dataclass(frozen=True)
class Manifest:
    schema_version: int
    install_id: str
    runtime: RuntimeSpec
    container_name: str
    volume_name: str
    image: str
    port: int
    origin: str
    url: str
    data_dir: str


def default_install_dir() -> Path:
    return Path.home() / ".local/share/internship-pipeline"


def validate_image(image: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@-]*", image):
        raise Failure("Use an explicit versioned image reference, with no whitespace or options.")
    if "@" in image:
        if not re.search(r"@sha256:[0-9a-f]{64}$", image):
            raise Failure("Image digests must be a complete sha256 digest.")
    else:
        tag = image.rsplit("/", 1)[-1].partition(":")[2]
        if not tag or tag.lower() in {"latest", "local", "main", "master", "edge", "dev"}:
            raise Failure(
                "Supply a release version tag or sha256 digest; no mutable default is used."
            )


def validate_runtime(spec: RuntimeSpec) -> None:
    if (
        not all(
            isinstance(value, str)
            for value in (spec.name, spec.executable, spec.endpoint, spec.identity)
        )
        or spec.name not in {"docker", "podman"}
        or not Path(spec.executable).is_absolute()
    ):
        raise Failure("Manifest runtime is invalid; inspect the installation manifest.")
    parsed = urlsplit(spec.endpoint)
    if spec.name == "docker":
        valid = parsed.scheme == "unix" and not parsed.netloc and parsed.path.startswith("/")
    else:
        valid = (
            not spec.endpoint
            or (parsed.scheme == "unix" and not parsed.netloc and parsed.path.startswith("/"))
            or (parsed.scheme == "ssh" and parsed.hostname in {"127.0.0.1", "localhost", "::1"})
        )
    if not valid:
        raise Failure(
            "Only local engine endpoints are prepared; remote engine URLs are unsupported."
        )
    if spec.identity and (
        spec.name != "podman" or parsed.scheme != "ssh" or not Path(spec.identity).is_absolute()
    ):
        raise Failure("Saved SSH identity is invalid; inspect the Podman connection.")
    if spec.name == "podman" and parsed.scheme == "ssh" and not spec.identity:
        raise Failure(
            "A local Podman machine needs an explicit saved SSH identity from its connection."
        )


def load_manifest(path: Path) -> Manifest:
    try:
        if path.is_symlink() or not path.is_file():
            raise Failure(
                f"No regular installation manifest at {path}; run the local installer first."
            )
        if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o022:
            raise Failure("Manifest must be owned by you and not writable by another user.")
        if path.stat().st_size > 65536:
            raise Failure(
                "Installation manifest exceeds its size limit; inspect the original file."
            )
        data = json.loads(path.read_text())
        data["runtime"] = RuntimeSpec(**data["runtime"])
        manifest = Manifest(**data)
        if not all(
            isinstance(value, str)
            for value in (
                manifest.install_id,
                manifest.container_name,
                manifest.volume_name,
                manifest.image,
                manifest.origin,
                manifest.url,
                manifest.data_dir,
            )
        ):
            raise ValueError("manifest string fields")
        UUID(manifest.install_id)
        validate_runtime(manifest.runtime)
        validate_image(manifest.image)
        stem = "internship-pipeline-" + manifest.install_id
        if (
            manifest.schema_version != 1
            or manifest.container_name != stem
            or manifest.volume_name != stem + "-data"
            or type(manifest.port) is not int
            or not 1024 <= manifest.port <= 65535
            or manifest.origin != f"http://localhost:{manifest.port}"
            or manifest.url != manifest.origin
            or manifest.data_dir not in {"/var/data", "/var/data/restored"}
        ):
            raise ValueError("invalid manifest fields")
        return manifest
    except Failure:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        raise Failure(
            "Invalid installation manifest; restore its original copy before proceeding."
        ) from exc


def write_manifest(path: Path, manifest: Manifest) -> None:
    # Exclusive creation leaves an interrupted installation discoverable on a rerun.
    with path.open("x") as stream:
        os.chmod(path, 0o600)
        json.dump(asdict(manifest), stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


class Runtime:
    def __init__(self, spec: RuntimeSpec):
        validate_runtime(spec)
        self.spec = spec

    def is_ready(self, container: dict[str, Any]) -> bool:
        state = container.get("State")
        if not isinstance(state, dict) or state.get("Running") is not True:
            return False
        health = state.get("Health")
        return isinstance(health, dict) and health.get("Status") == "healthy"

    @property
    def environment(self) -> dict[str, str]:
        # Freeze connection selection without changing Docker/Podman global configuration.
        return {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("DOCKER_")
            and key
            not in {
                "CONTAINER_HOST",
                "CONTAINER_CONNECTION",
                "CONTAINER_SSHKEY",
                "PODMAN_CONNECTIONS_CONF",
            }
        }

    def argv(self, *args: str) -> list[str]:
        prefix = [self.spec.executable]
        if self.spec.name == "docker":
            prefix += ["--host", self.spec.endpoint]
        elif self.spec.endpoint:
            prefix += ["--url", self.spec.endpoint]
            if self.spec.identity:
                prefix += ["--identity", self.spec.identity]
        else:
            prefix += ["--remote=false"]
        return prefix + list(args)

    def run(
        self,
        *args: str,
        timeout: float = 15,
        include_stderr: bool = False,
        stdin: BinaryIO | None = None,
    ) -> str:
        try:
            result = subprocess.run(
                self.argv(*args),
                env=self.environment,
                capture_output=True,
                text=True,
                stdin=stdin,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Failure(
                f"{self.spec.name} {args[0]} could not complete; start/check "
                f"the saved local runtime and retry."
            ) from exc
        if result.returncode:
            raise Failure(
                f"{self.spec.name} {args[0]} failed; check the saved "
                f"runtime, image access and installation resources."
            )
        if len(result.stdout) + len(result.stderr) > 2 * 1024 * 1024:
            raise Failure(
                "Runtime output exceeded the inspection limit; narrow the request and retry."
            )
        if include_stderr:
            return "\n".join(stream.strip() for stream in (result.stdout, result.stderr) if stream)
        return result.stdout.strip()

    def maintenance(self, manifest: Manifest, command: str, image_id: str) -> None:
        """Run explicit local recovery with private terminal IO and the saved image."""
        if command not in {"setup-token", "recover-owner"}:
            raise Failure("Unsupported maintenance operation.")
        if not re.fullmatch(r"(?:sha256:)?[a-f0-9]{64}", image_id):
            raise Failure("Exact installed image identity is unavailable; preserve the volume.")
        try:
            result = subprocess.run(
                self.argv(
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
                    image_id,
                    command,
                    "--data-dir",
                    manifest.data_dir,
                ),
                env=self.environment,
                timeout=600,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Failure(
                "Recovery did not complete; preserve the volume and inspect locally."
            ) from exc
        if result.returncode:
            raise Failure(
                "Recovery failed; preserve the volume and inspect locally before restart."
            )

    def check(self) -> None:
        try:
            info = json.loads(
                self.run("info", "--format", "json" if self.spec.name == "podman" else "{{json .}}")
            )
            operating_system = info.get("OSType", info.get("host", {}).get("os", ""))
            if operating_system != "linux":
                raise Failure("The installer requires a Linux container engine.")
        except (ValueError, AttributeError, TypeError) as exc:
            raise Failure("The local runtime returned invalid engine information.") from exc

    def restore(self, manifest: Manifest, backup: Path) -> str:
        """Restore privately into fresh owned storage using an exact local image ID."""
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", manifest.image):
            raise Failure("Fresh restore requires the inspected source image identity.")
        deadline = time.monotonic() + 600
        with tempfile.TemporaryFile(mode="w+b") as stream:
            digest = archive_backup(backup, stream, deadline)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Failure("Private backup transfer timed out; destination remains stopped.")
            self.run(
                "run",
                "--rm",
                "--pull",
                "never",
                "--network",
                "none",
                "--read-only",
                "--tmpfs",
                "/tmp",
                "-i",
                "--entrypoint",
                "python",
                "--mount",
                f"type=volume,src={manifest.volume_name},dst=/var/data",
                manifest.image,
                "-c",
                RESTORE_STREAM,
                digest,
                timeout=remaining,
                stdin=stream,
            )
        return digest

    def _inspect(
        self, kind: str, name: str, deadline: float | None = None
    ) -> dict[str, Any] | None:
        # A failed inspect is not evidence of absence: enumerate names first.
        listing = (
            ("ps", "-a", "--format", "{{.Names}}")
            if kind == "container"
            else ("volume", "ls", "--format", "{{.Name}}")
        )

        def budget() -> float:
            remaining = 15 if deadline is None else min(15, deadline - time.monotonic())
            if remaining <= 0:
                raise Failure("Setup readiness timed out; inspect status/logs. Data is retained.")
            return remaining

        names = self.run(*listing, timeout=budget()).splitlines()
        if name not in names:
            return None
        args = ("inspect", name) if kind == "container" else ("volume", "inspect", name)
        try:
            values = json.loads(self.run(*args, timeout=budget()))
            if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
                raise ValueError("inspect shape")
            return values[0]
        except (ValueError, TypeError) as exc:
            raise Failure("Runtime inspection returned invalid resource information.") from exc

    def inspect_volume(
        self, manifest: Manifest, deadline: float | None = None
    ) -> dict[str, Any] | None:
        volume = self._inspect("volume", manifest.volume_name, deadline)
        if volume is not None and (
            not isinstance(volume.get("Labels"), dict)
            or volume["Labels"].get(LABEL) != manifest.install_id
        ):
            raise Failure(
                "Volume ownership does not match; leave this resource "
                "untouched and inspect the manifest."
            )
        return volume

    def inspect_container(
        self, manifest: Manifest, deadline: float | None = None
    ) -> dict[str, Any] | None:
        container = self._inspect("container", manifest.container_name, deadline)
        if container is None:
            return None
        config = container.get("Config")
        mounts = container.get("Mounts")
        host = container.get("HostConfig")
        state = container.get("State")
        if (
            not isinstance(config, dict)
            or not isinstance(config.get("Labels"), dict)
            or not isinstance(mounts, list)
            or not all(isinstance(mount, dict) for mount in mounts)
            or not isinstance(host, dict)
            or not isinstance(host.get("PortBindings"), dict)
            or not isinstance(state, dict)
            or (state.get("Health") is not None and not isinstance(state["Health"], dict))
        ):
            raise Failure(
                "Container inspection fields are malformed; leave the resource untouched."
            )
        bindings = host["PortBindings"]
        expected = [{"HostIp": "127.0.0.1", "HostPort": str(manifest.port)}]
        data_mounts = [
            mount
            for mount in mounts
            if isinstance(mount.get("Destination"), str)
            and (
                mount["Destination"] == "/var/data" or mount["Destination"].startswith("/var/data/")
            )
        ]
        environment = config.get("Env")
        if (
            (config.get("Labels") or {}).get(LABEL) != manifest.install_id
            or config.get("Image") != manifest.image
            or len(data_mounts) != 1
            or data_mounts[0].get("Name") != manifest.volume_name
            or data_mounts[0].get("Destination") != "/var/data"
            or bindings.get("8080/tcp") != expected
            or not isinstance(environment, list)
            or [
                entry
                for entry in environment
                if isinstance(entry, str) and entry.startswith("PIPELINE_DATA_DIR=")
            ]
            != [f"PIPELINE_DATA_DIR={manifest.data_dir}"]
            or [
                entry
                for entry in environment
                if isinstance(entry, str) and entry.startswith("PIPELINE_CONFIG=")
            ]
            != [f"PIPELINE_CONFIG={manifest.data_dir}/config/settings.yaml"]
        ):
            raise Failure(
                "Container ownership, image, storage or loopback port "
                "differs from the manifest; leave it untouched."
            )
        return container

    def require_owned(self, manifest: Manifest, deadline: float | None = None) -> dict[str, Any]:
        if self.inspect_volume(manifest, deadline) is None:
            raise Failure(
                "Saved data volume is missing; restore it before starting the installation."
            )
        container = self.inspect_container(manifest, deadline)
        if container is None:
            raise Failure(
                "Saved container is missing; use the same local installer "
                "and manifest to recover it."
            )
        return container


def discover_runtime(name: str) -> RuntimeSpec:
    executable = shutil.which(name)
    if executable is None:
        raise Failure(
            f"{name} is not installed; install/start a local Docker or Podman engine and retry."
        )
    executable = str(Path(executable).absolute())
    try:
        identity = ""
        if name == "docker":
            endpoint = os.environ.get("DOCKER_HOST", "")
            context = os.environ.get("DOCKER_CONTEXT", "")
            if context or not endpoint:
                command = [executable, "context", "inspect"] + ([context] if context else [])
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=10, check=True
                )
                endpoint = json.loads(result.stdout)[0]["Endpoints"]["docker"]["Host"]
        else:
            endpoint = os.environ.get("CONTAINER_HOST", "")
            connection = os.environ.get("CONTAINER_CONNECTION", "")
            if not endpoint:
                result = subprocess.run(
                    [executable, "system", "connection", "list", "--format", "json"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                )
                entries = json.loads(result.stdout)
                selected = (
                    [entry for entry in entries if entry.get("Name") == connection]
                    if connection
                    else [entry for entry in entries if entry.get("Default")]
                )
                if connection and len(selected) != 1:
                    raise Failure("The selected Podman connection does not exist.")
                if len(selected) > 1:
                    raise Failure(
                        "Podman has several default connections; select one before retrying."
                    )
                endpoint = selected[0]["URI"] if selected else ""
                identity = selected[0].get("Identity", "") if selected else ""
            else:
                identity = os.environ.get("CONTAINER_SSHKEY", "")
        spec = RuntimeSpec(name, executable, endpoint, identity)
        Runtime(spec).check()
        return spec
    except Failure:
        raise
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError) as exc:
        raise Failure(f"{name} is unavailable; start its existing local engine and retry.") from exc


def wait_ready(runtime: Runtime, manifest: Manifest, timeout: float = 60) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        container = runtime.require_owned(manifest, deadline)
        state = container.get("State") or {}
        if runtime.is_ready(container):
            return container
        if not state.get("Running"):
            raise Failure(
                "Container stopped before setup readiness; inspect "
                "status/logs, then retry without deleting data."
            )
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise Failure(
        "Setup readiness timed out; inspect status/logs and retry the same "
        "installation. Data is retained."
    )
