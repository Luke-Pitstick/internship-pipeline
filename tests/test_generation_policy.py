"""Durable automatic policy gates using real queue/provider/compiler integration."""

import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from test_assessments import response
from test_owner_app import claim
from test_tailored_resume import request
from test_tailored_resume import service as tailored_service  # noqa: F401

from internship_pipeline.app import create_app
from internship_pipeline.assessments import Assessments, current_identity
from internship_pipeline.generation_policy import (
    AutomationDenied,
    GenerationPolicies,
    GenerationPolicy,
    SaveGenerationPolicy,
)
from internship_pipeline.providers.connections import ENDPOINTS, ConnectionInput, ProbeResult


@pytest.fixture
def policies(tailored_service):  # noqa: F811
    service = tailored_service
    models = service.connections
    models.save(
        "jev",
        ConnectionInput(
            model="jev-latest",
            endpoint=ENDPOINTS["jev"],
            api_key="synthetic-jev-key",
            expected_revision=0,
        ),
    )
    revision = models.summary()["jev"]["revision"]
    attempt, _, _ = models.reserve_test("jev", revision)
    models.complete_test(attempt, ProbeResult("success", "jev-synthetic", 10, 10))
    matcher = Assessments(
        service.store,
        models,
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json=response(json.loads(req.content)))
        ),
    )
    matcher.evaluate(service.job_id)
    return GenerationPolicies(service)


def save(policies, **changes):
    view = policies.view()
    policy = {**view["policy"], **changes}
    return policies.save(SaveGenerationPolicy(expected_revision=view["revision"], **policy))


def edit_result(policies, **changes):
    with policies.store.transaction() as db:
        identity = current_identity(db, policies.store.get_job(policies.tailored.job_id))
        row = db.execute("SELECT result FROM assessments WHERE identity=?", (identity,)).fetchone()
        data = json.loads(row[0])
        data.update(changes)
        db.execute("UPDATE assessments SET result=? WHERE identity=?", (json.dumps(data), identity))


def task(policies):
    with policies.store.connection() as db:
        return db.execute("SELECT * FROM tasks WHERE kind='tailored_resume'").fetchone()


def test_default_off_durable_and_preview_never_calls_generation(policies):
    view = policies.view()
    assert view["policy"]["enabled"] is False
    assert view["preview"]["qualifying_count"] == 1
    assert policies.reconcile() == 0 and not policies.tailored.calls
    assert task(policies) is None
    save(policies, minimum_fit=80)
    assert GenerationPolicies(policies.tailored).view()["policy"]["minimum_fit"] == 80
    assert not policies.tailored.calls


@pytest.mark.parametrize(
    "changes,count",
    [
        ({"normalized_fit": 60}, 0),
        ({"recommendation": "review"}, 0),
        ({"eligible": None}, 0),
        ({"eligible": False}, 0),
    ],
)
def test_explicit_fit_recommendation_eligibility_rules(policies, changes, count):
    edit_result(policies, **changes)
    assert policies.view()["preview"]["qualifying_count"] == count
    view = policies.view(
        GenerationPolicy(
            minimum_fit=50,
            recommendation="recommended_or_review",
            eligibility="confirmed_or_unknown",
        )
    )
    assert view["preview"]["qualifying_count"] == (
        0 if changes.get("eligible", True) is False else 1
    )
    assert not policies.tailored.calls


def test_atomic_enqueue_guard_disable_and_manual_promotion(policies):
    service = policies.tailored
    with pytest.raises(AutomationDenied):
        service.request(service.job_id, 1, 1, automatic=True)
    save(policies, enabled=True)
    assert task(policies)["status"] == "pending"
    save(policies, enabled=False)
    assert task(policies)["status"] == "cancelled" and task(policies)["attempts"] == 0
    assert not service.process_next() and not service.calls
    request(service)
    assert json.loads(task(policies)["payload"])["origin"] == "manual"
    assert service.process_next() and service.latest(service.job_id)["state"] == "draft"
    assert len(service.calls) == 1
    assert policies.store.get_job(service.job_id).applied_at is None


def test_claim_rechecks_policy_if_settings_saved_after_enqueue(policies):
    save(policies, enabled=True)
    # Simulate a second process changing policy without the save cancellation sweep.
    with policies.store.transaction() as db:
        db.execute("UPDATE generation_policy SET data=?", (GenerationPolicy().model_dump_json(),))
    assert not policies.tailored.process_next()
    assert task(policies)["status"] == "cancelled"
    assert task(policies)["attempts"] == 0 and not policies.tailored.calls


def test_disable_race_after_claim_before_provider_io(policies, monkeypatch):
    save(policies, enabled=True)
    service = policies.tailored
    original = service.queue.claim

    def raced(*args, **kwargs):
        result = original(*args, **kwargs)
        save(policies, enabled=False)
        return result

    monkeypatch.setattr(service.queue, "claim", raced)
    assert service.process_next()
    assert task(policies)["status"] == "cancelled" and task(policies)["attempts"] == 0
    assert not service.calls
    with policies.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM tailored_attempts").fetchone()[0] == 0


def test_stale_assessment_enforces_enqueue_and_claim(policies):
    save(policies, enabled=True)
    service = policies.tailored
    snapshot = service.profiles.read()
    from internship_pipeline.profile_settings import SaveSettings

    service.profiles.save(
        SaveSettings(
            expected_revision=snapshot.revision,
            profile=snapshot.profile.model_copy(update={"name": "Changed synthetic name"}),
            preferences=snapshot.preferences,
        )
    )
    assert policies.view()["preview"]["qualifying_count"] == 0
    assert policies.reconcile() == 0
    assert not service.process_next() and not service.calls
    assert task(policies)["status"] == "cancelled"


def test_policy_saves_scans_and_concurrent_requests_share_artifact(policies):
    save(policies, enabled=True)
    for _ in range(3):
        save(policies, enabled=True)
        policies.reconcile()
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: policies.reconcile(), range(4)))
    assert policies.tailored.process_next()
    assert len(policies.tailored.calls) == 1
    for _ in range(3):
        save(policies, enabled=True)
        policies.reconcile()
    assert not policies.tailored.process_next()
    with policies.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM tailored_resumes").fetchone()[0] == 1
        assert (
            db.execute("SELECT COUNT(*) FROM tasks WHERE kind='tailored_resume'").fetchone()[0] == 1
        )
    assert len(list(policies.tailored.root.glob("*.pdf"))) == 1


def test_manual_pending_unchanged_and_automatic_failure_not_replayed(policies):
    request(policies.tailored)
    save(policies, enabled=False)
    assert task(policies)["status"] == "pending"
    assert policies.tailored.process_next()
    assert len(policies.tailored.calls) == 1
    save(policies, enabled=True)
    assert json.loads(task(policies)["payload"])["origin"] == "manual"
    with policies.store.transaction() as db:
        db.execute(
            "UPDATE tasks SET status='failed',payload=? WHERE kind='tailored_resume'",
            (
                json.dumps(
                    {"key": task(policies)["key"].removeprefix("tailored:"), "origin": "automatic"}
                ),
            ),
        )
    policies.reconcile()
    save(policies, enabled=True)
    assert task(policies)["status"] == "failed"


def test_owner_auth_validation_revision_conflict_and_preview_read_only(policies, tmp_path):
    app = create_app(tmp_path, origin="http://localhost:8080", settings=policies.tailored.settings)
    with TestClient(app, base_url="http://localhost:8080") as client:
        assert client.get("/api/generation-policy").status_code == 401
        headers = claim(client)
        before = client.get("/api/generation-policy").json()
        body = {**before["policy"], "minimum_fit": 90}
        assert client.post("/api/generation-policy/preview", json=body).status_code == 403
        assert (
            client.post("/api/generation-policy/preview", json=body, headers=headers).status_code
            == 200
        )
        assert client.get("/api/generation-policy").json()["revision"] == before["revision"]
        assert (
            client.post(
                "/api/generation-policy", json={**body, "expected_revision": 99}, headers=headers
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/generation-policy",
                json={**body, "minimum_fit": 101, "expected_revision": before["revision"]},
                headers=headers,
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/generation-policy",
                json={**body, "expected_revision": before["revision"]},
                headers=headers,
            ).status_code
            == 200
        )


@pytest.mark.parametrize("change", ["closed", "applied", "jev_revision"])
def test_current_job_and_assessment_revisions_are_required(policies, change):
    save(policies, enabled=True)
    service = policies.tailored
    if change == "jev_revision":
        revision = service.connections.summary()["jev"]["revision"]
        service.connections.save(
            "jev",
            ConnectionInput(
                model="changed-model",
                endpoint=ENDPOINTS["jev"],
                api_key="synthetic-new-key",
                expected_revision=revision,
            ),
        )
    else:
        job = service.store.get_job(service.job_id)
        from internship_pipeline.models import utcnow

        job = (
            job.model_copy(update={"status": "closed"})
            if change == "closed"
            else job.model_copy(update={"applied_at": utcnow()})
        )
        with policies.store.transaction() as db:
            db.execute(
                "UPDATE jobs SET data=?,status=? WHERE id=?",
                (job.model_dump_json(), job.status, job.id),
            )
    assert policies.view()["preview"]["qualifying_count"] == 0
    assert not service.process_next() and not service.calls
    assert task(policies)["status"] == "cancelled"


def test_run_limit_decline_keeps_attempt_budget_and_calls_untouched(policies, monkeypatch):
    from internship_pipeline.resumes import tailored
    from internship_pipeline.run_limits import RunLimitError

    def blocked(*args):
        raise RunLimitError("run_call_limit")

    monkeypatch.setattr(tailored, "reserve", blocked)
    save(policies, enabled=True)
    assert policies.tailored.process_next()
    assert task(policies)["attempts"] == 0 and task(policies)["status"] == "failed"
    assert task(policies)["error"] == "run_call_limit" and not policies.tailored.calls
    with policies.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM tailored_attempts").fetchone()[0] == 0
