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


def test_cookie_free_session_burst_is_bounded_and_survives_restart(client: TestClient) -> None:
    statuses = []
    for number in range(35):
        client.cookies.clear()
        response = client.get("/api/session", headers={"X-Forwarded-For": f"192.0.2.{number}"})
        statuses.append(response.status_code)
    assert statuses[:20] == [200] * 20
    assert statuses[20:] == [429] * 15
    assert response.headers["retry-after"] == "300"
    with client.app.state.identity.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM owner_sessions").fetchone()[0] == 20
    restarted = create_app(client.app.state.identity.path.parent, origin="http://localhost:8080")
    with TestClient(restarted, base_url="http://localhost:8080") as other:
        assert other.get("/api/session").status_code == 429


def test_concurrent_cookie_free_http_admission_is_atomic(client: TestClient) -> None:
    def request(number: int) -> int:
        with TestClient(client.app, base_url="http://localhost:8080") as caller:
            return caller.get("/api/session", headers={"X-Forwarded-For": str(number)}).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(request, range(32)))
    assert statuses.count(200) == 20
    assert statuses.count(429) == 12
    with client.app.state.identity.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM owner_sessions").fetchone()[0] == 20


def test_anonymous_global_cap_cleanup_and_session_reuse(tmp_path: Path, monkeypatch) -> None:
    from internship_pipeline.identity import Throttled

    now = [10000.0]
    monkeypatch.setattr("internship_pipeline.identity.time.time", lambda: now[0])
    identity = Identity(tmp_path / "admission.sqlite3")
    with ThreadPoolExecutor(max_workers=8) as pool:

        def admit(number: int) -> bool:
            try:
                identity.anonymous_session(f"client-{number}")
                return True
            except Throttled:
                return False

        assert sum(pool.map(admit, range(120))) == 100
    # The global admission limit persists; another address does not evade it.
    restarted = Identity(identity.path)
    with pytest.raises(Throttled):
        restarted.anonymous_session("other")
    now[0] += 301
    guests = [restarted.anonymous_session(f"next-{n}") for n in range(28)]
    with pytest.raises(Throttled):
        restarted.anonymous_session("cap-overflow")
    token, csrf_value, _ = guests[0]
    assert restarted.anonymous_session("next-0", token)[:2] == (token, csrf_value)
    with restarted.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM owner_sessions").fetchone()[0] == 128
        assert db.execute("SELECT COUNT(*) FROM anonymous_admission").fetchone()[0] == 29
    # Expiration frees capacity and removes expired admission keys without a restart.
    now[0] += 1201
    restarted.anonymous_session("after-expiration")
    with restarted.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM owner_sessions").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM anonymous_admission").fetchone()[0] == 2


def test_valid_guest_and_owner_reuse_work_when_new_session_admission_is_full(
    client: TestClient,
) -> None:
    guest = client.get("/api/session")
    token = client.cookies.get("pipeline_session")
    csrf_value = guest.json()["csrf"]
    with client.app.state.identity.connection() as db:
        db.execute("UPDATE anonymous_admission SET count=100 WHERE key='global'")
    for _ in range(3):
        response = client.get("/api/session")
        assert response.status_code == 200 and "set-cookie" not in response.headers
        assert client.cookies.get("pipeline_session") == token
        assert response.json()["csrf"] == csrf_value
    claim(client)
    for _ in range(3):
        response = client.get("/api/session")
        assert response.status_code == 200 and response.json()["authenticated"]
        assert "set-cookie" not in response.headers
    assert client.get("/api/jobs").status_code == 200


def test_csv_stream_uses_complete_iterator_with_owner_admission(
    client: TestClient, monkeypatch
) -> None:
    service = client.app.state.sheets_integration

    def chunks():
        yield "job_id,title\n"
        for number in range(10005):
            yield f"id-{number},Synthetic {number}\n"

    monkeypatch.setattr(service, "csv_chunks", chunks)
    monkeypatch.setattr(service, "csv", lambda: pytest.fail("CSV response must use the iterator"))
    assert client.get("/api/sheets/export.csv").status_code == 401
    claim(client)
    response = client.get("/api/sheets/export.csv")
    assert response.status_code == 200
    assert len(response.text.splitlines()) == 10006
    assert response.text.endswith("id-10004,Synthetic 10004\n")
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]
