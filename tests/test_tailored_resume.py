"""Synthetic end-to-end configured transport, durable queue and real PDF generation."""

import json
from pathlib import Path

import httpx
import pytest
from test_storage import posting

from internship_pipeline.model_connections import ModelConnectionStore
from internship_pipeline.models import FetchResult, Settings
from internship_pipeline.profile_settings import Preferences, Profile, ProfileSettings, SaveSettings
from internship_pipeline.providers.connections import ENDPOINTS, ConnectionInput, ProbeResult
from internship_pipeline.resumes.tailored import TailoredResumes
from internship_pipeline.storage import Store


@pytest.fixture
def service(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    profiles = ProfileSettings(store)
    profiles.save(
        SaveSettings(
            expected_revision=0,
            profile=Profile.model_validate_json(
                (Path(__file__).parent / "fixtures/master_profile.json").read_text()
            ),
            preferences=Preferences(),
        )
    )
    store.register_target("acme", "company", "{}", "ashby")
    job = store.ingest("acme", FetchResult(jobs=[posting()]), "p1")[0]
    models = ModelConnectionStore(store.path, tmp_path / "model-credentials.key")
    config = ConnectionInput(
        model="synthetic-model",
        endpoint=ENDPOINTS["general"],
        api_key="synthetic-key",
        expected_revision=0,
        max_output_tokens=1024,
    )
    models.save("general", config)
    revision = models.summary()["general"]["revision"]
    attempt, _, _ = models.reserve_test("general", revision)
    models.complete_test(attempt, ProbeResult("success", "synthetic-model", 12, 8))
    calls = []

    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["store"] is False
        assert payload["text"]["format"]["strict"] is True
        assert "untrusted_job" in payload["input"]
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "synthetic-model",
                "usage": {"input_tokens": 40, "output_tokens": 20},
                "output": [
                    {
                        "type": "message",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {"fact_ids": ["experience-api", "project-dashboard"]}
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    result = TailoredResumes(
        store,
        Settings(database_path=store.path, artifact_dir=tmp_path / "artifacts"),
        connections=models,
        transport=httpx.MockTransport(respond),
    )
    result.job_id = job.id
    result.calls = calls
    return result


def request(service):
    status = service.latest(service.job_id)
    return service.request(service.job_id, status["profile_revision"], status["model_revision"])


def test_real_generation_review_cache_and_revision_suppression(service):
    queued = request(service)
    assert queued["state"] == "pending"
    assert service.process_next()
    draft = service.latest(service.job_id)
    assert draft["state"] == "draft", draft
    assert draft["pages"] <= 2 and draft["warnings"]
    pdf = service.pdf(draft["key"])
    assert pdf.startswith(b"%PDF-")
    assert service.review(draft["key"])["state"] == "reviewed"
    assert request(service)["key"] == draft["key"] and len(service.calls) == 1
    profile = service.profiles.read()
    service.profiles.save(
        SaveSettings(
            expected_revision=profile.revision,
            profile=profile.profile.model_copy(update={"name": "New Synthetic Name"}),
            preferences=profile.preferences,
        )
    )
    assert service.latest(service.job_id)["state"] == "idle"
    with pytest.raises(FileNotFoundError):
        service.pdf(draft["key"])


def test_checkpoint_survives_compile_failure(service):
    compiler = service.compiler

    class Broken:
        def compile(self, source, deadline):
            raise OSError("private storage detail")

    service.compiler = Broken()
    request(service)
    service.process_next()
    assert service.latest(service.job_id)["state"] == "failed"
    service.compiler = compiler
    request(service)
    service.process_next()
    assert service.latest(service.job_id)["state"] == "draft"
    assert len(service.calls) == 1


def test_model_change_during_compile_suppresses_result(service):
    compiler = service.compiler

    class Change:
        def compile(self, source, deadline):
            service.connections.remove(
                "general", service.connections.summary()["general"]["revision"]
            )
            return compiler.compile(source, deadline)

    service.compiler = Change()
    request(service)
    service.process_next()
    assert service.latest(service.job_id)["state"] == "idle"
    with service.store.connection() as db:
        assert db.execute("SELECT filename FROM tailored_resumes").fetchone()[0] is None


@pytest.mark.parametrize("ids", [["invented"], ["experience-api", "experience-api"], []])
def test_unsupported_duplicate_and_empty_selection(service, ids):
    def respond(request):
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "synthetic-model",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "output": [
                    {
                        "type": "message",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": json.dumps({"fact_ids": ids})}],
                    }
                ],
            },
        )

    service.transport = httpx.MockTransport(respond)
    request(service)
    service.process_next()
    assert service.latest(service.job_id)["state"] == "failed"
    assert not list(service.root.glob("*.pdf"))


@pytest.mark.parametrize("status", [401, 429, 503, 400])
def test_http_failure_sanitized_and_bounded(service, status):
    service.transport = httpx.MockTransport(
        lambda _: httpx.Response(status, text="synthetic-key SECRET_PROVIDER_DETAIL")
    )
    request(service)
    service.process_next()
    value = service.latest(service.job_id)
    assert value["state"] == ("pending" if status in (429, 503) else "failed")
    assert "SECRET_PROVIDER_DETAIL" not in json.dumps(value)
    if status in (429, 503):
        for _ in range(2):
            with service.store.transaction() as db:
                db.execute("UPDATE tasks SET available_at=0 WHERE kind='tailored_resume'")
            service.process_next()
        assert service.latest(service.job_id)["state"] == "failed"
        assert service.latest(service.job_id)["attempts"] == 3
    with service.store.connection() as db:
        row = db.execute("SELECT * FROM tailored_attempts ORDER BY id LIMIT 1").fetchone()
        assert row["input_tokens"] is None and row["output_tokens"] is None


def test_missing_key_configuration_is_not_ready(service):
    service.connections.remove("general", service.connections.summary()["general"]["revision"])
    with pytest.raises(ValueError, match="successfully test"):
        request(service)


def test_lost_worker_lease_does_not_publish(service):
    compiler = service.compiler

    class Lose:
        def compile(self, source, deadline):
            content = compiler.compile(source, deadline)
            with service.store.transaction() as db:
                db.execute("UPDATE tasks SET token='other-worker' WHERE kind='tailored_resume'")
            return content

    service.compiler = Lose()
    request(service)
    service.process_next()
    with service.store.connection() as db:
        assert db.execute("SELECT filename FROM tailored_resumes").fetchone()[0] is None
    assert not list(service.root.glob("*.pdf"))


def test_corrupt_cache_recovers_without_reinference(service):
    request(service)
    service.process_next()
    with service.store.connection() as db:
        filename = db.execute("SELECT filename FROM tailored_resumes").fetchone()[0]
    (service.root / filename).write_bytes(b"corrupt")
    assert request(service)["state"] == "pending"
    service.process_next()
    assert service.latest(service.job_id)["state"] == "draft"
    assert len(service.calls) == 1


def test_owner_csrf_review_and_download_boundary(service, tmp_path):
    from fastapi.testclient import TestClient
    from test_owner_app import claim

    from internship_pipeline.app import create_app

    app = create_app(tmp_path, origin="http://localhost:8080", settings=service.settings)
    with TestClient(app, base_url="http://localhost:8080") as client:
        url = f"/api/jobs/{service.job_id}/resume"
        assert client.get(url).status_code == 401
        headers = claim(client)
        status = client.get(url).json()
        body = {
            "expected_profile_revision": status["profile_revision"],
            "expected_model_revision": status["model_revision"],
        }
        assert client.post(url, json=body).status_code == 403
        assert (
            client.post(
                url, json=body, headers={**headers, "Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert client.post(url, json=body, headers=headers).status_code == 202
        service.process_next()
        draft = client.get(url).json()
        assert draft["state"] == "draft"
        assert (
            client.post(
                f"/api/tailored-resume/{draft['key']}/review", headers=headers, json={}
            ).json()["state"]
            == "reviewed"
        )
        response = client.get(draft["download_url"])
        assert (
            response.status_code == 200 and "attachment" in response.headers["content-disposition"]
        )
        assert service.store.get_job(service.job_id).applied_at is None
        client.post("/api/logout", headers=headers)
        assert client.get(draft["download_url"]).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {
            "status": "incomplete",
            "model": "synthetic-model",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "output": [],
        },
        {
            "status": "completed",
            "model": "synthetic-model",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "output": [
                {
                    "type": "message",
                    "status": "completed",
                    "content": [{"type": "refusal", "refusal": "no"}],
                }
            ],
        },
        {"status": "completed", "model": "synthetic-model", "output": []},
        {
            "status": "completed",
            "model": "synthetic-model",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "output": [
                {
                    "type": "message",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "not json"}],
                }
            ],
        },
    ],
)
def test_malformed_incomplete_refusal_and_missing_usage(service, body):
    service.transport = httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    request(service)
    service.process_next()
    assert service.latest(service.job_id)["state"] == "failed"
    assert not list(service.root.glob("*.pdf"))


def test_transport_timeout_no_automatic_replay(service):
    def timeout(request):
        raise httpx.ReadTimeout("private", request=request)

    service.transport = httpx.MockTransport(timeout)
    request(service)
    service.process_next()
    value = service.latest(service.job_id)
    assert value["state"] == "failed" and value["attempts"] == 1
    assert "unknown" in value["error"]
    assert not service.process_next()


def test_concurrent_requests_share_one_task(service):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: request(service), range(4)))
    assert len({row["key"] for row in results}) == 1
    with service.store.connection() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM tasks WHERE kind='tailored_resume'").fetchone()[0] == 1
        )


def test_observation_refresh_preserves_cache_identity(service):
    first = request(service)
    with service.store.transaction() as db:
        db.execute("UPDATE jobs SET last_seen=last_seen+5")
    assert service.latest(service.job_id)["key"] == first["key"]


@pytest.mark.parametrize("provider", ["anthropic", "openrouter"])
def test_native_provider_durable_generation_and_pdf(service, provider):
    from test_general_providers import settings, synthetic_response

    current = service.connections.summary()["general"]["revision"]
    saved = service.connections.save("general", settings(provider, current))
    attempt, config, _ = service.connections.reserve_test("general", saved["revision"])
    service.connections.complete_test(attempt, ProbeResult("success", config.model, 40, 20))
    calls = []

    def respond(request):
        calls.append(str(request.url))
        assert str(request.url) == config.endpoint
        return httpx.Response(
            200,
            json=synthetic_response(
                provider,
                {"fact_ids": ["experience-api", "project-dashboard"]},
            ),
        )

    service.transport = httpx.MockTransport(respond)
    request(service)
    assert service.process_next()
    draft = service.latest(service.job_id)
    assert draft["state"] == "draft", draft
    assert service.pdf(draft["key"]).startswith(b"%PDF-")
    assert service.review(draft["key"])["state"] == "reviewed"
    assert request(service)["key"] == draft["key"] and len(calls) == 1
    with service.store.connection() as db:
        row = db.execute("SELECT * FROM tailored_attempts ORDER BY id DESC LIMIT 1").fetchone()
        assert row["effective_model"] == config.model
        assert (row["input_tokens"], row["output_tokens"]) == (40, 20)
