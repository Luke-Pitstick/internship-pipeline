from __future__ import annotations

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_dashboard_api import api as dashboard_fixture

from internship_pipeline import cli
from internship_pipeline.app import create_app
from internship_pipeline.bootstrap import configured_roles
from internship_pipeline.identity import Identity, IdentityError
from internship_pipeline.models import Settings

api = dashboard_fixture

PASSWORD = "synthetic-password-for-tests"


@pytest.fixture
def client(tmp_path: Path, api) -> TestClient:
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<h1>Application shell</h1>")
    app = create_app(
        tmp_path, origin="http://localhost:8080", static_dir=web, settings=api.settings
    )
    with TestClient(app, base_url="http://localhost:8080") as client:
        yield client


def csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.get("/api/session").json()["csrf"]}


def claim(client: TestClient) -> dict[str, str]:
    token = client.app.state.identity.setup_token(rotate=True)
    response = client.post(
        "/api/claim",
        headers=csrf(client),
        json={
            "setup_token": token,
            "username": "owner",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf"]}


def test_claim_race_is_atomic_and_single_use(tmp_path: Path) -> None:
    identity = Identity(tmp_path / "identity.sqlite3")
    token = identity.setup_token()
    assert token

    def attempt(number: int) -> bool:
        try:
            Identity(identity.path).claim(token, str(number), PASSWORD)
            return True
        except IdentityError:
            return False

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert sum(executor.map(attempt, range(4))) == 1
    assert identity.setup_token(rotate=True) is None
    with sqlite3.connect(identity.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM owner").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM owner_setup").fetchone()[0] == 0
        stored = connection.execute("SELECT password_hash FROM owner").fetchone()[0]
        assert stored.startswith("$argon2id$") and PASSWORD not in stored
    assert token.encode() not in identity.path.read_bytes()


def test_setup_health_and_private_endpoints(client: TestClient) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/healthz").json() == {"alive": True}
    assert client.get("/readyz").json() == {"ready": True, "mode": "setup"}
    for path in ("/api/jobs", "/api/status", "/api/resumes/relevant", "/api/unknown"):
        assert client.get(path, headers={"Authorization": "Bearer old-token"}).status_code == 401
    assert client.post("/api/jobs/relevant/applied", json={"status": "applied"}).status_code == 401
    guest = client.get("/api/session")
    assert guest.json()["claimed"] is False
    assert "HttpOnly" in guest.headers["set-cookie"]
    assert "SameSite=strict" in guest.headers["set-cookie"]
    assert client.get("/api/jobs").status_code == 401


def test_csrf_origin_validation_and_password_redaction(client: TestClient) -> None:
    token = client.app.state.identity.setup_token(rotate=True)
    payload = {"setup_token": token, "username": "owner", "password": PASSWORD}
    headers = csrf(client)
    assert client.post("/api/claim", json=payload).status_code == 403
    assert (
        client.post(
            "/api/claim", headers={**headers, "Origin": "https://evil.test"}, json=payload
        ).status_code
        == 403
    )
    bad = client.post("/api/claim", headers=headers, json={**payload, "password": PASSWORD * 100})
    assert bad.status_code == 422 and PASSWORD not in bad.text
    assert client.post("/api/claim", headers=headers, content="x" * 20000).status_code == 413
    assert (
        client.post(
            "/api/claim", headers=headers, json={**payload, "setup_token": "wrong"}
        ).status_code
        == 400
    )
    assert not client.app.state.identity.claimed()


def test_session_rotation_logout_expiry_and_login(client: TestClient) -> None:
    csrf(client)
    guest = client.cookies.get("pipeline_session")
    headers = claim(client)
    signed_in = client.cookies.get("pipeline_session")
    assert guest != signed_in
    assert client.app.state.identity.session(guest) is None
    assert client.get("/api/jobs").status_code == 200
    assert client.post("/api/logout", json={}).status_code == 403
    assert client.post("/api/logout", json={}, headers=headers).status_code == 200
    assert client.app.state.identity.session(signed_in) is None
    assert client.get("/api/jobs").status_code == 401
    headers = csrf(client)
    assert (
        client.post(
            "/api/login",
            headers=headers,
            json={
                "username": "owner",
                "password": "wrong",
            },
        ).status_code
        == 401
    )
    response = client.post(
        "/api/login",
        headers=headers,
        json={
            "username": "OWNER",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200
    with client.app.state.identity.connection() as connection:
        connection.execute("UPDATE owner_sessions SET expires=0")
    assert client.get("/api/jobs").status_code == 401


def test_login_throttles_survive_restart(client: TestClient) -> None:
    claim(client)
    headers = csrf(client)
    for _ in range(9):
        assert (
            client.post(
                "/api/login",
                headers=headers,
                json={
                    "username": "owner",
                    "password": "wrong",
                },
            ).status_code
            == 401
        )
    response = client.post(
        "/api/login",
        headers=headers,
        json={
            "username": "owner",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 429 and response.headers["retry-after"] == "300"
    from internship_pipeline.identity import Throttled

    with pytest.raises(Throttled):
        Identity(client.app.state.identity.path).attempt("testclient")


def test_owner_sessions_and_jobs_persist_and_recovery_revokes(
    tmp_path: Path, api, monkeypatch
) -> None:
    app = create_app(tmp_path, origin="http://localhost:8080", settings=api.settings)
    with TestClient(app, base_url="http://localhost:8080") as client:
        headers = claim(client)
        first = client.post(
            "/api/jobs/relevant/applied", headers=headers, json={"status": "applied"}
        ).json()
        old_session = client.cookies.get("pipeline_session")
        identity = Identity(app.state.identity.path)
        assert identity.claimed() and identity.session(old_session)["authenticated"]
        assert api.mark_applied("relevant") == first
        monkeypatch.setattr("builtins.input", lambda _: "recovered-owner")
        monkeypatch.setattr("getpass.getpass", lambda _: "recovered-password-123")
        # Recovery is an offline operator action and must reject an active application.
        assert cli.main(["recover-owner", "--data-dir", str(tmp_path)]) == 2
        assert identity.login("owner", PASSWORD) is not None
        assert identity.login("recovered-owner", "recovered-password-123") is None
    assert cli.main(["recover-owner", "--data-dir", str(tmp_path)]) == 0
    assert identity.login("owner", PASSWORD) is None
    assert identity.login("recovered-owner", "recovered-password-123") is not None
    assert identity.setup_token(rotate=True) is None
    assert api.mark_applied("relevant") == first
    with TestClient(app, base_url="http://localhost:8080") as restarted:
        restarted.cookies.set("pipeline_session", old_session)
        assert restarted.get("/api/jobs").status_code == 401


def test_secure_cookie_and_origin_configuration(tmp_path: Path) -> None:
    app = create_app(tmp_path, origin="https://jobs.example.test", static_dir=tmp_path)
    with TestClient(app, base_url="https://jobs.example.test") as client:
        response = client.get("/api/session")
        assert "__Host-pipeline_session=" in response.headers["set-cookie"]
        assert "Secure" in response.headers["set-cookie"]
        assert client.get("/healthz", headers={"Host": "evil.test"}).status_code == 400
    with pytest.raises(ValueError):
        create_app(tmp_path, origin="http://public.example.test")


def test_readiness_distinguishes_missing_assets_db_and_supervisor(tmp_path: Path) -> None:
    status = tmp_path / "supervisor.json"
    web = tmp_path / "web"
    web.mkdir()
    app = create_app(tmp_path, origin="http://localhost", static_dir=web, supervisor_status=status)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 503
        (web / "index.html").write_text("shell")
        status.write_text(json.dumps({"at": time.time(), "healthy": True, "roles": []}))
        assert client.get("/readyz").status_code == 200
        status.write_text(json.dumps({"at": 0, "healthy": True}))
        assert client.get("/readyz").status_code == 503


def test_unconfigured_worker_capabilities_remain_inactive(tmp_path: Path) -> None:
    assert configured_roles(
        Settings(database_path=tmp_path / "state.db", companies_path=tmp_path / "absent")
    ) == ["search-runs", "email-delivery", "sheets-sync"]
