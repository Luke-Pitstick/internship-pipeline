"""Isolated real-engine acceptance; prints no setup tokens, cookies, or passwords."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import platform
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ENGINE = "docker"


class SmokeFailure(RuntimeError):
    pass


def docker(*args: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            [ENGINE, *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        raise SmokeFailure(f"{ENGINE.title()} {args[0]} exceeded {timeout}s") from None
    except FileNotFoundError:
        raise SmokeFailure(f"{ENGINE.title()} CLI is not installed") from None
    if result.returncode:
        # Commands and engine output can include private setup logs; never echo them.
        raise SmokeFailure(f"{ENGINE.title()} {args[0]} failed (exit {result.returncode})")
    return result.stdout.strip()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


class Browser:
    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def request(self, path: str, body: dict | None = None, csrf: str = "") -> tuple[int, bytes]:
        headers = {"Origin": self.origin}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        if csrf:
            headers["X-CSRF-Token"] = csrf
        request = urllib.request.Request(
            urllib.parse.urljoin(self.origin + "/", path), data=data, headers=headers
        )
        try:
            with self.opener.open(request, timeout=3) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as response:
            return response.code, response.read()

    def json(self, path: str, body: dict | None = None, csrf: str = "") -> dict:
        status, data = self.request(path, body, csrf)
        require(status == 200, f"HTTP {path} returned {status}; expected 200")
        return json.loads(data)


def ready(browser: Browser, mode: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            status, data = browser.request("/readyz")
            if status == 200 and json.loads(data) == {"ready": True, "mode": mode}:
                return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.5)
    raise SmokeFailure(f"Readiness did not recover in {mode} mode within 60s")


def stopped(container: str) -> None:
    state = json.loads(docker("inspect", "--format", "{{json .State}}", container))
    require(not state["Running"], "Container is still running")
    require(state["ExitCode"] == 0 and not state["OOMKilled"], "Shutdown was not clean")


def healthy(container: str) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if docker("inspect", "--format", "{{.State.Health.Status}}", container) == "healthy":
            return
        time.sleep(0.5)
    state = json.loads(docker("inspect", "--format", "{{json .State}}", container))
    health = state.get("Health") or {}
    status = health.get("Status")
    print("Health diagnostic: " + json.dumps({
        "running": state.get("Running") is True,
        "status": status if status in {"healthy", "unhealthy", "starting"} else "unknown",
        "recorded_checks": len(health.get("Log") or []),
    }), flush=True)
    if ENGINE == "podman":
        try:
            docker("healthcheck", "run", container, timeout=10)
        except SmokeFailure:
            print("Health diagnostic: explicit Podman image probe failed", flush=True)
        else:
            print("Health diagnostic: explicit Podman image probe passed", flush=True)
    raise SmokeFailure("Image healthcheck did not become healthy within 45s")


def recovery_acceptance(
    image: str, name: str, volume: str, browser: Browser, credentials: dict, payload: dict,
    origin: str, containers: list[str], volumes: list[str], metrics: dict,
) -> None:
    fixture = Path(__file__).with_name("container-recovery-fixture.py").resolve()
    mount = f"type=bind,src={fixture},dst=/fixture.py,readonly"
    common = ["--init", "--read-only", "--tmpfs", "/tmp", "--network", "none"]
    data_mount = f"type=volume,src={volume},dst=/var/data"

    def command(*args: str, mounts: list[str], timeout: int = 45) -> str:
        options = ["run", "--rm", *common, "--entrypoint", "python"]
        for item in mounts:
            options.extend(["--mount", item])
        return docker(*options, image, *args, timeout=timeout)

    rendered = command("/fixture.py", "seed", mounts=[mount, data_mount], timeout=60)
    metrics.update(json.loads(rendered))
    interrupted = name + "-interrupted"
    containers.append(interrupted)
    docker("run", "--detach", "--name", interrupted, *common, "--entrypoint", "python",
           "--mount", mount, "--mount", data_mount, image, "/fixture.py", "interrupt")
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if "CHECKPOINT_PERSISTED" in docker("logs", interrupted):
            break
        time.sleep(0.25)
    else:
        raise SmokeFailure("Synthetic collection did not reach persisted checkpoint")
    docker("kill", "--signal", "SIGKILL", interrupted)
    require(docker("wait", interrupted, timeout=15) == "137",
            "Interrupted container did not exit from SIGKILL")
    state = json.loads(docker("inspect", "--format", "{{json .State}}", interrupted))
    require(not state["OOMKilled"], "Interrupted worker was OOM killed")
    command("/fixture.py", "resume", mounts=[mount, data_mount])
    print("PASS actual container SIGKILL after fetch; checkpoint resumed without refetch",
          flush=True)

    recovered_volume = name + "-recovery"
    docker("volume", "create", recovered_volume)
    volumes.append(recovered_volume)
    # Populate the new volume from the image's owned /var/data before its second mount.
    recovery_data = f"type=volume,src={recovered_volume},dst=/var/data"
    command("-c", "import os; assert os.stat('/var/data').st_uid==10001",
            mounts=[recovery_data])
    recovery_mount = f"type=volume,src={recovered_volume},dst=/recovery"
    command("-m", "internship_pipeline.cli", "backup", "/recovery/backup", "--data-dir",
            "/var/data", mounts=[data_mount, recovery_mount])
    command("-m", "internship_pipeline.cli", "restore", "/var/data/backup",
            "/var/data/restored", mounts=[recovery_data])
    command("/fixture.py", "verify", "--root", "/var/data/restored",
            mounts=[mount, recovery_data])
    restored_container = name + "-restored"
    containers.append(restored_container)
    # Original container is stopped, so reuse its loopback port/origin with its old cookie.
    port = urllib.parse.urlsplit(origin).port
    docker("run", "--detach", "--name", restored_container, "--init", "--read-only",
           "--tmpfs", "/tmp", "--publish", f"127.0.0.1:{port}:8080", "--env",
           f"PIPELINE_ORIGIN={origin}", "--env", "PIPELINE_DATA_DIR=/var/data/restored",
           "--mount", recovery_data, image)
    ready(browser, "owner")
    healthy(restored_container)
    require(not browser.json("/api/session")["authenticated"],
            "Restore retained a browser session")
    session = browser.json("/api/session")
    require(session["claimed"], "Restore lost owner identity")
    require(browser.request("/api/claim", payload, session["csrf"])[0] == 400,
            "Restore reopened first-run claim")
    browser.json("/api/login", credentials, session["csrf"])
    setup = browser.json("/api/onboarding")
    require(setup["defer_models"] and "models" in setup["reviewed"],
            "Restore lost guided setup progress")
    require(len(browser.json("/api/jobs")["jobs"]) == 1, "Restore duplicated or lost jobs")
    require("Owner setup token:" not in docker("logs", restored_container),
            "Restore produced a first-run setup token")
    docker("stop", "--time", "45", restored_container, timeout=55)
    stopped(restored_container)
    command("/fixture.py", "verify", "--root", "/var/data/restored",
            mounts=[mount, recovery_data])
    print("PASS stopped backup/fresh-volume restore: keys, PDF, owner, revoked sessions, "
          "uncertain work review and confirmed delivery/Sheets state without replay", flush=True)


def run(build_timeout: int, *, existing_image: str = "", expected_platform: str = "",
        recovery: bool = False, report_path: Path | None = None) -> None:
    docker("info", "--format", "{{json .}}", timeout=15)
    version = docker("version", "--format", "{{json .}}", timeout=15)
    print(f"Engine: {ENGINE}; host {platform.node()}; {platform.system()}/{platform.machine()}",
          flush=True)
    metrics: dict = {"host": platform.node(), "host_os": platform.platform(),
                     "engine": ENGINE, "engine_version": json.loads(version),
                     "pull_seconds": None, "run_memory": None,
                     "render_peak_memory": None}
    name = f"pipeline-t03-{uuid.uuid4().hex[:12]}"
    image, volume = existing_image or f"{name}:smoke", f"{name}-data"
    container_created = volume_created = image_created = False
    additional_containers: list[str] = []
    additional_volumes: list[str] = []
    try:
        if not existing_image:
            print(f"Building {image} (bounded to {build_timeout}s)", flush=True)
            docker("build", "--tag", image, str(Path(__file__).resolve().parents[1]),
                   timeout=build_timeout)
            image_created = True
        metadata = json.loads(docker("image", "inspect", "--format", "{{json .}}", image))
        actual_platform = f"{metadata['Os']}/{metadata['Architecture']}"
        require(not expected_platform or actual_platform == expected_platform,
                "Image platform differs from requested platform")
        metrics.update(image_id=metadata["Id"], image_bytes=metadata["Size"],
                       image_platform=actual_platform)
        print(f"PASS image: {metadata['Id']}; {actual_platform}", flush=True)
        docker("volume", "create", volume)
        volume_created = True
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            port = available.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        container_created = True
        start_at = time.monotonic()
        docker(
            "run", "--detach", "--name", name, "--init", "--read-only", "--tmpfs", "/tmp",
            "--publish", f"127.0.0.1:{port}:8080", "--env", f"PIPELINE_ORIGIN={origin}",
            "--mount", f"type=volume,src={volume},dst=/var/data", image,
        )
        browser = Browser(origin)
        ready(browser, "setup")
        docker("exec", name, "python", "-c",
               "import json; assert json.load(open('/var/data/supervisor.json'))['roles']==[]")
        metrics["start_to_setup_seconds"] = round(time.monotonic() - start_at, 3)
        metrics["idle_memory"] = docker("stats", "--no-stream", "--format",
                                        "{{.MemUsage}}", name, timeout=15)
        healthy(name)
        status, html = browser.request("/")
        require(status == 200 and b"_app/" in html, "Built frontend did not serve")
        assets = re.findall(rb'(?:src|href)="([^" ]*\/_app/[^" ]+)"', html)
        require(bool(assets), "Built frontend asset references were absent")
        for asset in assets:
            require(browser.request(asset.decode())[0] == 200, "Frontend asset did not serve")
        require(browser.json("/healthz") == {"alive": True}, "Liveness failed")
        for path in ("/api/jobs", "/api/status", "/api/resumes/unknown", "/api/onboarding"):
            require(browser.request(path)[0] == 401, f"Private endpoint {path} was public")
        print("PASS one-port built frontend/API, setup readiness, anonymous denial", flush=True)
        logs = docker("logs", name)
        tokens = re.findall(r"Owner setup token: (\S+)", logs)
        require(len(tokens) == 1, "Expected exactly one first-boot setup token")
        token = tokens[0]
        credentials = {"username": "synthetic-owner", "password": "synthetic-smoke-password"}
        payload = {**credentials, "setup_token": token}
        csrf = browser.json("/api/session")["csrf"]
        csrf = browser.json("/api/claim", payload, csrf)["csrf"]
        require(browser.request("/api/claim", payload, csrf)[0] == 400, "Claim was reusable")
        require(browser.json("/api/jobs")["jobs"] == [], "Fresh synthetic volume was not empty")
        roles = browser.json("/api/status")["worker_roles"]
        require(set(roles) <= {"web", "search-runs", "email-delivery", "sheets-sync"},
                "Fresh owner installation activated a model or live collection worker")
        browser.json("/api/logout", {}, csrf)
        require(browser.request("/api/jobs")[0] == 401, "Logout did not revoke access")
        csrf = browser.json("/api/session")["csrf"]
        require(browser.request("/api/login", {**credentials, "password": "wrong"}, csrf)[0]
                == 401, "Wrong password was accepted")
        csrf = browser.json("/api/login", credentials, csrf)["csrf"]
        print("PASS single-use claim, login, logout", flush=True)
        require(browser.request("/setup/")[0] == 200, "Built guided setup page did not serve")
        require(browser.json("/api/onboarding")["step"] == "models",
                "Fresh guided setup did not begin with model choices")
        setup = browser.json("/api/onboarding/checkpoint",
                             {"step": "models", "defer_models": True}, csrf)
        require(setup["step"] == "profile" and setup["defer_models"],
                "Guided setup did not persist explicit model deferral")
        # Execute as the image's ordinary user; prove the actual volume and both DBs writable.
        write = (
            "import os,sqlite3; from pathlib import Path; "
            "assert os.getuid()==10001; root=Path('/var/data'); "
            "assert all((root/n).stat().st_uid==10001 "
            "for n in ('identity.sqlite3','state.sqlite3')); "
            "db=sqlite3.connect(root/'state.sqlite3'); "
            "db.execute('CREATE TABLE t03_smoke (value TEXT)'); "
            "db.execute(\"INSERT INTO t03_smoke VALUES ('synthetic-persistent-marker')\"); "
            "db.commit(); db.close()"
        )
        docker("exec", name, "python", "-c", write)
        print("PASS non-root UID 10001, volume ownership and SQLite write", flush=True)
        docker("stop", "--time", "45", name, timeout=55)
        stopped(name)
        print("PASS SIGTERM graceful stop (exit 0, no OOM)", flush=True)
        docker("start", name)
        ready(browser, "owner")
        healthy(name)
        require(browser.json("/api/session")["authenticated"], "Owner session did not persist")
        setup = browser.json("/api/onboarding")
        require(setup["step"] == "profile" and "models" in setup["reviewed"],
                "Restart lost guided setup progress")
        guest = Browser(origin)
        session = guest.json("/api/session")
        require(session["claimed"] and not session["authenticated"], "Owner did not persist")
        require(guest.request("/api/claim", payload, session["csrf"])[0] == 400,
                "Restart reopened claim")
        require(len(re.findall(r"Owner setup token:", docker("logs", name))) == 1,
                "Restart issued another setup token")
        check = (
            "import sqlite3; db=sqlite3.connect('/var/data/state.sqlite3'); "
            "assert db.execute('SELECT value FROM t03_smoke').fetchone()[0]"
            "=='synthetic-persistent-marker'; db.close()"
        )
        docker("exec", name, "python", "-c", check)
        require(browser.request("/")[0] == 200, "Frontend failed after restart")
        browser.json("/api/jobs")
        print("PASS same-volume restart: owner, data, session, closed claim and readiness",
              flush=True)
        docker("kill", "--signal", "SIGINT", name)
        require(docker("wait", name, timeout=45) == "0", "SIGINT exit was not zero")
        stopped(name)
        print("PASS SIGINT graceful stop (exit 0, no OOM)", flush=True)
        if recovery:
            recovery_acceptance(image, name, volume, browser, credentials, payload, origin,
                                additional_containers, additional_volumes, metrics)
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(metrics, indent=2) + "\n")
    finally:
        failures = []
        resources = []
        if container_created:
            resources.append(("container", ("rm", "--force", name)))
        for additional in additional_containers:
            resources.append(("container", ("rm", "--force", additional)))
        if volume_created:
            resources.append(("volume", ("volume", "rm", volume)))
        for additional in additional_volumes:
            resources.append(("volume", ("volume", "rm", additional)))
        if image_created:
            resources.append(("image tag", ("image", "rm", image)))
        for kind, command in resources:
            try:
                docker(*command)
            except SmokeFailure:
                failures.append(f"{kind}: {command[-1]}")
        if failures:
            raise SmokeFailure("Cleanup needs attention for own resources: " + "; ".join(failures))
        if resources:
            print("PASS cleaned own created resources", flush=True)


def main() -> int:
    global ENGINE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-timeout", type=int, default=1200)
    parser.add_argument("--engine", choices=["docker", "podman"], default="docker")
    parser.add_argument("--image", default="",
                        help="Smoke a local image without building/removing it")
    parser.add_argument("--platform", default="", choices=["", "linux/amd64", "linux/arm64"])
    parser.add_argument("--recovery", action="store_true",
                        help="Also test T17 interrupted recovery")
    parser.add_argument("--report", type=Path, help="Write sanitized host/image measurements")
    args = parser.parse_args()
    if args.build_timeout < 1:
        parser.error("--build-timeout must be positive")
    ENGINE = args.engine
    try:
        run(args.build_timeout, existing_image=args.image, expected_platform=args.platform,
            recovery=args.recovery, report_path=args.report)
    except (SmokeFailure, OSError, ValueError, KeyError) as exc:
        print(f"BLOCKED/FAILED: {exc}", file=sys.stderr)
        return 1
    print("PASS actual single-container acceptance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
