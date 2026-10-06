"""Isolated real-engine acceptance; prints no setup tokens, cookies, or passwords."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
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


class SmokeFailure(RuntimeError):
    pass


def docker(*args: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        raise SmokeFailure(f"Docker {args[0]} exceeded {timeout}s") from None
    except FileNotFoundError:
        raise SmokeFailure("Docker CLI is not installed") from None
    if result.returncode:
        # Commands and engine output can include private setup logs; never echo them.
        raise SmokeFailure(f"Docker {args[0]} failed (exit {result.returncode})")
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


def run(build_timeout: int) -> None:
    engine = json.loads(docker("info", "--format", "{{json .}}", timeout=15))
    print(
        f"Engine: {engine['OperatingSystem']}; Docker {engine['ServerVersion']}; "
        f"{engine['OSType']}/{engine['Architecture']}", flush=True
    )
    name = f"pipeline-t03-{uuid.uuid4().hex[:12]}"
    image, volume = f"{name}:smoke", f"{name}-data"
    container_created = volume_created = image_created = False
    try:
        print(f"Building {image} (bounded to {build_timeout}s)", flush=True)
        docker("build", "--tag", image, str(Path(__file__).resolve().parents[1]),
               timeout=build_timeout)
        image_created = True
        print(f"PASS build: {docker('image', 'inspect', '--format', '{{.Id}}', image)}",
              flush=True)
        docker("volume", "create", volume)
        volume_created = True
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            port = available.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        container_created = True
        docker(
            "run", "--detach", "--name", name, "--init", "--read-only", "--tmpfs", "/tmp",
            "--publish", f"127.0.0.1:{port}:8080", "--env", f"PIPELINE_ORIGIN={origin}",
            "--mount", f"type=volume,src={volume},dst=/var/data", image,
        )
        browser = Browser(origin)
        ready(browser, "setup")
        status, html = browser.request("/")
        require(status == 200 and b"_app/" in html, "Built frontend did not serve")
        assets = re.findall(rb'(?:src|href)="([^" ]*\/_app/[^" ]+)"', html)
        require(bool(assets), "Built frontend asset references were absent")
        for asset in assets:
            require(browser.request(asset.decode())[0] == 200, "Frontend asset did not serve")
        require(browser.json("/healthz") == {"alive": True}, "Liveness failed")
        for path in ("/api/jobs", "/api/status", "/api/resumes/unknown"):
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
        require(browser.json("/api/status")["worker_roles"] == [], "Setup activated workers")
        browser.json("/api/logout", {}, csrf)
        require(browser.request("/api/jobs")[0] == 401, "Logout did not revoke access")
        csrf = browser.json("/api/session")["csrf"]
        require(browser.request("/api/login", {**credentials, "password": "wrong"}, csrf)[0]
                == 401, "Wrong password was accepted")
        browser.json("/api/login", credentials, csrf)
        print("PASS single-use claim, login, logout", flush=True)
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
        require(browser.json("/api/session")["authenticated"], "Owner session did not persist")
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
    finally:
        failures = []
        resources = []
        if container_created:
            resources.append(("container", ("rm", "--force", name)))
        if volume_created:
            resources.append(("volume", ("volume", "rm", volume)))
        if image_created:
            resources.append(("image tag", ("image", "rm", image)))
        for kind, command in resources:
            try:
                docker(*command)
            except SmokeFailure:
                failures.append(f"{kind}: {name}")
        if failures:
            raise SmokeFailure("Cleanup needs attention for own resources: " + "; ".join(failures))
        if resources:
            print("PASS cleaned own created resources", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-timeout", type=int, default=1200)
    args = parser.parse_args()
    if args.build_timeout < 1:
        parser.error("--build-timeout must be positive")
    try:
        run(args.build_timeout)
    except (SmokeFailure, OSError, ValueError, KeyError) as exc:
        print(f"BLOCKED/FAILED: {exc}", file=sys.stderr)
        return 1
    print("PASS actual single-container acceptance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
