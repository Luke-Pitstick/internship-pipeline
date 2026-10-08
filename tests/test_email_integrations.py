"""Synthetic SMTP settings, real durable queue, current assessment and auth behavior."""

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from test_assessments import assess, request_body, response, setup
from test_owner_app import claim

from internship_pipeline.app import create_app
from internship_pipeline.email_integrations import EmailInput, EmailIntegrations
from internship_pipeline.models import FetchResult, Settings
from internship_pipeline.profile_settings import ProfileSettings, SaveSettings


@pytest.mark.parametrize("outcome", ["accepted", "uncertain"])
def test_delivery_outcome_and_queue_checkpoint_rollback_together(tmp_path, outcome):
    calls = []
    service, _ = make(tmp_path, lambda *args: calls.append(args) or outcome)
    service.schedule()
    with service.store.connection() as db:
        db.executescript("""
            CREATE TRIGGER crash_email_checkpoint BEFORE UPDATE OF status ON tasks
            WHEN OLD.kind='email_delivery' AND NEW.status IN ('done','failed')
            BEGIN SELECT RAISE(ABORT, 'injected checkpoint crash'); END;
        """)
    with pytest.raises(sqlite3.IntegrityError, match="checkpoint crash"):
        service.process_next()
    with service.store.connection() as db:
        assert db.execute("SELECT status FROM email_attempts").fetchone()[0] == "pending"
        assert db.execute("SELECT status FROM email_deliveries").fetchone()[0] == "sending"
        db.execute("DROP TRIGGER crash_email_checkpoint")
        db.execute("UPDATE tasks SET lease_until=0 WHERE kind='email_delivery'")
    restarted = EmailIntegrations(service.store, service.connections, transport=service.transport)
    assert restarted.process_next()
    assert len(calls) == 1
    assert restarted.summary()["deliveries"][0]["status"] == "uncertain"


@pytest.mark.parametrize("outcome", ["accepted", "uncertain"])
def test_crash_after_outcome_commit_cannot_replay_transport(tmp_path, monkeypatch, outcome):
    calls = []
    service, _ = make(tmp_path, lambda *args: calls.append(args) or outcome)
    service.schedule()
    original = service.store.transaction

    @contextmanager
    def crash_after_commit():
        with original() as db:
            yield db
            recorded = db.execute("SELECT status FROM email_deliveries").fetchone()[0] == outcome
        if recorded:
            raise SystemExit("injected worker termination after outcome commit")

    with monkeypatch.context() as patch:
        patch.setattr(service.store, "transaction", crash_after_commit)
        with pytest.raises(SystemExit):
            service.process_next()
    with service.store.connection() as db:
        db.execute("UPDATE tasks SET lease_until=0 WHERE kind='email_delivery'")
    restarted = EmailIntegrations(service.store, service.connections, transport=service.transport)
    restarted.process_next()
    assert len(calls) == 1
    assert restarted.summary()["deliveries"][0]["status"] == outcome


@pytest.mark.parametrize("state", ["accepted", "uncertain", "cancelled"])
def test_terminal_delivery_admission_never_calls_transport(tmp_path, state):
    calls = []
    service, _ = make(tmp_path, lambda *args: calls.append(args) or "accepted")
    service.schedule()
    with service.store.connection() as db:
        db.execute("UPDATE email_deliveries SET status=?", (state,))
    assert service.process_next()
    assert calls == []
    assert service.summary()["deliveries"][0]["status"] == state
    assert not service.process_next()


@pytest.mark.parametrize(
    "change", ["profile", "model", "posting", "dismissed", "rejected", "closed", "applied"]
)
def test_queued_members_revalidate_before_transport(tmp_path, change):
    calls = []
    service, job = make(tmp_path, lambda *args: calls.append(args) or "accepted")
    assert service.schedule() == 1
    if change == "profile":
        profiles = ProfileSettings(service.store)
        snapshot = profiles.read()
        profiles.save(
            SaveSettings(
                expected_revision=snapshot.revision,
                profile=snapshot.profile,
                preferences=snapshot.preferences,
            )
        )
    elif change == "applied":
        service.store.mark_applied(job.id)
    else:
        with service.store.transaction() as db:
            if change == "model":
                db.execute("UPDATE model_attempts SET effective_model='changed-model'")
            elif change in {"dismissed", "rejected"}:
                db.execute(
                    "INSERT INTO job_workspace(job_id,dismissed,decision,updated) VALUES(?,?,?,?)",
                    (
                        job.id,
                        change == "dismissed",
                        "rejected" if change == "rejected" else None,
                        time.time(),
                    ),
                )
            else:
                current = job.model_copy(
                    update={"status": "closed"}
                    if change == "closed"
                    else {"content_hash": "changed"}
                )
                db.execute(
                    "UPDATE jobs SET data=?,status=?,content_hash=? WHERE id=?",
                    (current.model_dump_json(), current.status, current.content_hash, job.id),
                )
    assert service.process_next()
    assert calls == []
    assert service.summary()["deliveries"][0]["status"] == "cancelled"


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


def qualifying_alias(service, original):
    posting = original.posting.model_copy(
        update={
            "source_id": "2",
            "apply_url": "https://example.test/apply/2",
            "title": "Second Python internship",
        }
    )
    job = service.store.ingest("fixture", FetchResult(jobs=[posting]), "synthetic")[0]
    snapshot = ProfileSettings(service.store).read()
    body, evidence = request_body(job, snapshot, "jev-1.13.0")
    result = assess(job, snapshot, 1, "jev-latest", body, response(body), evidence)
    with service.store.transaction() as db:
        db.execute(
            "INSERT INTO assessments VALUES(?,?,?,?)",
            (result.identity, job.id, result.model_dump_json(), time.time()),
        )
    return job


def test_mixed_digest_rebuilds_body_and_prunes_pdf_members(tmp_path):
    calls = []
    service, first = make(tmp_path, lambda *args: calls.append(args) or "accepted")
    second = qualifying_alias(service, first)
    config = service.summary()["config"]
    service.save(
        EmailInput(**config, expected_revision=1).model_copy(
            update={"mode": "digest", "digest_hour": 0, "attach_pdf": True}
        )
    )
    pdf_jobs = []
    service.pdf_provider = lambda job: pdf_jobs.append(job) or b"%PDF-current"
    assert service.schedule() == 1
    service.store.mark_applied(first.id)
    assert service.process_next()
    assert len(calls) == 1
    assert first.id not in calls[0][3]
    assert second.id in calls[0][3]
    assert "Source timestamp" in calls[0][3] and "First observed" in calls[0][3]
    assert pdf_jobs == [second.id] and calls[0][-1] == [b"%PDF-current"]
    with service.store.connection() as db:
        assert [r[0] for r in db.execute("SELECT job_id FROM email_members")] == [second.id]


def test_member_change_during_pdf_lookup_cancels_before_admission(tmp_path):
    calls = []
    service, job = make(tmp_path, lambda *args: calls.append(args) or "accepted")
    config = service.summary()["config"]
    service.save(EmailInput(**config, expected_revision=1).model_copy(update={"attach_pdf": True}))
    service.schedule()

    def pdf(job_id):
        service.store.mark_applied(job_id)
        return b"%PDF-current"

    service.pdf_provider = pdf
    assert service.process_next() and calls == []
    assert service.summary()["deliveries"][0]["status"] == "cancelled"
    with service.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM email_attempts").fetchone()[0] == 0
    assert service.store.get_job(job.id).applied_at is not None


@pytest.mark.parametrize("during", ["pdf", "transport"])
def test_lost_lease_cannot_admit_or_publish_outcome(tmp_path, during):
    calls = []
    service, _ = make(tmp_path)
    config = service.summary()["config"]
    service.save(EmailInput(**config, expected_revision=1).model_copy(update={"attach_pdf": True}))
    service.schedule()

    def lose_lease():
        with service.store.transaction() as db:
            db.execute(
                "UPDATE tasks SET token='foreign',lease_until=? WHERE kind='email_delivery'",
                (time.time() + 120,),
            )

    def pdf(job_id):
        if during == "pdf":
            lose_lease()
        return b"%PDF-current"

    def transport(*args):
        calls.append(args)
        lose_lease()
        return "accepted"

    service.pdf_provider, service.transport = pdf, transport
    assert service.process_next()
    assert len(calls) == (1 if during == "transport" else 0)
    with service.store.connection() as db:
        assert (
            db.execute("SELECT token FROM tasks WHERE kind='email_delivery'").fetchone()[0]
            == "foreign"
        )
        assert service.summary()["deliveries"][0]["status"] == (
            "sending" if during == "transport" else "queued"
        )
        db.execute("UPDATE tasks SET lease_until=0 WHERE kind='email_delivery'")
    restarted = EmailIntegrations(
        service.store, service.connections, transport=lambda *args: calls.append(args) or "accepted"
    )
    assert restarted.process_next()
    assert len(calls) == 1
    assert restarted.summary()["deliveries"][0]["status"] == (
        "uncertain" if during == "transport" else "accepted"
    )


@pytest.mark.parametrize("after_commit", [False, True])
def test_crash_at_transport_attempt_admission_is_conservative(tmp_path, monkeypatch, after_commit):
    calls = []
    service, _ = make(tmp_path, lambda *args: calls.append(args) or "accepted")
    service.schedule()
    original = service.store.transaction

    @contextmanager
    def crash_at_attempt():
        pending = False
        with original() as db:
            yield db
            pending = bool(
                db.execute("SELECT 1 FROM email_attempts WHERE status='pending'").fetchone()
            )
            if pending and not after_commit:
                raise SystemExit("injected crash before admission commit")
        if pending and after_commit:
            raise SystemExit("injected crash after admission commit")

    with monkeypatch.context() as patch:
        patch.setattr(service.store, "transaction", crash_at_attempt)
        with pytest.raises(SystemExit):
            service.process_next()
    assert calls == []
    with service.store.connection() as db:
        db.execute("UPDATE tasks SET lease_until=0 WHERE kind='email_delivery'")
    assert service.process_next()
    assert len(calls) == (0 if after_commit else 1)
    assert service.summary()["deliveries"][0]["status"] == (
        "uncertain" if after_commit else "accepted"
    )


@pytest.mark.parametrize("change", ["threshold", "recommendation"])
def test_current_assessment_must_still_qualify_at_admission(tmp_path, change):
    calls = []
    service, _ = make(tmp_path, lambda *args: calls.append(args) or "accepted")
    service.schedule()
    with service.store.transaction() as db:
        result = json.loads(db.execute("SELECT result FROM assessments").fetchone()[0])
        if change == "threshold":
            result["normalized_fit"] = 0
        else:
            result["recommendation"] = "review"
        db.execute("UPDATE assessments SET result=?", (json.dumps(result),))
    assert service.process_next() and calls == []
    assert service.summary()["deliveries"][0]["status"] == "cancelled"


def test_credential_failure_is_terminal_until_explicit_owner_retry(tmp_path):
    calls = []
    service, _ = make(tmp_path, lambda *args: calls.append(args) or "accepted")
    service.schedule()
    with service.store.transaction() as db:
        encrypted = db.execute("SELECT encrypted FROM email_config").fetchone()[0]
        db.execute("UPDATE email_config SET encrypted=?", (b"unreadable-synthetic-secret",))
    assert service.process_next() and calls == []
    delivery = service.summary()["deliveries"][0]
    assert delivery["status"] == "failed"
    assert not service.process_next()
    with service.store.transaction() as db:
        db.execute("UPDATE email_config SET encrypted=?", (encrypted,))
    service.retry(delivery["id"])
    assert service.process_next() and len(calls) == 1
    assert service.summary()["deliveries"][0]["status"] == "accepted"


@pytest.mark.parametrize("outcome", ["unexpected", "exception"])
def test_ambiguous_transport_never_automatically_replays(tmp_path, outcome):
    calls = []

    def transport(*args):
        calls.append(args)
        if outcome == "exception":
            raise OSError("synthetic network interruption")
        return "unknown-outcome"

    service, _ = make(tmp_path, transport)
    service.schedule()
    assert service.process_next()
    assert service.summary()["deliveries"][0]["status"] == "uncertain"
    assert not service.process_next() and len(calls) == 1
