from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from internship_pipeline.app import create_app
from internship_pipeline.model_connections import ConnectionError, ModelConnectionStore
from internship_pipeline.providers.connections import (
    ENDPOINTS,
    ConnectionInput,
    ProbeResult,
    probe,
)

KEY = "synthetic-private-key-do-not-echo"


def config(kind="jev", revision=0, **changes):
    return ConnectionInput(
        model="jev-1.13.0" if kind == "jev" else "test-model",
        endpoint=ENDPOINTS[kind],
        expected_revision=revision,
        api_key=KEY,
        **changes,
    )


@pytest.fixture
def store(tmp_path):
    return ModelConnectionStore(tmp_path / "state.sqlite3", tmp_path / "model-credentials.key")


def jev_response():
    return {
        "model": "jev-1.13.0",
        "usage": {"input_tokens": 120, "output_tokens": 60},
        "answers": {
            "requirement": {
                "type": "choice",
                "choice": "satisfied",
                "confidence": 1,
                "probabilities": {"satisfied": 1, "violated": 0, "not_stated": 0, "ambiguous": 0},
            },
            "evidence": {
                "type": "choice",
                "choice": "p1",
                "confidence": 1,
                "probabilities": {"p1": 1, "none": 0},
            },
            "fit": {
                "type": "score",
                "score": 3,
                "confidence": 1,
                "probabilities": {"0": 0, "1": 0, "2": 0, "3": 1},
            },
        },
    }


def general_response():
    return {
        "model": "test-model-2026",
        "usage": {"input_tokens": 90, "output_tokens": 20},
        "status": "completed",
        "output": [
            {
                "type": "message",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"skill": "Python", "evidence_id": "fact-1"}),
                    }
                ],
            }
        ],
    }


def test_encrypted_revisions_edit_remove_and_restart(store):
    saved = store.save("jev", config())
    revision = saved["revision"]
    assert KEY not in json.dumps(store.summary())
    assert KEY.encode() not in store.db_path.read_bytes()
    assert store.key_path.stat().st_mode & 0o777 == 0o600
    assert KEY not in repr(config())
    restored = ModelConnectionStore(store.db_path, store.key_path)
    attempt, settings, key = restored.reserve_test("jev", revision)
    assert key == KEY and settings.model == "jev-1.13.0"
    restored.complete_test(attempt, ProbeResult("success", "jev-1.13.0", 120, 60))
    assert restored.summary()["jev"]["tested_revision"] == revision
    edit = config(revision=revision).model_copy(update={"api_key": None, "model": "jev-latest"})
    changed = restored.save("jev", edit)
    assert not changed["ready"] and changed["revision"] > revision
    attempt2, _, retained = restored.reserve_test("jev", changed["revision"])
    assert retained == KEY
    restored.complete_test(attempt2, ProbeResult("timeout"))
    replaced = config(revision=changed["revision"]).model_copy(
        update={"api_key": config().api_key.__class__("new-synthetic-key")}
    )
    replaced_row = restored.save("jev", replaced)
    _, _, new = restored.reserve_test("jev", replaced_row["revision"])
    assert new == "new-synthetic-key"
    removed = restored.remove("jev", replaced_row["revision"])
    assert not removed["configured"] and removed["revision"] > replaced_row["revision"]
    with restored.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM model_credentials").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM model_revisions").fetchone()[0] == 4
        assert (
            db.execute("SELECT input_tokens FROM model_attempts WHERE id=?", (attempt,)).fetchone()[
                0
            ]
            == 120
        )
    with pytest.raises(ConnectionError, match="Enter an API key"):
        restored.save("jev", edit.model_copy(update={"expected_revision": removed["revision"]}))


def test_missing_or_wrong_recovery_key_never_resets_credentials(store):
    row = store.save("jev", config())
    backup = store.key_path.read_bytes()
    store.key_path.unlink()
    with pytest.raises(ConnectionError, match="Restore"):
        ModelConnectionStore(store.db_path, store.key_path)
    store.key_path.write_bytes(backup)
    store.key_path.chmod(0o600)
    recovered = ModelConnectionStore(store.db_path, store.key_path)
    assert recovered.reserve_test("jev", row["revision"])[2] == KEY


def test_stale_results_limits_and_independence(store):
    saved = store.save("jev", config())
    attempt, _, _ = store.reserve_test("jev", saved["revision"])
    with pytest.raises(ConnectionError, match="one at a time"):
        store.reserve_test("jev", saved["revision"])
    with pytest.raises(ConnectionError, match="changed"):
        store.save("jev", config())
    changed = store.save("jev", config(revision=saved["revision"]))
    store.complete_test(attempt, ProbeResult("success", "jev-1.13.0", 1, 2))
    assert not store.summary()["jev"]["ready"]
    general = store.save("general", config("general"))
    assert general["configured"] and store.summary()["jev"]["configured"]
    for _ in range(4):
        attempt, _, _ = store.reserve_test("jev", changed["revision"])
        store.complete_test(attempt, ProbeResult("authentication"))
    with pytest.raises(ConnectionError, match="five per hour"):
        store.reserve_test("jev", changed["revision"])


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost/private",
        "https://evil.test",
        "https://api.typesafe.ai@evil.test/v1/systemone",
        ENDPOINTS["jev"] + "?secret=yes",
    ],
)
def test_no_arbitrary_provider_urls(store, endpoint):
    with pytest.raises(ConnectionError, match="official"):
        store.save("jev", config().model_copy(update={"endpoint": endpoint}))


@pytest.mark.parametrize(
    "changes",
    [
        {"timeout_seconds": 61},
        {"max_output_tokens": 9999},
        {"model": "bad\nmodel"},
        {"api_key": ""},
    ],
)
def test_bounds(changes):
    raw = config().model_dump()
    raw.update(changes)
    with pytest.raises(ValidationError):
        ConnectionInput.model_validate(raw)


@pytest.mark.parametrize("kind", ["jev", "general"])
def test_real_contract_request_and_response(kind):
    def handler(request):
        assert str(request.url) == ENDPOINTS[kind]
        assert request.headers["authorization"] == f"Bearer {KEY}"
        body = json.loads(request.content)
        if kind == "jev":
            assert set(body["questions"]) == {"requirement", "evidence", "fit"}
        else:
            assert body["text"]["format"]["strict"] is True
            assert body["store"] is False and body["max_output_tokens"] == 1024
        return httpx.Response(200, json=jev_response() if kind == "jev" else general_response())

    result = asyncio.run(probe(kind, config(kind), KEY, transport=httpx.MockTransport(handler)))
    assert result.status == "success" and result.input_tokens > 0


@pytest.mark.parametrize("outcome", ["success", "invalid_output", "stale_revision"])
def test_reserved_probe_persists_resolved_identity_usage_and_readiness(store, outcome):
    selected = config().model_copy(update={"model": "jev-latest"})
    saved = store.save("jev", selected)
    assert not saved["ready"]
    attempt, settings, key = store.reserve_test("jev", saved["revision"])
    pending = store.summary()["jev"]
    assert not pending["ready"] and pending["last_test"]["status"] == "pending"
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == ENDPOINTS["jev"]
        assert json.loads(request.content)["model"] == "jev-latest"
        body = jev_response()
        if outcome == "invalid_output":
            body["answers"]["evidence"]["choice"] = "invented-evidence"
        return httpx.Response(200, json=body)

    result = asyncio.run(probe("jev", settings, key, transport=httpx.MockTransport(handler)))
    if outcome == "stale_revision":
        store.save("jev", selected.model_copy(update={"expected_revision": saved["revision"]}))
    store.complete_test(attempt, result)
    assert len(calls) == 1
    expected_status = "output" if outcome == "invalid_output" else "success"
    assert result.status == expected_status
    with store.connection() as db:
        recorded = db.execute("SELECT * FROM model_attempts WHERE id=?", (attempt,)).fetchone()
        assert recorded["revision"] == saved["revision"]
        assert recorded["status"] == expected_status
        assert recorded["effective_model"] == "jev-1.13.0"
        assert (recorded["input_tokens"], recorded["output_tokens"]) == (120, 60)
        assert recorded["completed_at"] is not None
        assert recorded["request_bytes"] > 0 and recorded["output_token_limit"] is None
    restarted = ModelConnectionStore(store.db_path, store.key_path)
    summary = restarted.summary()["jev"]
    assert summary["config"]["model"] == "jev-latest"
    assert summary["ready"] is (outcome == "success")
    assert summary["tested_revision"] == (saved["revision"] if outcome == "success" else None)
    if outcome == "success":
        assert summary["last_test"]["effective_model"] == "jev-1.13.0"
        assert restarted.ready_connection("jev", saved["revision"])[0].model == "jev-latest"
    else:
        with pytest.raises(ConnectionError, match="successfully test"):
            restarted.ready_connection("jev", saved["revision"])


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (401, "authentication"),
        (403, "authentication"),
        (429, "rate_limit"),
        (400, "unsupported"),
        (302, "unsupported"),
        (503, "unavailable"),
    ],
)
def test_sanitized_provider_errors(code, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(code, text=KEY, headers={"Location": "https://evil.test"})

    result = asyncio.run(probe("jev", config(), KEY, transport=httpx.MockTransport(handler)))
    assert result.status == status and len(calls) == 1
    assert KEY not in repr(result)


def test_timeout_body_limit_and_unsupported_output():
    def timeout(request):
        raise httpx.ReadTimeout(KEY)

    assert (
        asyncio.run(probe("jev", config(), KEY, transport=httpx.MockTransport(timeout))).status
        == "timeout"
    )
    for body in (
        "x" * 65537,
        "not JSON",
        json.dumps({"model": KEY}),
        json.dumps({**general_response(), "status": "incomplete"}),
    ):
        result = asyncio.run(
            probe(
                "general",
                config("general"),
                KEY,
                transport=httpx.MockTransport(
                    lambda request, body=body: httpx.Response(200, text=body)
                ),
            )
        )
        assert result.status == "output" and KEY not in repr(result)
    invalid = jev_response()
    invalid["answers"]["fit"]["score"] = 0
    result = asyncio.run(
        probe(
            "jev",
            config(),
            KEY,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=invalid)),
        )
    )
    assert result.status == "output" and result.input_tokens == 120


def test_integrated_owner_csrf_persistence_and_test(tmp_path: Path, monkeypatch):
    from internship_pipeline import model_connection_router

    async def synthetic(kind, config, key):
        assert key == KEY
        return await probe(
            kind,
            config,
            key,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=jev_response())),
        )

    monkeypatch.setattr(model_connection_router, "probe", synthetic)
    app = create_app(tmp_path, origin="http://localhost:8080")
    with TestClient(app, base_url="http://localhost:8080") as client:
        assert client.get("/api/model-connections").status_code == 401
        session = client.get("/api/session").json()
        response = client.post(
            "/api/claim",
            headers={"X-CSRF-Token": session["csrf"]},
            json={
                "setup_token": app.state.identity.setup_token(rotate=True),
                "username": "synthetic-owner",
                "password": "synthetic-test-password",
            },
        )
        headers = {"X-CSRF-Token": response.json()["csrf"]}
        body = config().model_dump(mode="json")
        body["api_key"] = KEY
        path = "/api/model-connections/jev"
        for suffix in ("save", "test", "remove"):
            assert client.post(path + "/" + suffix, json=body).status_code == 403
        assert (
            client.post(
                path + "/save", json=body, headers={**headers, "Origin": "https://evil.test"}
            ).status_code
            == 403
        )
        saved = client.post(path + "/save", json=body, headers=headers)
        assert saved.status_code == 200, saved.text
        revision = saved.json()["revision"]
        assert KEY not in saved.text
        tested = client.post(path + "/test", json={"expected_revision": revision}, headers=headers)
        assert tested.json()["status"] == "success"
        body["timeout_seconds"] = 100
        invalid = client.post(path + "/save", json=body, headers=headers)
        assert invalid.status_code == 422 and KEY not in invalid.text
    restarted = create_app(tmp_path, origin="http://localhost:8080")
    assert restarted.state.model_connections.summary()["jev"]["ready"] is True
