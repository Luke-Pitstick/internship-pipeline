from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from test_owner_app import api as api
from test_owner_app import claim
from test_owner_app import client as client


def test_owner_can_save_scoring_limits_and_stale_saves_are_rejected(client: TestClient):
    assert client.get("/api/scoring-limits").status_code == 401
    headers = claim(client)
    response = client.get("/api/scoring-limits")
    assert response.status_code == 200
    initial = response.json()
    assert initial["limits"] == {
        "hourly_calls": 60,
        "daily_calls": 200,
        "daily_tokens": 5_000_000,
    }
    body = {
        "expected_revision": initial["revision"],
        "hourly_calls": 300,
        "daily_calls": 1500,
        "daily_tokens": 50_000_000,
    }
    assert client.post("/api/scoring-limits", json=body).status_code == 403
    response = client.post("/api/scoring-limits", json=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["limits"]["daily_tokens"] == 50_000_000
    assert client.post("/api/scoring-limits", json=body, headers=headers).status_code == 409
    assert client.get("/api/scoring-limits").json() == response.json()
    for value in (0, -1, 1.5, True, "500"):
        bad = {**body, "expected_revision": response.json()["revision"], "daily_tokens": value}
        assert client.post("/api/scoring-limits", json=bad, headers=headers).status_code == 422


@pytest.mark.parametrize("field", ["hourly_calls", "daily_calls", "daily_tokens"])
def test_raising_limits_wakes_existing_jobs_and_worker_uses_saved_limits(
    tmp_path, monkeypatch, field
):
    import time

    from test_assessments import response, setup, view

    from internship_pipeline import assessments
    from internship_pipeline.models import Settings
    from internship_pipeline.pipeline import Pipeline
    from internship_pipeline.scoring_limits import SaveScoringLimits, ScoringSettings
    from internship_pipeline.storage import Store

    service, job = setup(tmp_path)
    monkeypatch.setenv("PIPELINE_DATA_DIR", str(tmp_path))
    settings = ScoringSettings(service.store)
    defaults = settings.view()["limits"]
    settings.save(SaveScoringLimits(expected_revision=0, **{**defaults, field: 1}))
    with service.store.transaction() as db:
        db.execute("DELETE FROM tasks")
        db.execute(
            "INSERT INTO assessment_attempts(identity,job_id,started,status,reserved_tokens,"
            "input_tokens,output_tokens) VALUES('previous',?,?,'success',2,1,1)",
            (job.id, time.time()),
        )
    fingerprint = service.enqueue(job.id)
    calls = []

    async def success(config, key, body, transport=None):
        calls.append(body)
        return response(body)

    monkeypatch.setattr(assessments, "request", success)
    worker = Pipeline(
        Settings(database_path=service.store.path),
        service.profiles.read().candidate(),
        service.store,
    )
    assert worker.process_next(["match"])
    assert not calls
    with service.store.connection() as db:
        task = db.execute("SELECT * FROM tasks").fetchone()
        assert task["status"] == "pending"
        assert task["error"] == "evaluation_budget_exhausted"
        assert task["available_at"] > time.time()
        assert task["attempts"] == 0
    raised = {"hourly_calls": 1000, "daily_calls": 5000, "daily_tokens": 500_000_000}
    settings.save(SaveScoringLimits(expected_revision=1, **raised))
    assert ScoringSettings(Store(service.store.path)).view()["limits"] == raised
    with service.store.connection() as db:
        task = db.execute("SELECT * FROM tasks").fetchone()
        assert task["available_at"] <= time.time()
        assert task["error"] is None
        assert task["key"] == "assessment:" + fingerprint
    assert worker.process_next(["match"])
    assert len(calls) == 1
    assert view(service, job)["state"] == "complete"
    settings.save(SaveScoringLimits(expected_revision=2, **defaults))
    assert view(service, job)["state"] == "complete"
    assert not worker.process_next(["match"])
    assert len(calls) == 1
