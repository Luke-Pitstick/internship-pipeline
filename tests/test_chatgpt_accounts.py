from __future__ import annotations

import gzip
import json
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from threading import Event
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from internship_pipeline.app import create_app
from internship_pipeline.chatgpt.protocol import (
    DISCOVERY,
    ISSUER,
    PLAN_SCOPE,
    RESOURCE,
    TOKEN,
    ChatGPTError,
    request_json,
)
from internship_pipeline.model_connections import ConnectionError, ModelConnectionStore
from internship_pipeline.providers.connections import ConnectionInput, ProbeResult


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def fixture(tmp_path, signing_key):
    class OAuth:
        def __init__(self):
            self.store = ModelConnectionStore(tmp_path / "state.sqlite3", tmp_path / "instance.key")
            self.accounts = self.store.chatgpt
            self.accounts.transport = httpx.MockTransport(self.request)
            self.refreshes = 0
            self.revoke_status = 200
            self.refresh_status = 200
            self.pending_nonce = ""
            self.requests = []

        def tokens(self, expected_nonce, **claims):
            now = int(time.time())
            identity = dict(
                iss=ISSUER,
                sub="synthetic-subject",
                aud="oaiapp_test",
                exp=now + 300,
                iat=now,
                nonce=expected_nonce,
                email="synthetic@example.test",
            )
            identity.update(claims)
            return dict(
                access_token="synthetic-access-token",
                refresh_token="synthetic-refresh-token",
                id_token=jwt.encode(
                    identity, signing_key, algorithm="RS256", headers={"kid": "test"}
                ),
                token_type="Bearer",
                expires_in=3600,
                scope="openid profile email offline_access resource.invoke " + PLAN_SCOPE,
            )

        def request(self, request):
            self.requests.append(request)
            if str(request.url) == DISCOVERY:
                return httpx.Response(
                    200,
                    json=dict(
                        issuer=ISSUER,
                        jwks_uri=ISSUER + "/test-keys",
                        revocation_endpoint=ISSUER + "/revoke",
                    ),
                )
            if request.url.path == "/test-keys":
                key = jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
                return httpx.Response(200, json={"keys": [{**key, "kid": "test", "alg": "RS256"}]})
            if str(request.url) == TOKEN:
                fields = parse_qs(request.content.decode())
                if fields["grant_type"] == ["refresh_token"]:
                    self.refreshes += 1
                    if self.refresh_status != 200:
                        return httpx.Response(self.refresh_status, json={"error": "invalid_grant"})
                    return httpx.Response(
                        200,
                        json=dict(
                            access_token="rotated-access-token",
                            refresh_token="rotated-refresh-token",
                            expires_in=3600,
                            token_type="Bearer",
                        ),
                    )
                return httpx.Response(200, json=self.tokens(self.pending_nonce))
            if str(request.url) == RESOURCE + "/models":
                assert request.headers["authorization"].startswith("Bearer ")
                return httpx.Response(
                    200,
                    json={
                        "models": [
                            {
                                "slug": "test-model",
                                "display_name": "Test Model",
                                "visibility": "list",
                            },
                            {"slug": "hidden", "display_name": "Hidden", "visibility": "hidden"},
                        ]
                    },
                )
            if request.url.path == "/revoke":
                return httpx.Response(self.revoke_status)
            raise AssertionError(str(request.url))

        def begin(self, revision=0, account_id=None):
            result = self.accounts.begin(
                revision, "http://127.0.0.1:8080/auth/callback", account_id
            )
            query = parse_qs(urlsplit(result["authorize_url"]).query)
            self.pending_nonce = query["nonce"][0]
            return result, query

        def connect(self):
            pending, query = self.begin()
            return self.accounts.complete(query["state"][0], "synthetic-code", "oaiapp_test")

    return OAuth()


def chatgpt_config(account_id, revision=0, model="test-model"):
    return ConnectionInput(
        model=model,
        endpoint=RESOURCE + "/responses",
        auth_mode="chatgpt",
        chatgpt_account_id=account_id,
        expected_revision=revision,
    )


def test_registration_persistence_encryption_models_and_readiness(fixture):
    account_id = fixture.connect()
    assert fixture.accounts.models(account_id) == [
        {"slug": "test-model", "display_name": "Test Model"}
    ]
    saved = fixture.store.save("general", chatgpt_config(account_id))
    assert not saved["ready"]
    attempt, config, token = fixture.store.reserve_test("general", saved["revision"])
    assert token == "synthetic-access-token"
    fixture.store.complete_test(attempt, ProbeResult("success", "test-model", 20, 10))
    restarted = ModelConnectionStore(fixture.store.db_path, fixture.store.key_path)
    assert restarted.summary()["general"]["ready"]
    assert restarted.ready_connection("general", saved["revision"])[1] == token
    with fixture.store.connection() as db:
        assert db.execute("SELECT output_token_limit FROM model_attempts").fetchone()[0] is None
    assert token not in json.dumps(fixture.accounts.accounts())
    assert token.encode() not in fixture.store.db_path.read_bytes()
    with pytest.raises(ConnectionError, match="available"):
        fixture.store.save("general", chatgpt_config(account_id, saved["revision"], "hidden"))


@pytest.mark.parametrize("compressed", [False, True])
def test_model_catalog_accepts_large_metadata_and_preserves_visible_order(fixture, compressed):
    account_id = fixture.connect()
    catalog = {
        "models": [
            {
                "slug": slug,
                "display_name": name,
                "visibility": visibility,
                "base_instructions": "synthetic metadata " * 12_000,
            }
            for slug, name, visibility in [
                ("second-model", "Second Model", "list"),
                ("hidden-model", "Hidden Model", "hidden"),
                ("first-model", "First Model", "list"),
            ]
        ]
    }
    payload = json.dumps(catalog).encode()
    assert len(payload) > 262_144
    fixture.accounts.transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=gzip.compress(payload) if compressed else payload,
            headers={"content-encoding": "gzip"} if compressed else {},
        )
    )
    assert fixture.accounts.models(account_id) == [
        {"slug": "second-model", "display_name": "Second Model"},
        {"slug": "first-model", "display_name": "First Model"},
    ]


def test_model_catalog_remains_bounded_after_decompression(fixture):
    account_id = fixture.connect()
    payload = json.dumps({"models": [], "metadata": "x" * 2_097_152}).encode()
    fixture.accounts.transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=gzip.compress(payload), headers={"content-encoding": "gzip"}
        )
    )
    with pytest.raises(ChatGPTError, match="oversized"):
        fixture.accounts.models(account_id)


def test_oauth_responses_keep_the_smaller_size_limit():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"metadata": "x" * 262_144})
    )
    with pytest.raises(ChatGPTError, match="oversized"):
        request_json("GET", DISCOVERY, transport=transport)


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://attacker.test"},
        {"aud": "wrong-client"},
        {"nonce": "wrong-nonce"},
        {"exp": 1},
        {"sub": ""},
        {"azp": "wrong-client"},
        {"at_hash": "wrong"},
    ],
)
def test_invalid_identity_cannot_connect_and_callback_is_single_use(fixture, claims):
    pending, query = fixture.begin()
    tokens = fixture.tokens(query["nonce"][0], **claims)
    with pytest.raises(ChatGPTError):
        fixture.accounts.complete(query["state"][0], None, "oaiapp_test", tokens=tokens)
    assert fixture.accounts.accounts() == []
    assert fixture.accounts.attempt_status(pending["attempt_id"]) == "failed"
    with pytest.raises(ChatGPTError, match="already used"):
        fixture.accounts.complete(query["state"][0], None, "oaiapp_test", tokens=tokens)


def test_signature_scopes_and_returning_identity_are_verified(fixture, signing_key):
    pending, query = fixture.begin()
    tokens = fixture.tokens(query["nonce"][0])
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims = jwt.decode(tokens["id_token"], options={"verify_signature": False})
    tokens["id_token"] = jwt.encode(claims, other_key, algorithm="RS256", headers={"kid": "test"})
    with pytest.raises(ChatGPTError, match="identity"):
        fixture.accounts.complete(query["state"][0], None, "oaiapp_test", tokens=tokens)
    pending, query = fixture.begin()
    tokens = fixture.tokens(query["nonce"][0])
    tokens["scope"] = "openid profile email"
    with pytest.raises(ChatGPTError, match="plan usage"):
        fixture.accounts.complete(query["state"][0], None, "oaiapp_test", tokens=tokens)
    account_id = fixture.connect()
    pending, query = fixture.begin(account_id=account_id)
    assert query["client_id"] == ["oaiapp_test"]
    assert "agent_name_hint" not in query and "id_token_hint" in query
    with pytest.raises(ChatGPTError, match="different account"):
        fixture.accounts.complete(
            query["state"][0],
            None,
            None,
            tokens=fixture.tokens(query["nonce"][0], sub="another-person"),
        )
    assert fixture.accounts.access_token(account_id) == "synthetic-access-token"


def test_refresh_is_serialized_and_rotates_without_model_revision(fixture):
    account_id = fixture.connect()
    with fixture.accounts.connection() as db:
        db.execute("UPDATE chatgpt_accounts SET expires_at=0")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: fixture.accounts.access_token(account_id), range(2)))
    assert results == ["rotated-access-token"] * 2
    assert fixture.refreshes == 1
    assert (
        fixture.accounts.decrypt(fixture.accounts.account(account_id)["encrypted"])["refresh_token"]
        == "rotated-refresh-token"
    )
    assert fixture.store.summary()["general"]["revision"] == 0


def test_reauthorization_cannot_be_overwritten_by_an_inflight_refresh(fixture):
    account_id = fixture.connect()
    _, query = fixture.begin(account_id=account_id)
    tokens = fixture.tokens(query["nonce"][0])
    tokens["access_token"] = "reauthorized-access-token"
    with fixture.accounts.connection() as db:
        db.execute("UPDATE chatgpt_accounts SET expires_at=0")
    refreshing, release, verified = Event(), Event(), Event()

    def respond(request):
        if str(request.url) == TOKEN:
            refreshing.set()
            assert release.wait(5)
        if request.url.path == "/test-keys":
            verified.set()
        return fixture.request(request)

    fixture.accounts.transport = httpx.MockTransport(respond)
    with ThreadPoolExecutor(max_workers=2) as pool:
        refresh = pool.submit(fixture.accounts.access_token, account_id)
        assert refreshing.wait(2)
        reconnect = pool.submit(
            fixture.accounts.complete, query["state"][0], None, "oaiapp_test", tokens=tokens
        )
        try:
            assert verified.wait(2)
            with pytest.raises(FutureTimeout):
                reconnect.result(timeout=0.1)
        finally:
            release.set()
        assert refresh.result() == "rotated-access-token"
        assert reconnect.result() == account_id
    assert fixture.accounts.access_token(account_id) == "reauthorized-access-token"


def test_refresh_denial_requires_reconnect_but_outage_does_not_delete_tokens(fixture):
    account_id = fixture.connect()
    with fixture.accounts.connection() as db:
        db.execute("UPDATE chatgpt_accounts SET expires_at=0")
    fixture.refresh_status = 503
    with pytest.raises(ChatGPTError):
        fixture.accounts.access_token(account_id)
    assert fixture.accounts.connected(account_id)
    fixture.refresh_status = 400
    with pytest.raises(ChatGPTError):
        fixture.accounts.access_token(account_id)
    assert not fixture.accounts.connected(account_id)
    assert fixture.accounts.account(account_id)["encrypted"] is not None


@pytest.mark.parametrize("status", [200, 503])
def test_disconnect_stops_generation_and_reports_revocation(fixture, status):
    account_id = fixture.connect()
    saved = fixture.store.save("general", chatgpt_config(account_id))
    attempt, _, _ = fixture.store.reserve_test("general", saved["revision"])
    fixture.store.complete_test(attempt, ProbeResult("success"))
    fixture.revoke_status = status
    assert fixture.accounts.disconnect(account_id) == (status == 200)
    assert not fixture.store.summary()["general"]["ready"]
    assert fixture.accounts.account(account_id)["encrypted"] is None
    with pytest.raises(ConnectionError, match="Reconnect"):
        fixture.store.ready_connection("general", saved["revision"])


def test_pairing_claim_expiry_cancel_and_model_revision_races(fixture):
    pending = fixture.accounts.begin(0, None)
    paired = fixture.accounts.claim_pairing(pending["pairing_code"], 12345)
    with pytest.raises(ChatGPTError, match="already used"):
        fixture.accounts.claim_pairing(pending["pairing_code"], 12345)
    with pytest.raises(ChatGPTError):
        fixture.accounts.complete(paired["state"], None, "oaiapp_test", pairing="wrong", tokens={})
    fixture.accounts.cancel(pending["attempt_id"])
    with pytest.raises(ChatGPTError):
        fixture.accounts.complete(
            paired["state"], None, "oaiapp_test", pairing=pending["pairing_code"], tokens={}
        )
    pending, query = fixture.begin()
    fixture.store.save(
        "general",
        ConnectionInput(
            model="other",
            endpoint=RESOURCE + "/responses",
            api_key="synthetic-api-key",
            expected_revision=0,
        ),
    )
    with pytest.raises(ChatGPTError, match="changed"):
        fixture.accounts.complete(
            query["state"][0], None, "oaiapp_test", tokens=fixture.tokens(query["nonce"][0])
        )
    assert fixture.accounts.accounts() == []


def test_missing_instance_key_is_not_recreated_for_oauth_only_installation(fixture):
    fixture.connect()
    fixture.store.key_path.unlink()
    with pytest.raises(ConnectionError, match="Restore"):
        ModelConnectionStore(fixture.store.db_path, fixture.store.key_path)
    assert not fixture.store.key_path.exists()


def test_encrypted_nonobject_credentials_are_refused(fixture):
    encrypted = fixture.accounts.cipher.encrypt(b"[]")
    with pytest.raises(ChatGPTError, match="credentials are unavailable"):
        fixture.accounts.decrypt(encrypted)


def test_pending_authorization_also_requires_the_original_encryption_key(fixture):
    fixture.accounts.begin(0, None)
    fixture.store.key_path.unlink()
    with pytest.raises(ConnectionError, match="Restore"):
        ModelConnectionStore(fixture.store.db_path, fixture.store.key_path)
    assert not fixture.store.key_path.exists()


def test_revocation_does_not_consume_an_unused_response_body(fixture):
    class UnreadBody(httpx.SyncByteStream):
        def __iter__(self):
            pytest.fail("Revocation must not read the response body")

    account_id = fixture.connect()

    def respond(request):
        if request.url.path == "/revoke":
            return httpx.Response(200, stream=UnreadBody())
        return fixture.request(request)

    fixture.accounts.transport = httpx.MockTransport(respond)
    assert fixture.accounts.disconnect(account_id)
    assert fixture.accounts.account(account_id)["encrypted"] is None


def test_backup_verification_checks_oauth_records_with_the_instance_key(fixture):
    from internship_pipeline.operations import OperationError, _credentials

    account_id = fixture.connect()
    root = fixture.store.db_path.parent
    (root / "model-credentials.key").write_bytes(fixture.store.key_path.read_bytes())
    _credentials(root)
    with fixture.accounts.connection() as db:
        db.execute("UPDATE chatgpt_accounts SET encrypted=? WHERE id=?", (b"corrupted", account_id))
    with pytest.raises(OperationError, match="decrypt"):
        _credentials(root)


def claim_owner(client, app):
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
    return {"X-CSRF-Token": response.json()["csrf"]}


@pytest.mark.parametrize("origin", ["http://localhost:8080", "https://pipeline.example.test"])
def test_owner_api_callback_and_remote_helper_flow(tmp_path, fixture, origin):
    app = create_app(tmp_path / "app", origin=origin)
    accounts = app.state.model_connections.chatgpt
    accounts.transport = fixture.accounts.transport
    with TestClient(app, base_url=origin) as client:
        assert client.get("/api/chatgpt").status_code == 401
        assert client.get("/api/chatgpt/helper").status_code == 401
        headers = claim_owner(client, app)
        assert client.post("/api/chatgpt/start", json={"expected_revision": 0}).status_code == 403
        assert (
            client.post(
                "/api/chatgpt/start",
                json={"expected_revision": 0},
                headers={**headers, "Origin": "https://attacker.test"},
            ).status_code
            == 403
        )
        pending = client.post(
            "/api/chatgpt/start", json={"expected_revision": 0}, headers=headers
        ).json()
        assert client.get("/api/chatgpt/helper").status_code == 200
        if origin.startswith("http:"):
            query = parse_qs(urlsplit(pending["authorize_url"]).query)
            fixture.pending_nonce = query["nonce"][0]
            response = client.get(
                "http://127.0.0.1:8080/auth/callback",
                params={
                    "state": query["state"][0],
                    "code": "synthetic-code",
                    "client_id": "oaiapp_test",
                },
            )
            assert response.status_code == 200, response.text
            assert "synthetic-code" not in response.text
            assert response.headers["cache-control"] == "no-store"
        else:
            assert client.post("/api/chatgpt/pair", json={"port": 12345}).status_code == 403
            pair_headers = {"Authorization": "Bearer " + pending["pairing_code"]}
            paired = client.post(
                "/api/chatgpt/pair", json={"port": 12345}, headers=pair_headers
            ).json()
            query = parse_qs(urlsplit(paired["authorize_url"]).query)
            response = client.post(
                "/api/chatgpt/complete",
                headers=pair_headers,
                json={
                    "state": paired["state"],
                    "client_id": "oaiapp_test",
                    "tokens": fixture.tokens(query["nonce"][0]),
                },
            )
            assert response.status_code == 200, response.text
        status = client.post(
            "/api/chatgpt/status", json={"attempt_id": pending["attempt_id"]}, headers=headers
        ).json()
        assert status["status"] == "connected" and status["account_id"]
        account = client.get("/api/chatgpt").json()["accounts"][0]
        assert account["email"] == "synthetic@example.test"
        assert "access_token" not in json.dumps(account)
        assert (
            client.post(
                "/api/chatgpt/models", json={"account_id": account["id"]}, headers=headers
            ).json()["models"][0]["slug"]
            == "test-model"
        )
        assert (
            client.post(
                "/api/chatgpt/welcome", json={"account_id": account["id"]}, headers=headers
            ).status_code
            == 200
        )
        assert client.get("/api/chatgpt").json()["accounts"][0]["welcomed"]
        assert client.get("/api/chatgpt", headers={"Host": "attacker.test"}).status_code == 400
