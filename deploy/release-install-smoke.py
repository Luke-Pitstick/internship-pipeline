"""Exercise downloaded RC1 installers on disposable GitHub-hosted Linux runners.

This is release acceptance tooling, never a user's upgrade/cleanup command. It
prints only aggregate results; the runner owns all synthetic data until teardown.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import platform
import re
import subprocess
import tarfile
import time
from pathlib import Path

VERSION = "v0.1.0-rc.1"
IMAGE = ("ghcr.io/luke-pitstick/internship-pipeline@sha256:"
         "616d882df67a978a8b7fd798d90cb6e4634caa03a4e63ffb09cb973f9788130d")
LAUNCHER_SHA = "465efd89cae5d9753be6d2b85c3d5c329835f0931fc11549a76fa8cdeb3cdd1f"
BOOTSTRAP_SHA = "431a9dc06b838fb93d94a698226ba6e6edc86772c4b1586566216b1c9c0fcca2"
BUNDLE_SHA = "f80065ecc64a79af323e47c7431b8da9934b75f8ce0cbbc8017d535184c9ec53"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load acceptance helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command(*argv: str, data: bytes | None = None, timeout: int = 660) -> bytes:
    result = subprocess.run(argv, input=data, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        # Installer/engine output can contain first-run credentials. Never print it.
        raise RuntimeError(f"Acceptance command {Path(argv[0]).name} failed ({result.returncode})")
    return result.stdout


def checked_file(path: Path, expected: str) -> bytes:
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected:
        raise RuntimeError(f"Unaccepted release asset: {path.name}")
    return content


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("docker", "podman"), required=True)
    parser.add_argument("--delivery", choices=("authenticated-bundle", "public-launcher"),
                        required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true" or platform.system() != "Linux":
        raise RuntimeError("Run only on an isolated GitHub-hosted Linux runner")
    os.umask(0o077)
    args.work.mkdir(mode=0o700)  # Refuse reuse rather than adopting existing resources.
    root = args.work.resolve()
    assets = args.assets.resolve()
    checked_file(assets / "install.sh", LAUNCHER_SHA)
    checked_file(assets / "bootstrap_installer.py", BOOTSTRAP_SHA)
    bundle = checked_file(assets / f"internship-pipeline-installer-{VERSION}.tar.gz", BUNDLE_SHA)
    smoke = load("container_smoke", Path(__file__).with_name("container-smoke.py"))
    smoke.ENGINE = args.engine
    bootstrap = load("released_bootstrap", assets / "bootstrap_installer.py")
    extracted = root / "bundle"
    extracted.mkdir()
    local_launcher = bootstrap.unpack(bundle, extracted, VERSION) / "install.sh"
    launcher = assets / "install.sh" if args.delivery == "public-launcher" else local_launcher
    base = ["sh", str(launcher)]
    source = root / "source"
    source_command = root / "source-command"
    restored = root / "restored"
    restored_command = root / "restored-command"
    first = [*base, "--runtime", args.engine, "--install-dir", str(source),
             "--command-dir", str(source_command), "--port", "18080"]
    if args.delivery == "authenticated-bundle":
        first += ["--image", IMAGE]
    started = time.monotonic()
    command(*first)
    installed_seconds = round(time.monotonic() - started, 3)
    manifest = json.loads((source / "installation.json").read_text())
    smoke.require(manifest["image"] == IMAGE, "Installer selected another image")
    container, volume = manifest["container_name"], manifest["volume_name"]
    image_id = smoke.docker("inspect", "--format", "{{.Image}}", container)
    manager = str(source_command / "internship-pipeline")
    browser = smoke.Browser(manifest["origin"])
    smoke.ready(browser, "setup")
    smoke.healthy(container)
    smoke.require(browser.request("/")[0] == 200, "Frontend unavailable")
    smoke.require(browser.request("/api/jobs")[0] == 401, "Jobs exposed before claim")
    tokens = re.findall(r"Owner setup token: (\S+)", smoke.docker("logs", container))
    smoke.require(len(tokens) == 1, "Missing unique setup token")
    credentials = {"username": "synthetic-owner", "password": "synthetic-release-password"}
    csrf = browser.json("/api/session")["csrf"]
    csrf = browser.json("/api/claim", {**credentials, "setup_token": tokens[0]}, csrf)["csrf"]
    browser.json("/api/onboarding/checkpoint", {"step": "models", "defer_models": True}, csrf)
    command(manager, "status")
    command(manager, "url")
    command(manager, "logs", "--lines", "10")
    command(manager, "stop")
    smoke.stopped(container)
    # Both reruns use the released entry point and must preserve the manifest.
    rerun = [*base, "--install-dir", str(source), "--command-dir", str(source_command)]
    command(*rerun)
    smoke.ready(browser, "owner")
    smoke.require(json.loads((source / "installation.json").read_text()) == manifest,
                  "Rerun changed installation identity")
    smoke.require(browser.json("/api/session")["authenticated"], "Restart lost owner session")
    command(manager, "stop")

    # The existing recovery fixture writes only synthetic secrets and disabled transports.
    fixture = Path(__file__).with_name("container-recovery-fixture.py").read_bytes()
    def maintenance(volume_name: str, *argv: str, data: bytes | None = None) -> bytes:
        return command(args.engine, "run", "--rm", "-i", "--pull", "never", "--network", "none",
                       "--read-only", "--tmpfs", "/tmp", "--entrypoint", "python", "--mount",
                       f"type=volume,src={volume_name},dst=/var/data", image_id, *argv, data=data)

    metrics = json.loads(maintenance(volume, "-", "seed", data=fixture))
    interrupted = container + "-interrupted"
    fixture_path = Path(__file__).with_name("container-recovery-fixture.py").resolve()
    smoke.docker("run", "--detach", "--name", interrupted, "--pull", "never", "--network",
                 "none", "--read-only", "--tmpfs", "/tmp", "--entrypoint", "python",
                 "--mount", f"type=volume,src={volume},dst=/var/data", "--mount",
                 f"type=bind,src={fixture_path},dst=/fixture.py,readonly", image_id,
                 "/fixture.py", "interrupt")
    deadline = time.monotonic() + 25
    while "CHECKPOINT_PERSISTED" not in smoke.docker("logs", interrupted):
        if time.monotonic() > deadline:
            raise RuntimeError("Synthetic worker did not persist its checkpoint")
        time.sleep(0.25)
    smoke.docker("kill", "--signal", "SIGKILL", interrupted)
    smoke.require(smoke.docker("wait", interrupted) == "137", "Worker was not interrupted")
    maintenance(volume, "-", "resume", data=fixture)
    backup_volume = container + "-backup"
    smoke.docker("volume", "create", "--label",
                 f"io.internship-pipeline.install-id={manifest['install_id']}", backup_volume)
    maintenance(backup_volume, "-c",
                "from pathlib import Path; Path('/var/data/backup').mkdir(mode=0o700)")
    command(args.engine, "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
            "--tmpfs", "/tmp", "--entrypoint", "internship-pipeline", "--mount",
            f"type=volume,src={volume},dst=/var/data", "--mount",
            f"type=volume,src={backup_volume},dst=/recovery", image_id, "backup",
            "/recovery/backup/snapshot", "--data-dir", "/var/data")
    archive = maintenance(backup_volume, "-c", "import sys,tarfile; "
                          "t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|'); "
                          "t.add('/var/data/backup/snapshot',arcname='snapshot'); t.close()")
    backup_parent = root / "backups"
    backup_parent.mkdir(mode=0o700)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        if any(not (item.isfile() or item.isdir()) for item in tar.getmembers()):
            raise RuntimeError("Backup contained nonregular members")
        tar.extractall(backup_parent, filter="data")
    backup = backup_parent / "snapshot"
    backup.chmod(0o700)
    backup_hashes = {str(p.relative_to(backup)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in backup.rglob("*") if p.is_file()}
    command(*base, "--restore-source", str(source), "--restore-from", str(backup),
            "--install-dir", str(restored), "--command-dir", str(restored_command),
            "--port", "18081")
    destination = json.loads((restored / "installation.json").read_text())
    smoke.require(destination["image"] == image_id, "Restore changed exact local image")
    smoke.require(destination["volume_name"] != volume, "Restore reused source volume")
    smoke.require(destination["data_dir"] == "/var/data/restored", "Restore used wrong root")
    recovered = smoke.Browser(destination["origin"])
    smoke.ready(recovered, "owner")
    session = recovered.json("/api/session")
    smoke.require(session["claimed"] and not session["authenticated"], "Invalid restored identity")
    recovered.json("/api/login", credentials, session["csrf"])
    smoke.require(len(recovered.json("/api/jobs")["jobs"]) == 1,
                  "Restored job missing or duplicated")
    recovered_manager = str(restored_command / "internship-pipeline")
    command(recovered_manager, "status")
    command(recovered_manager, "stop")
    maintenance(destination["volume_name"], "-", "verify", "--root", "/var/data/restored",
                data=fixture)
    command(recovered_manager, "start")
    smoke.ready(recovered, "owner")
    command(recovered_manager, "stop")
    smoke.stopped(container)
    smoke.require(json.loads((source / "installation.json").read_text()) == manifest,
                  "Restore modified source manifest")
    smoke.require(backup_hashes == {
        str(p.relative_to(backup)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in backup.rglob("*") if p.is_file()}, "Restore modified host backup")
    # Preserve actual runtime license/source inventory for review, not a legal-clearance assertion.
    inventory = maintenance(volume, "-c", "import pathlib,subprocess,json; "
        "print(json.dumps({'debian':subprocess.check_output(['dpkg-query','-W',"
        "'-f=${binary:Package}\\t${Version}\\t${source:Package}\\t${source:Version}\\n'],text=True),"
        "'project_license':pathlib.Path('/app/LICENSE').read_text(),"
        "'frontend_notices':pathlib.Path('/app/web/build/third-party-licenses.md').read_text()}))")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.with_suffix(".notices.json").write_bytes(inventory)
    args.report.write_text(json.dumps({
        "version": VERSION, "image": IMAGE, "config_digest": image_id,
        "engine": args.engine, "architecture": platform.machine(), "delivery": args.delivery,
        "install_seconds": installed_seconds, "synthetic_pdf_metrics": metrics,
        "passed": ["asset_hashes", "fresh_install", "owner_claim", "saved_rerun", "management",
                   "stopped_backup", "fresh_installer_restore", "restored_login", "synthetic_job",
                   "encrypted_connections_and_pdf", "source_and_backup_preserved", "image_notices"],
        "live_providers": False, "unfamiliar_operator": False,
    }, indent=2) + "\n")
    print(f"PASS {args.engine}/{platform.machine()} {args.delivery}: "
          "install, owner, rerun, backup, restore")


if __name__ == "__main__":
    main()
