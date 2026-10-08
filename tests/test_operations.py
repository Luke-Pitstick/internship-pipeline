"""Synthetic full-installation recovery; never touches an existing user installation."""

from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from pdf_fixtures import textual_pdf
from test_owner_app import PASSWORD
from test_tailored_resume import request
from test_tailored_resume import service as tailored_fixture

from internship_pipeline.app import create_app, runtime_settings
from internship_pipeline.identity import Identity
from internship_pipeline.model_connections import ModelConnectionStore
from internship_pipeline.models import Settings
from internship_pipeline.operations import (
    OperationError,
    backup_installation,
    installation_lock,
    restore_installation,
    verify_backup,
)
from internship_pipeline.profiles.imports import ResumeImports, Review, Selection
from internship_pipeline.resumes.master import MasterResumes
from internship_pipeline.resumes.tailored import TailoredResumes
from internship_pipeline.storage import Store, enqueue

service = tailored_fixture


def identity(root):
    service = Identity(root / "identity.sqlite3")
    token = service.setup_token()
    service.claim(token, "owner", PASSWORD)
    return service


@pytest.mark.parametrize("name", ["persistent?synthetic", "persistent#synthetic", "space ünicode"])
def test_backup_restore_reserved_paths_preserves_both_database_identities(tmp_path, name):
    root = tmp_path / name
    settings = Settings(database_path=root / "state.sqlite3", artifact_dir=root / "artifacts")
    store = Store(settings.database_path)
    account = identity(root)
    with store.connection() as db:
        enqueue(db, "match", "synthetic-job", {"job_id": "synthetic"}, 1)
    ModelConnectionStore(store.path, root / "model-credentials.key")
    backup = tmp_path / (name + "-backup")
    restored = tmp_path / (name + "-restored")
    backup_installation(root, settings, backup)
    verify_backup(backup)
    with sqlite3.connect(backup / "state.sqlite3") as db:
        assert db.execute("SELECT key FROM tasks").fetchone()[0] == "synthetic-job"
    restore_installation(backup, restored)
    with Store(restored / "state.sqlite3").connection() as db:
        assert db.execute("SELECT key FROM tasks").fetchone()[0] == "synthetic-job"
    assert Identity(restored / "identity.sqlite3").login("owner", PASSWORD)
    assert account.claimed()
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        [name, name + "-backup", name + "-restored"]
    )


@pytest.mark.parametrize("database", ["state.sqlite3", "identity.sqlite3"])
@pytest.mark.parametrize("wrong", ["empty", "unrelated", "swapped"])
def test_backup_verification_refuses_hash_valid_wrong_database(service, tmp_path, database, wrong):
    identity(tmp_path)
    backup = tmp_path.parent / (tmp_path.name + "-backup")
    backup_installation(tmp_path, service.settings, backup)
    target = backup / database
    target.unlink()
    with sqlite3.connect(target) as db:
        if wrong == "unrelated":
            db.execute("CREATE TABLE unrelated(value TEXT)")
        elif wrong == "swapped":
            other = "identity.sqlite3" if database == "state.sqlite3" else "state.sqlite3"
            with sqlite3.connect(backup / other) as source:
                source.backup(db)
    manifest_path = backup / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][database] = {
        "size": target.stat().st_size,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(OperationError, match="verification"):
        verify_backup(backup)


@pytest.mark.parametrize("database", ["state.sqlite3", "identity.sqlite3"])
def test_backup_refuses_wrong_source_database_before_publishing(tmp_path, database):
    root = tmp_path / "synthetic"
    settings = Settings(database_path=root / "state.sqlite3", artifact_dir=root / "artifacts")
    store = Store(settings.database_path)
    identity(root)
    ModelConnectionStore(store.path, root / "model-credentials.key")
    (root / database).unlink()
    with sqlite3.connect(root / database) as db:
        db.execute("CREATE TABLE unrelated(value TEXT)")
    target = tmp_path / "backup"
    with pytest.raises(OperationError, match="schema"):
        backup_installation(root, settings, target)
    assert not target.exists()
    assert not list(tmp_path.glob(".pipeline-backup-*"))


def test_full_restore_preserves_encryption_provenance_documents_auth_and_no_replay(
    service, tmp_path
):
    root = tmp_path
    identity(root)
    imports = ResumeImports(service.store)
    uploaded = imports.upload(
        textual_pdf("Synthetic Source\nExperience\nBuilt 12 APIs."),
        "pdf",
        service.profiles.read().revision,
    )
    imports.confirm(
        uploaded["id"],
        Review(
            expected_revision=service.profiles.read().revision,
            confirmed=True,
            selections=[Selection(line_id=uploaded["lines"][2]["id"], kind="experience")],
        ),
    )
    request(service)
    assert service.process_next()
    draft = service.latest(service.job_id)
    pdf = service.pdf(draft["key"])
    master = MasterResumes(service.store, service.settings)
    master.request(service.profiles.read().revision)
    assert master.process_next()
    original_master = master.latest()["key"]
    master_pdf = master.pdf(original_master)
    (root / "uploads").mkdir()
    (root / "uploads/synthetic.pdf").write_bytes(textual_pdf("Synthetic upload"))
    from internship_pipeline.email_integrations import EmailIntegrations

    EmailIntegrations(service.store, service.connections, transport=lambda *args: "accepted")
    with service.store.transaction() as db:
        db.execute(
            "INSERT INTO email_deliveries(id,revision,created,status,title,body,delivered_at) "
            "VALUES('confirmed',1,1,'accepted','Synthetic alert','Synthetic body',1)"
        )
        db.execute(
            "INSERT INTO email_deliveries(id,revision,created,status,title,body) "
            "VALUES('synthetic',1,1,'sending','Synthetic alert','Synthetic body')"
        )
        enqueue(db, "email_delivery", "confirmed-task", {"id": "confirmed"}, 1)
        db.execute("UPDATE tasks SET status='done' WHERE key='confirmed-task'")
        enqueue(db, "email_delivery", "uncertain", {"id": "synthetic"}, 1)
        db.execute(
            "UPDATE tasks SET status='running',lease_until=99999999999 WHERE key='uncertain'"
        )
    target = root.parent / (root.name + "-backup")
    fresh = root.parent / (root.name + "-restore")
    backup_installation(root, service.settings, target)
    assert not list(target.glob("*-wal")) and not list(target.glob("*-shm"))
    restore_installation(target, fresh)
    settings = runtime_settings(fresh, fresh / "config/settings.yaml")
    store = Store(settings.database_path)
    connections = ModelConnectionStore(store.path, fresh / "model-credentials.key")
    assert connections.ready_connection("general", 1)[1] == "synthetic-key"
    assert (fresh / "model-credentials.key").read_bytes() == (
        root / "model-credentials.key"
    ).read_bytes()
    restored = TailoredResumes(store, settings, connections=connections)
    assert (
        restored.latest(service.job_id)["key"] == draft["key"] and restored.pdf(draft["key"]) == pdf
    )
    assert MasterResumes(store, settings).pdf(original_master) == master_pdf
    assert (fresh / "uploads/synthetic.pdf").read_bytes() == (
        root / "uploads/synthetic.pdf"
    ).read_bytes()
    with store.connection() as db:
        assert (
            db.execute(
                "SELECT digest,lines FROM resume_imports WHERE id=?", (uploaded["id"],)
            ).fetchone()
            is not None
        )
        assert db.execute(
            "SELECT status,delivered_at FROM email_deliveries WHERE id='confirmed'"
        ).fetchone()[:] == ("accepted", 1)
        assert (
            db.execute("SELECT status FROM email_deliveries WHERE id='synthetic'").fetchone()[0]
            == "uncertain"
        )
        assert (
            db.execute("SELECT status FROM tasks WHERE key='confirmed-task'").fetchone()[0]
            == "done"
        )
        assert (
            db.execute("SELECT status FROM tasks WHERE key='uncertain'").fetchone()[0] == "failed"
        )
        assert len(store.list_jobs()) == 1
    recovered = Identity(fresh / "identity.sqlite3")
    assert recovered.login("owner", PASSWORD)
    with recovered.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM owner_sessions").fetchone()[0] == 1
    assert all(p.stat().st_mode & 0o077 == 0 for p in fresh.rglob("*") if p.is_file())
    recovered.recover("owner", "synthetic-new-password")
    assert not recovered.login("owner", PASSWORD)
    assert recovered.login("owner", "synthetic-new-password")


def test_backup_active_instance_key_mismatch_tampering_and_fresh_only(service, tmp_path):
    identity(tmp_path)
    target = tmp_path.parent / (tmp_path.name + "-backup")
    with installation_lock(tmp_path):
        with pytest.raises(OperationError, match="Stop"):
            backup_installation(tmp_path, service.settings, target)
    backup_installation(tmp_path, service.settings, target)
    with pytest.raises(OperationError, match="new backup"):
        backup_installation(tmp_path, service.settings, target)
    with pytest.raises(OperationError, match="new directory"):
        restore_installation(target, tmp_path)
    (target / "model-credentials.key").write_bytes(b"wrong-key")
    with pytest.raises(OperationError, match="verification"):
        verify_backup(target)
    assert not list(target.parent.glob(".pipeline-restore-*"))


def test_backup_disk_failure_cleanup_and_symlink_refusal(service, tmp_path, monkeypatch):
    identity(tmp_path)
    target = tmp_path.parent / (tmp_path.name + "-backup")
    import internship_pipeline.operations as operations

    original = operations.shutil.copyfile

    def fail(*args):
        raise OSError("synthetic ENOSPC")

    monkeypatch.setattr(operations.shutil, "copyfile", fail)
    with pytest.raises(OSError):
        backup_installation(tmp_path, service.settings, target)
    assert not target.exists()
    assert not list(target.parent.glob(".pipeline-backup-*"))
    monkeypatch.setattr(operations.shutil, "copyfile", original)
    original_publish = operations.os.rename
    monkeypatch.setattr(operations.os, "rename", fail)
    with pytest.raises(OSError):
        backup_installation(tmp_path, service.settings, target)
    assert not target.exists()
    monkeypatch.setattr(operations.os, "rename", original_publish)
    (service.settings.artifact_dir / "unsafe").symlink_to(tmp_path / "identity.sqlite3")
    with pytest.raises(OperationError, match="Symbolic"):
        backup_installation(tmp_path, service.settings, target)


def test_diagnostics_redacted_authorization_worker_staleness_retry(service, tmp_path):
    identity(tmp_path)
    status = tmp_path / "supervisor.json"
    status.write_text(json.dumps({"healthy": True, "at": 1, "roles": ["matcher", "secret-role"]}))
    with service.store.transaction() as db:
        enqueue(db, "match", "failed-model", {"job_id": service.job_id}, 1)
        db.execute(
            "UPDATE tasks SET status='failed',error='token=secret "
            "/private/resume.pdf private payload' WHERE key='failed-model'"
        )
        db.execute("UPDATE targets SET error='private board response',last_attempt=1")
    app = create_app(
        tmp_path,
        origin="http://localhost:8080",
        settings=service.settings,
        supervisor_status=status,
    )
    with TestClient(app, base_url="http://localhost:8080") as client:
        assert client.get("/api/diagnostics").status_code == 401
        headers = {"X-CSRF-Token": client.get("/api/session").json()["csrf"]}
        response = client.post(
            "/api/login", headers=headers, json={"username": "owner", "password": PASSWORD}
        )
        headers = {"X-CSRF-Token": response.json()["csrf"]}
        data = client.get("/api/diagnostics").json()
        assert not data["workers"]["healthy"] and data["workers"]["roles"] == ["matcher"]
        assert "secret" not in json.dumps(data) and "/private/" not in json.dumps(data)
        task = data["failed"][0]["id"]
        assert client.post(f"/api/diagnostics/{task}/retry", json={}).status_code == 403
        assert (
            client.post(f"/api/diagnostics/{task}/retry", headers=headers, json={}).status_code
            == 200
        )
        with pytest.raises(OperationError):
            backup_installation(tmp_path, service.settings, tmp_path.parent / "active-backup")


def test_killed_collection_worker_recovers_checkpoint_without_network(tmp_path, monkeypatch):
    import asyncio
    import os
    import subprocess
    import sys

    from internship_pipeline.models import Settings
    from internship_pipeline.search_runs import SearchRuns, SourceSave

    root = tmp_path / "runtime"
    root.mkdir()
    store = Store(root / "state.sqlite3")
    runs = SearchRuns(store)
    search = runs.save(
        SourceSave(name="Synthetic interrupted", board="synthetic", expected_revision=0)
    )["searches"][0]
    run = runs.start(search["id"])["run"]
    script = """
import asyncio,os,signal
from pathlib import Path
from internship_pipeline.storage import Store
from internship_pipeline.search_runs import SearchRuns
from internship_pipeline.models import FetchResult,SourceJob,Settings
from internship_pipeline.sources import ats
from internship_pipeline.operations import installation_lock
root=Path(os.environ['SYNTHETIC_RECOVERY_ROOT'])
store=Store(root/'state.sqlite3')
async def fetch(*args):
    return FetchResult(jobs=[SourceJob(source='greenhouse',source_id='1',board_id='browser-greenhouse-synthetic',company='Synthetic',title='Internship',description='Python',apply_url='https://example.test/1')])
ats.fetch_company=fetch
def killed(*args,**kwargs):os.kill(os.getpid(),signal.SIGKILL)
store.ingest=killed
with installation_lock(root):
    asyncio.run(SearchRuns(store).process_next(Settings(database_path=store.path)))
"""
    process = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "SYNTHETIC_RECOVERY_ROOT": str(root)},
        capture_output=True,
        timeout=15,
    )
    assert process.returncode == -9
    assert runs.view(run["id"])["run"]["stage"] == "fetched"

    async def forbidden(*args):
        raise AssertionError("Restart must use persisted fetch")

    monkeypatch.setattr("internship_pipeline.sources.ats.fetch_company", forbidden)
    with store.transaction() as db:
        db.execute("UPDATE tasks SET lease_until=0")
    with installation_lock(root, offline=True):
        pass
    assert asyncio.run(
        SearchRuns(Store(store.path)).process_next(Settings(database_path=store.path))
    )
    assert len(store.list_jobs()) == 1 and runs.view()["run"]["collected"] == 1


def test_cli_backup_restore_and_local_owner_recovery(service, tmp_path, monkeypatch):
    import yaml

    from internship_pipeline.cli import main

    identity(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    (config / "settings.yaml").write_text(yaml.safe_dump(service.settings.model_dump(mode="json")))
    backup = tmp_path.parent / (tmp_path.name + "-cli-backup")
    fresh = tmp_path.parent / (tmp_path.name + "-cli-restored")
    assert main(["backup", str(backup), "--data-dir", str(tmp_path)]) == 0
    assert main(["restore", str(backup), str(fresh)]) == 0
    monkeypatch.setattr("builtins.input", lambda _: "restored-owner")
    monkeypatch.setattr("getpass.getpass", lambda _: "synthetic-restored-password")
    assert main(["recover-owner", "--data-dir", str(fresh)]) == 0
    assert Identity(fresh / "identity.sqlite3").login(
        "restored-owner", "synthetic-restored-password"
    )


def test_restore_preserves_confirmed_email_sheet_journals_and_encrypted_integrations(tmp_path):
    from test_sheets_integration import make, sync

    from internship_pipeline.email_integrations import EmailIntegrations
    from internship_pipeline.models import Settings
    from internship_pipeline.sheets_integration import SheetsIntegration

    sheets, provider, job, secret = make(tmp_path)
    email = EmailIntegrations(sheets.store, sheets.connections, transport=lambda *args: "accepted")
    assert email.schedule() == 1 and email.process_next()
    completed = sync(sheets)
    writes = len(provider.writes)
    interrupted = sheets.preview(1)
    sheets.request(interrupted["id"])
    with sheets.store.transaction() as db:
        db.execute(
            "UPDATE tasks SET status='running',lease_until=99999999999 "
            "WHERE kind='sheets_sync' AND status='pending'"
        )
        before = [tuple(r) for r in db.execute("SELECT * FROM sheets_checkpoints")]
    identity(tmp_path)
    target = tmp_path.parent / (tmp_path.name + "-backup")
    fresh = tmp_path.parent / (tmp_path.name + "-restored")
    backup_installation(
        tmp_path,
        Settings(database_path=sheets.store.path, artifact_dir=tmp_path / "artifacts"),
        target,
    )
    restore_installation(target, fresh)
    store = Store(fresh / "state.sqlite3")
    connections = ModelConnectionStore(store.path, fresh / "model-credentials.key")

    def forbidden(*args):
        raise AssertionError("Confirmed email must never replay")

    restored_email = EmailIntegrations(store, connections, transport=forbidden)
    assert restored_email.schedule() == 0 and not restored_email.process_next()
    assert restored_email.summary()["deliveries"][0]["status"] == "accepted"
    restored_sheets = SheetsIntegration(store, connections, provider_factory=lambda *args: provider)
    assert not restored_sheets.process_next() and len(provider.writes) == writes
    with store.connection() as db:
        assert (
            db.execute("SELECT state FROM sheets_runs WHERE id=?", (completed["id"],)).fetchone()[0]
            == "complete"
        )
        assert (
            db.execute("SELECT state FROM sheets_runs WHERE id=?", (interrupted["id"],)).fetchone()[
                0
            ]
            == "failed"
        )
        assert [tuple(r) for r in db.execute("SELECT * FROM sheets_checkpoints")] == before
        assert (
            connections.cipher.decrypt(
                db.execute("SELECT encrypted FROM sheets_config").fetchone()[0]
            ).decode()
            == secret
        )
        assert (
            connections.cipher.decrypt(
                db.execute("SELECT encrypted FROM email_config").fetchone()[0]
            ).decode()
            == "synthetic-email-secret"
        )

    from internship_pipeline.assessments import stored_view
    from internship_pipeline.profile_settings import ProfileSettings, SaveSettings

    with store.connection() as db:
        assert stored_view(db, store.get_job(job.id))["state"] == "complete"
    profiles = ProfileSettings(store)
    snapshot = profiles.read()
    profiles.save(
        SaveSettings(
            expected_revision=snapshot.revision,
            profile=snapshot.profile,
            preferences=snapshot.preferences.model_copy(
                update={
                    "soft": snapshot.preferences.soft.model_copy(
                        update={"skills": ["Synthetic revision change"]}
                    )
                }
            ),
        )
    )
    with store.connection() as db:
        assert stored_view(db, store.get_job(job.id))["state"] == "stale"
