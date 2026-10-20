from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from internship_pipeline.app import create_app
from internship_pipeline.bootstrap import configured_roles
from internship_pipeline.identity import Identity
from internship_pipeline.models import Settings
from internship_pipeline.storage import Store


def test_configured_collection_does_not_require_models_or_notifications(tmp_path: Path) -> None:
    companies = tmp_path / "companies.yaml"
    companies.write_text("[]")
    settings = Settings(database_path=tmp_path / "state.sqlite3", companies_path=companies)
    create_app(tmp_path, origin="http://localhost", settings=settings)
    assert configured_roles(settings) == ["email-delivery", "sheets-sync"]
    with Store(settings.database_path).transaction() as db:
        db.execute("UPDATE onboarding_state SET data=json_set(data,'$.complete',json('true'))")
    assert configured_roles(settings) == [
        "search-runs",
        "email-delivery",
        "sheets-sync",
        "discovery",
        "collector",
    ]
    settings = settings.model_copy(update={"companies_path": tmp_path / "absent"})
    assert configured_roles(settings) == [
        "search-runs",
        "email-delivery",
        "sheets-sync",
        "discovery",
    ]


@pytest.mark.parametrize("reload", [False, True])
def test_real_supervisor_setup_restart_and_graceful_shutdown(tmp_path: Path, reload: bool) -> None:
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    root = tmp_path / "persistent"
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<h1>Static app shell</h1>")
    # Child workers use real CLI/queue/storage code with only provider I/O replaced.
    transport = tmp_path / "transport"
    transport.mkdir()
    (transport / "sitecustomize.py").write_text(
        "from internship_pipeline.sources import jobspy\n"
        "from internship_pipeline.models import FetchResult, SourceJob\n"
        "def fetch(query, timeout):\n"
        "    return FetchResult(jobs=[SourceJob(source='jobspy:linkedin', "
        "source_id='synthetic-1', board_id=query.id, company='Synthetic', "
        "title='Synthetic internship', description='Internship', "
        "apply_url='https://example.test/jobs/1')])\n"
        "jobspy.fetch_search = fetch\n"
        "from internship_pipeline import discovery\n"
        "discovery.discover_companies = lambda **kwargs: []\n"
    )
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(transport), str(Path("src").resolve()))),
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
                    [
                        sys.executable,
                        "-m",
                        "internship_pipeline.bootstrap",
                        *(["--reload"] if reload else []),
                    ],
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
                    assert client.get("/api/session").json()["authenticated"] is True
                    if boot == 0:
                        worker_deadline = time.monotonic() + 10
                        while client.get("/api/status").json()["worker_roles"] != [
                            "email-delivery",
                            "sheets-sync",
                        ]:
                            assert time.monotonic() < worker_deadline
                            time.sleep(0.05)
                        assert client.get("/api/jobs").json()["jobs"] == []
                        headers = {"X-CSRF-Token": client.get("/api/session").json()["csrf"]}
                        saved = client.post(
                            "/api/profile-settings",
                            headers=headers,
                            json={
                                "expected_revision": 0,
                                "profile": {},
                                "preferences": {},
                            },
                        )
                        assert saved.status_code == 200
                        for step in ("models", "profile", "filters", "integrations"):
                            result = client.post(
                                "/api/onboarding/checkpoint",
                                headers=headers,
                                json={
                                    "step": step,
                                    "defer_models": True,
                                    "email": "skip",
                                    "sheets": "skip",
                                },
                            )
                            assert result.status_code == 200
                        preview = client.get("/api/onboarding").json()["preview_token"]
                        finished = client.post(
                            "/api/onboarding/finish", headers=headers, json={"preview": preview}
                        )
                        assert finished.status_code == 200
                        assert finished.json()["complete"]
                    worker_deadline = time.monotonic() + 15
                    while True:
                        roles = client.get("/api/status").json()["worker_roles"]
                        jobs = client.get("/api/jobs").json()["jobs"]
                        if "search-runs" in roles and len(jobs) == 1:
                            break
                        assert process.poll() is None, "Application exited after finishing setup"
                        assert time.monotonic() < worker_deadline, (
                            "Onboarding did not activate collection"
                        )
                        time.sleep(0.05)
                    assert jobs[0]["title"] == "Synthetic internship"
                    with Store(root / "state.sqlite3").connection() as db:
                        assert (
                            db.execute("SELECT stage FROM search_runs").fetchone()[0] == "collected"
                        )
                finally:
                    process.terminate()
                    process.wait(timeout=10)
                assert process.returncode == 0
                assert not (root / "supervisor.json").exists()
                output.seek(0)
                assert ("Owner setup URL:" in output.read()) is (boot == 0)
