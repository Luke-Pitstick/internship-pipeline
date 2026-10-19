"""Catalog wire contracts, bounded failures and owner-only credential resolution."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from internship_pipeline.app import create_app
from internship_pipeline.model_connections import ConnectionError, ModelConnectionStore
from internship_pipeline.providers.catalog import CatalogError, CatalogInput, list_models
from internship_pipeline.providers.connections import ConnectionInput
from internship_pipeline.providers.structured import GENERAL_ENDPOINTS

KEY = "synthetic-catalog-secret"


@pytest.mark.parametrize("provider", ["openai", "anthropic", "openrouter"])
def test_provider_catalog_headers_names_and_order(provider):
    calls = []

    def respond(request):
        calls.append(request)
        assert request.method == "GET" and request.url.path.endswith("/models")
        if provider == "openrouter":
            assert str(request.url) == "https://openrouter.ai/api/v1/models"
            assert "authorization" not in request.headers and "x-api-key" not in request.headers
        elif provider == "anthropic":
            assert request.headers["x-api-key"] == KEY
            assert request.headers["anthropic-version"] == "2023-06-01"
            assert "authorization" not in request.headers
        else:
            assert str(request.url) == "https://api.openai.com/v1/models"
            assert request.headers["authorization"] == "Bearer " + KEY
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "z-model", "display_name": "Z Model", "name": "Z Model"},
                    {"id": "a-model", "display_name": "A Model", "name": "A Model"},
                    {"id": "z-model", "display_name": "Z Model", "name": "Z Model"},
                    {"id": "unsafe model"},
                    {"id": KEY},
                ]
            },
        )

    models = asyncio.run(
        list_models(GENERAL_ENDPOINTS[provider], KEY, transport=httpx.MockTransport(respond))
    )
    assert models == [
        {"id": "z-model", "name": "z-model" if provider == "openai" else "Z Model"},
        {"id": "a-model", "name": "a-model" if provider == "openai" else "A Model"},
    ]
    assert len(calls) == 1


def test_anthropic_pagination_keeps_all_models():
    def respond(request):
        assert request.url.params["limit"] == "1000"
        second = request.url.params.get("after_id") == "claude-first"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "claude-second" if second else "claude-first",
                        "display_name": "Second" if second else "First",
                    }
                ],
                "has_more": not second,
                "last_id": "claude-first",
            },
        )

    models = asyncio.run(
        list_models(GENERAL_ENDPOINTS["anthropic"], KEY, transport=httpx.MockTransport(respond))
    )
    assert [model["id"] for model in models] == ["claude-first", "claude-second"]


@pytest.mark.parametrize("code", [302, 401, 403, 429, 500])
def test_catalog_errors_never_return_upstream_secrets_or_follow_redirects(code):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(code, text=KEY, headers={"Location": "https://evil.test"})

    with pytest.raises(CatalogError) as caught:
        asyncio.run(
            list_models(GENERAL_ENDPOINTS["openai"], KEY, transport=httpx.MockTransport(respond))
        )
    assert KEY not in str(caught.value) and len(calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"data": {}},
        {"data": [None]},
        {"data": [], "has_more": True, "last_id": "repeated"},
    ],
)
def test_malformed_catalog_and_repeated_cursor_fail(body):
    with pytest.raises(CatalogError):
        asyncio.run(
            list_models(
                GENERAL_ENDPOINTS["anthropic"],
                KEY,
                transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)),
            )
        )


def test_timeout_and_size_limit():
    def timeout(request):
        raise httpx.ReadTimeout(KEY)

    for respond in (
        timeout,
        lambda request: httpx.Response(200, content=b"x" * (16 * 1024 * 1024 + 1)),
    ):
        with pytest.raises(CatalogError) as caught:
            asyncio.run(
                list_models(
                    GENERAL_ENDPOINTS["openai"], KEY, transport=httpx.MockTransport(respond)
                )
            )
        assert KEY not in str(caught.value)


def test_catalog_uses_only_same_saved_provider_revision(tmp_path):
    store = ModelConnectionStore(tmp_path / "state.db", tmp_path / "key")
    request = CatalogInput(endpoint=GENERAL_ENDPOINTS["openai"], expected_revision=0)
    with pytest.raises(ConnectionError):
        store.catalog_key(request)
    assert (
        store.catalog_key(
            request.model_copy(
                update={"api_key": None, "endpoint": GENERAL_ENDPOINTS["openrouter"]}
            )
        )
        is None
    )
    config = ConnectionInput(
        endpoint=GENERAL_ENDPOINTS["openai"], model="test-model", api_key=KEY, expected_revision=0
    )
    saved = store.save("general", config)
    request.expected_revision = saved["revision"]
    assert store.catalog_key(request) == KEY
    assert (
        store.catalog_key(
            CatalogInput(endpoint=request.endpoint, expected_revision=0, api_key="replacement-key")
        )
        == "replacement-key"
    )
    with pytest.raises(ConnectionError):
        store.catalog_key(request.model_copy(update={"expected_revision": 0}))
    with pytest.raises(ConnectionError):
        store.catalog_key(request.model_copy(update={"endpoint": GENERAL_ENDPOINTS["anthropic"]}))
    assert store.summary()["general"]["revision"] == saved["revision"]


def test_catalog_route_owner_csrf_draft_key_and_validation(tmp_path, monkeypatch):
    from internship_pipeline import model_connection_router

    async def catalog(endpoint, key):
        assert endpoint == GENERAL_ENDPOINTS["openai"] and key == KEY
        return [{"id": "test-model", "name": "Test Model"}]

    monkeypatch.setattr(model_connection_router, "list_models", catalog)
    app = create_app(tmp_path, origin="http://localhost:8080")
    body = {"endpoint": GENERAL_ENDPOINTS["openai"], "api_key": KEY, "expected_revision": 0}
    path = "/api/model-connections/general/models"
    with TestClient(app, base_url="http://localhost:8080") as client:
        assert client.post(path, json=body).status_code in (401, 403)
        session = client.get("/api/session").json()
        claimed = client.post(
            "/api/claim",
            headers={"X-CSRF-Token": session["csrf"]},
            json={
                "setup_token": app.state.identity.setup_token(rotate=True),
                "username": "synthetic-owner",
                "password": "synthetic-test-password",
            },
        )
        headers = {"X-CSRF-Token": claimed.json()["csrf"]}
        assert client.post(path, json=body).status_code == 403
        assert (
            client.post(
                path, json=body, headers={**headers, "Origin": "https://evil.test"}
            ).status_code
            == 403
        )
        response = client.post(path, json=body, headers=headers)
        assert response.status_code == 200
        assert response.json()["models"][0]["id"] == "test-model"
        assert KEY not in response.text
        assert not app.state.model_connections.summary()["general"]["configured"]
        for update in ({"endpoint": "https://evil.test/models"}, {"api_key": KEY + "\n"}):
            response = client.post(path, json={**body, **update}, headers=headers)
            assert response.status_code == 422 and KEY not in response.text
        assert KEY not in json.dumps(app.state.model_connections.summary())
