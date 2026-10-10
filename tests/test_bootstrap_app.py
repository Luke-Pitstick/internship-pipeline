from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from internship_pipeline.bootstrap import configured_roles
from internship_pipeline.identity import Identity
from internship_pipeline.models import Settings


def test_configured_collection_does_not_require_models_or_notifications(tmp_path: Path) -> None:
    companies = tmp_path / "companies.yaml"
    companies.write_text("[]")
    settings = Settings(database_path=tmp_path / "state.sqlite3", companies_path=companies)
    assert configured_roles(settings) == [
        "search-runs",
        "email-delivery",
        "sheets-sync",
        "collector",
        "discovery",
    ]
    settings = settings.model_copy(update={"companies_path": tmp_path / "absent"})
    assert configured_roles(settings) == ["search-runs", "email-delivery", "sheets-sync"]


def test_real_supervisor_setup_restart_and_graceful_shutdown(tmp_path: Path) -> None:
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    root = tmp_path / "persistent"
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<h1>Static app shell</h1>")
    env = {
        **os.environ,
        "PYTHONPATH": str(Path("src").resolve()),
        "PIPELINE_DATA_DIR": str(root),
        "PIPELINE_WEB_DIR": str(web),
        "PIPELINE_ORIGIN": origin,
        "PORT": str(port),
    }
    # The test never consumes the operator's real worker settings or environment paths.
    for key in (
        "PIPELINE_CONFIG",
        "PIPELINE_DATABASE_PATH",
        "PIPELINE_SUPERVISOR_STATUS",
    ):
        env.pop(key, None)
    with httpx.Client(base_url=origin, timeout=2) as client:
        for boot in range(2):
            with (tmp_path / f"boot-{boot}.log").open("w+") as output:
                process = subprocess.Popen(
                    [sys.executable, "-m", "internship_pipeline.bootstrap"],
                    env=env,
                    stdout=output,
                    stderr=output,
                )
                try:
                    deadline = time.monotonic() + 15
                    while True:
                        assert process.poll() is None, "Application exited before readiness"
                        try:
                            if client.get("/readyz").status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        assert time.monotonic() < deadline, "Application never became ready"
                        time.sleep(0.05)
                    assert client.get("/").status_code == 200
                    if boot == 0:
                        csrf = client.get("/api/session").json()["csrf"]
                        token = Identity(root / "identity.sqlite3").setup_token(rotate=True)
                        result = client.post(
                            "/api/claim",
                            headers={"X-CSRF-Token": csrf},
                            json={
                                "setup_token": token,
                                "username": "synthetic",
                                "password": "synthetic-persistent-password",
                            },
                        )
                        assert result.status_code == 200
                    assert client.get("/api/jobs").json()["jobs"] == []
                    assert client.get("/api/session").json()["authenticated"] is True
                    worker_deadline = time.monotonic() + 10
                    while client.get("/api/status").json()["worker_roles"] != [
                        "search-runs",
                        "email-delivery",
                        "sheets-sync",
                    ]:
                        assert time.monotonic() < worker_deadline
                        time.sleep(0.05)
                finally:
                    process.terminate()
                    process.wait(timeout=10)
                assert process.returncode == 0
                assert not (root / "supervisor.json").exists()
                output.seek(0)
                assert ("Owner setup URL:" in output.read()) is (boot == 0)
