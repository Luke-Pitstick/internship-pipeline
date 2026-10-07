"""Synthetic SMTP settings, real durable queue, current assessment and auth behavior."""

import json
import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from test_assessments import assess, request_body, response, setup
from test_owner_app import claim

from internship_pipeline.app import create_app
from internship_pipeline.email_integrations import EmailInput, EmailIntegrations
from internship_pipeline.models import Settings


def make(tmp_path, transport=lambda *args: "accepted"):
    assessments, job = setup(tmp_path)
    snapshot = assessments.profiles.read()
    body, evidence = request_body(job, snapshot, "jev-1.13.0")
    result = assess(job, snapshot, 1, "jev-latest", body, response(body), evidence)
    with assessments.store.connection() as db:
        db.execute(
            "INSERT INTO assessments VALUES(?,?,?,?)",
            (result.identity, job.id, result.model_dump_json(), time.time()),
        )
    service = EmailIntegrations(assessments.store, assessments.connections, transport=transport)
    service.save(
        EmailInput(
            expected_revision=0,
            host="smtp.example.test",
            username="synthetic",
            password="synthetic-email-secret",
            sender="from@example.test",
            recipient="to@example.test",
            enabled=True,
        )
    )
    return service, job


def test_encryption_validation_no_pdf_and_deduplication(tmp_path):
    calls = []
    service, job = make(tmp_path, lambda *args: calls.append(args) or "accepted")
    assert b"synthetic-email-secret" not in service.store.path.read_bytes()
    assert "password" not in json.dumps(service.summary())
    assert service.schedule() == 1
    assert service.schedule() == 0
    assert service.process_next()
    assert calls[0][-1] == []
    assert "First observed" in calls[0][3] and "Source timestamp" in calls[0][3]
    assert service.summary()["deliveries"][0]["status"] == "accepted"
    assert not service.store.get_job(job.id).applied_at
    with pytest.raises(ValueError):
        EmailInput(expected_revision=0, host="bad/host", username="user", sender="x", recipient="x")


def test_digest_timezone_and_membership_survive_restart(tmp_path):
    service, _ = make(tmp_path)
    config = service.summary()["config"]
    service.save(
        EmailInput(**config, expected_revision=1).model_copy(
            update={"mode": "digest", "timezone": "America/Denver", "digest_hour": 9}
        )
    )
    assert service.schedule(datetime(2026, 10, 6, 14, 59, tzinfo=UTC).timestamp()) == 0
    assert service.schedule(datetime(2026, 10, 6, 15, 0, tzinfo=UTC).timestamp()) == 1
    restarted = EmailIntegrations(
        service.store, service.connections, transport=lambda *args: "accepted"
    )
    assert restarted.schedule(datetime(2026, 10, 6, 16, 0, tzinfo=UTC).timestamp()) == 0
    assert restarted.process_next()
    with service.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM email_members").fetchone()[0] == 1


def test_uncertain_interrupt_does_not_auto_resend_and_explicit_retry(tmp_path):
    calls = []
    service, _ = make(tmp_path, lambda *args: calls.append(args) or "accepted")
    service.schedule()
    task = service.queue.claim(["email_delivery"])
    with service.store.connection() as db:
        db.execute(
            "INSERT INTO email_attempts(delivery_id,started,status) VALUES(?,?,'pending')",
            (task.payload["id"], time.time()),
        )
        db.execute("UPDATE tasks SET lease_until=0 WHERE id=?", (task.id,))
    assert service.process_next() and calls == []
    assert service.summary()["deliveries"][0]["status"] == "uncertain"
    # A restored instance may retain its interrupted attempt pending until deliberate review.
    with service.store.connection() as db:
        db.execute(
            "INSERT INTO email_attempts(delivery_id,started,status) VALUES(?,?,'pending')",
            (task.payload["id"], time.time()),
        )
    service.retry(task.payload["id"])
    assert service.process_next() and len(calls) == 1


def test_retries_rejection_and_disable_cancel_queued(tmp_path):
    service, _ = make(tmp_path, lambda *args: "rejected")
    service.schedule()
    assert service.process_next()
    assert service.summary()["deliveries"][0]["status"] == "retrying"
    with service.store.connection() as db:
        db.execute("UPDATE tasks SET available_at=0 WHERE kind='email_delivery'")
    assert service.process_next()
    config = service.summary()["config"]
    service.save(EmailInput(**config, expected_revision=1).model_copy(update={"enabled": False}))
    assert not service.process_next()
    assert service.schedule() == 0
    assert service.summary()["deliveries"][0]["status"] == "cancelled"


def test_api_owner_csrf_redaction_and_real_queue(tmp_path):
    service, _ = make(tmp_path)
    app = create_app(
        tmp_path,
        origin="http://localhost:8080",
        settings=Settings(database_path=service.store.path),
    )
    with TestClient(app, base_url="http://localhost:8080") as client:
        assert client.get("/api/email").status_code == 401
        headers = claim(client)
        assert client.post("/api/email/test", json={"expected_revision": 1}).status_code == 403
        assert (
            client.post(
                "/api/email/test", json={"expected_revision": 1}, headers=headers
            ).status_code
            == 200
        )
        assert service.process_next()
        result = client.get("/api/email").json()
        assert result["deliveries"][0]["status"] == "accepted"
        assert "synthetic-email-secret" not in json.dumps(result)
        client.post("/api/logout", headers=headers)
        assert client.get("/api/email").status_code == 401


def test_optional_supported_pdf_and_missing_pdf_never_blocks_alert(tmp_path):
    calls = []
    service, job = make(tmp_path, lambda *args: calls.append(args) or "accepted")
    config = service.summary()["config"]
    service.save(EmailInput(**config, expected_revision=1).model_copy(update={"attach_pdf": True}))
    service.pdf_provider = lambda job_id: b"%PDF-synthetic"
    assert service.schedule() == 1 and service.process_next()
    assert calls[0][-1] == [b"%PDF-synthetic"]
    service.test(2)
    assert service.process_next() and calls[1][-1] == []


def test_retry_cap_and_uncertain_transport_are_inspectable(tmp_path):
    service, _ = make(tmp_path, lambda *args: "rejected")
    service.schedule()
    for _ in range(3):
        with service.store.connection() as db:
            db.execute("UPDATE tasks SET available_at=0 WHERE kind='email_delivery'")
        assert service.process_next()
    assert service.summary()["deliveries"][0]["status"] == "failed"
    assert not service.process_next()
    service.transport = lambda *args: "uncertain"
    service.retry(service.summary()["deliveries"][0]["id"])
    assert service.process_next()
    assert service.summary()["deliveries"][0]["status"] == "uncertain"
    assert not service.process_next()


def test_high_threshold_applied_and_stale_assessments_are_suppressed(tmp_path):
    service, job = make(tmp_path)
    service.store.mark_applied(job.id)
    assert service.schedule() == 0
    with service.store.connection() as db:
        db.execute("DELETE FROM model_attempts")
    assert service.schedule() == 0


def test_key_loss_does_not_silently_rekey_email_only_installation(tmp_path):
    from internship_pipeline.model_connections import ConnectionError, ModelConnectionStore

    service, _ = make(tmp_path)
    with service.store.connection() as db:
        db.execute("DELETE FROM model_credentials")
    service.connections.key_path.unlink()
    with pytest.raises(ConnectionError, match="Restore"):
        ModelConnectionStore(service.store.path, service.connections.key_path)


def test_final_attempt_crash_surfaces_uncertainty_without_replay(tmp_path):
    service, _ = make(tmp_path)
    service.schedule()
    task = service.queue.claim(["email_delivery"])
    with service.store.connection() as db:
        db.execute("UPDATE tasks SET attempts=3,lease_until=0 WHERE id=?", (task.id,))
        db.execute(
            "INSERT INTO email_attempts(delivery_id,started,status) VALUES(?,?,'pending')",
            (task.payload["id"], time.time()),
        )
    assert not service.process_next()
    assert service.summary()["deliveries"][0]["status"] == "uncertain"
