"""Synthetic Google auth/API and durable stable-ID/inward ownership acceptance."""

import copy
import json
from urllib.parse import unquote

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from test_email_integrations import make as email_fixture
from test_owner_app import claim

from internship_pipeline.app import create_app
from internship_pipeline.models import Settings
from internship_pipeline.sheets_integration import SheetsInput, SheetsIntegration, column_index
from internship_pipeline.sheets_provider import GoogleSheets, SheetsFailure, credential_info


def synthetic_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return json.dumps(
        {
            "type": "service_account",
            "project_id": "synthetic-test",
            "private_key_id": "synthetic-key-id",
            "private_key": key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode(),
            "client_email": "synthetic@synthetic-test.iam.gserviceaccount.com",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


class FakeSheets:
    def __init__(self):
        self.values = [
            [
                "ID",
                "Company",
                "Title",
                "Location",
                "Score",
                "Posted",
                "Observed",
                "Deadline",
                "URL",
                "Source",
                "Manual",
                "Formula",
            ]
        ]
        self.formula_cells = set()
        self.writes = []
        self.fail = False
        self.revoked = False

    def metadata(self):
        if self.revoked:
            raise SheetsFailure("revoked")
        return {
            "properties": {"title": "Synthetic Opportunities"},
            "sheets": [{"properties": {"title": "Jobs", "gridProperties": {"rowCount": 1000}}}],
        }

    def rows(self, title):
        if self.revoked:
            raise SheetsFailure("revoked")
        return copy.deepcopy(self.values)

    def formulas(self, title):
        return self.formula_cells.copy()

    def close(self):
        pass

    def write(self, title, row, cells):
        self.writes.append((row, cells.copy()))
        while len(self.values) < row:
            self.values.append([])
        for column, value in cells.items():
            index = column_index(column)
            while len(self.values[row - 1]) <= index:
                self.values[row - 1].append("")
            self.values[row - 1][index] = value
            if self.fail:
                self.fail = False
                raise SheetsFailure("uncertain")


def make(tmp_path, **config):
    email, job = email_fixture(tmp_path)
    provider = FakeSheets()
    service = SheetsIntegration(
        email.store, email.connections, provider_factory=lambda *args: provider
    )
    key = synthetic_key()
    service.save(
        SheetsInput(
            expected_revision=0,
            spreadsheet_id="synthetic-sheet-id",
            tab="Jobs",
            service_account=key,
            **config,
        )
    )
    service.test(1)
    return service, provider, job, key


def sync(service):
    preview = service.preview(service.summary()["revision"])
    assert not preview["conflicts"]
    service.request(preview["id"])
    assert service.process_next()
    return preview


def test_encrypted_key_dry_run_stable_id_notes_formulas_and_idempotent(tmp_path):
    service, provider, job, key = make(tmp_path)
    plan = service.preview(1)
    assert not provider.writes and plan["rows"] == 1
    assert "private_key" not in json.dumps(service.summary())
    assert json.loads(key)["private_key"].encode() not in service.store.path.read_bytes()
    # Preserve unrelated notes and formulas on a row already keyed by stable job ID.
    provider.values.append(
        [job.id, "", "", "", "", "", "", "", "", "", "Manual note", "=SUM(E2:E3)"]
    )
    provider.formula_cells.add((2, "L"))
    sync(service)
    assert provider.values[1][10:] == ["Manual note", "=SUM(E2:E3)"]
    assert all(set(cells) <= {*"ABCDEFGHIJ"} for _, cells in provider.writes)
    sync(service)
    assert len(provider.values) == 2
    assert provider.values[1][0] == job.id


def test_actual_formula_in_owned_column_and_duplicates_require_review(tmp_path):
    service, provider, job, _ = make(tmp_path)
    provider.values.append([job.id, "=UPPER(K2)"])
    provider.formula_cells.add((2, "B"))
    preview = service.preview(1)
    assert "Formula" in preview["conflicts"][0]["reason"]
    with pytest.raises(ValueError, match="conflicts"):
        service.request(preview["id"])
    provider.values.append([job.id])
    assert "Duplicate" in service.preview(1)["conflicts"][0]["reason"]
    assert not provider.writes


def test_partial_unknown_write_restart_re_reads_and_does_not_duplicate(tmp_path):
    service, provider, job, _ = make(tmp_path)
    plan = service.preview(1)
    service.request(plan["id"])
    provider.fail = True
    assert service.process_next()
    assert service.summary()["runs"][0]["state"] == "retrying"
    restart = SheetsIntegration(
        service.store, service.connections, provider_factory=lambda *args: provider
    )
    with service.store.connection() as db:
        db.execute("UPDATE tasks SET available_at=0 WHERE kind='sheets_sync'")
    assert restart.process_next()
    assert restart.summary()["runs"][0]["state"] == "complete"
    assert len(provider.values) == 2 and provider.values[1][0] == job.id
    with service.store.connection() as db:
        assert db.execute("SELECT completed FROM sheets_journal").fetchone()[0]


def test_remote_edit_after_preview_revocation_and_disable_stop_only_sync(tmp_path):
    service, provider, job, _ = make(tmp_path)
    plan = service.preview(1)
    service.request(plan["id"])
    provider.values.append([job.id, "Manual correction"])
    service.process_next()
    assert service.summary()["runs"][0]["state"] == "conflict"
    assert provider.values[1][1] == "Manual correction" and not provider.writes
    provider.values = provider.values[:1]
    plan = service.preview(1)
    service.request(plan["id"])
    provider.revoked = True
    service.process_next()
    assert service.summary()["runs"][0]["state"] == "failed"
    assert "revoked" in service.summary()["runs"][0]["error"]
    provider.revoked = False
    plan = service.preview(1)
    service.request(plan["id"])
    saved = service.summary()["config"]
    service.save(SheetsInput(expected_revision=1, **saved))
    service.process_next()
    assert service.summary()["runs"][0]["state"] == "cancelled"
    assert not provider.writes


def test_inward_status_notes_explicit_review_and_local_conflict_audit(tmp_path):
    service, provider, job, _ = make(tmp_path, inward_notes="K", inward_status="M")
    provider.values.append(
        [
            job.id,
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "Imported manual note",
            "=SUM(E2:E3)",
            "applied",
        ]
    )
    provider.formula_cells.add((2, "L"))
    sync(service)
    proposals = service.summary()["inward"]
    assert len(proposals) == 2 and not service.store.get_job(job.id).applied_at
    status = next(p for p in proposals if p["field"] == "application_status")
    note = next(p for p in proposals if p["field"] == "notes")
    service.resolve(status["id"], True)
    assert service.store.get_job(job.id).applied_at
    service.resolve(note["id"], True)
    with service.store.connection() as db:
        assert (
            db.execute("SELECT notes FROM job_workspace WHERE job_id=?", (job.id,)).fetchone()[0]
            == "Imported manual note"
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM sheets_inward WHERE state='accepted' AND resolved IS NOT NULL"
            ).fetchone()[0]
            == 2
        )
    assert provider.values[1][10] == "Imported manual note"
    provider.values[1][10] = "Changed remotely"
    sync(service)
    proposal = service.summary()["inward"][0]
    with service.store.connection() as db:
        db.execute("UPDATE job_workspace SET notes='Changed locally'")
    with pytest.raises(ValueError, match="Local state changed"):
        service.resolve(proposal["id"], True)


def test_formula_like_source_is_raw_data_csv_safe_and_no_formula(tmp_path):
    service, provider, job, _ = make(tmp_path)
    with service.store.connection() as db:
        updated = job.model_copy(
            update={
                "posting": job.posting.model_copy(
                    update={"company": '=IMPORTXML("http://evil.test")'}
                )
            }
        )
        db.execute("UPDATE jobs SET data=? WHERE id=?", (updated.model_dump_json(), job.id))
    sync(service)
    sync(service)
    assert provider.values[1][1].startswith("=IMPORTXML")
    assert "'=IMPORTXML" in service.csv()
    assert not provider.formula_cells


def test_provider_uses_official_auth_raw_and_formula_api_with_mock_http():
    calls = []

    def respond(request):
        calls.append(request)
        if str(request.url) == "https://oauth2.googleapis.com/token":
            assert b"assertion=" in request.content
            return httpx.Response(
                200,
                json={
                    "access_token": "synthetic-token",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        assert request.url.host == "sheets.googleapis.com"
        assert request.headers["authorization"] == "Bearer synthetic-token"
        if request.method == "POST":
            assert json.loads(request.content)["valueInputOption"] == "RAW"
            return httpx.Response(200, json={"totalUpdatedCells": 2})
        if "/values/" in request.url.path:
            assert request.url.params["valueRenderOption"] == "FORMULA"
            return httpx.Response(200, json={"values": [["ID"], ["stable"]]})
        if request.url.params.get("includeGridData") == "true":
            return httpx.Response(
                200,
                json={
                    "sheets": [
                        {
                            "data": [
                                {
                                    "startRow": 1,
                                    "startColumn": 11,
                                    "rowData": [
                                        {
                                            "values": [
                                                {
                                                    "userEnteredValue": {
                                                        "formulaValue": "=SUM(E2:E3)"
                                                    }
                                                }
                                            ]
                                        }
                                    ],
                                }
                            ]
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"properties": {"title": "Synthetic"}, "sheets": []})

    provider = GoogleSheets(
        credential_info(synthetic_key()),
        "synthetic-sheet-id",
        transport=httpx.MockTransport(respond),
    )
    provider.metadata()
    assert provider.rows("Owner's Jobs")[1] == ["stable"]
    assert provider.formulas("Owner's Jobs") == {(2, "L")}
    provider.write("Owner's Jobs", 2, {"A": "stable", "B": "=malicious()"})
    provider.close()
    assert unquote(calls[-2].url.params["ranges"]) == "'Owner''s Jobs'!A1:AZ10001"
    bad = json.loads(synthetic_key())
    bad["token_uri"] = "http://localhost/private"
    with pytest.raises(ValueError):
        credential_info(json.dumps(bad))


def test_owner_api_preview_queue_csv_and_csrf(tmp_path):
    service, provider, job, _ = make(tmp_path)
    app = create_app(
        tmp_path,
        origin="http://localhost:8080",
        settings=Settings(database_path=service.store.path),
    )
    app.state.sheets_integration.provider_factory = lambda *args: provider
    with TestClient(app, base_url="http://localhost:8080") as client:
        assert client.get("/api/sheets").status_code == 401
        headers = claim(client)
        assert client.post("/api/sheets/preview", json={"expected_revision": 1}).status_code == 403
        preview = client.post("/api/sheets/preview", json={"expected_revision": 1}, headers=headers)
        assert preview.status_code == 200 and not provider.writes
        assert (
            client.post(
                "/api/sheets/" + preview.json()["id"] + "/sync", json={}, headers=headers
            ).status_code
            == 200
        )
        assert app.state.sheets_integration.process_next()
        assert client.get("/api/sheets").json()["runs"][0]["state"] == "complete"
        export = client.get("/api/sheets/export.csv")
        assert export.status_code == 200 and job.id in export.text
        assert export.headers["cache-control"] == "no-store"
        client.post("/api/logout", headers=headers)
        assert client.get("/api/sheets/export.csv").status_code == 401


def test_scheduled_opt_in_bounded_retry_and_disconnect(tmp_path):
    service, provider, job, _ = make(tmp_path, enabled=True, interval_minutes=5)
    service.schedule()
    service.schedule()
    with service.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM tasks WHERE kind='sheets_sync'").fetchone()[0] == 1
    provider.revoked = True
    assert service.process_next()
    assert service.summary()["runs"][0]["state"] == "failed"
    provider.revoked = False
    plan = service.preview(1)
    service.request(plan["id"])
    provider.write = lambda *args: (_ for _ in ()).throw(SheetsFailure("retry"))
    for _ in range(3):
        with service.store.connection() as db:
            db.execute("UPDATE tasks SET available_at=0 WHERE kind='sheets_sync'")
        assert service.process_next()
    assert service.summary()["runs"][0]["state"] == "failed"
    assert not service.process_next()
    service.remove(1)
    assert service.summary()["config"] is None
    assert service.csv()


def test_pending_inward_change_cannot_apply_after_disconnect(tmp_path):
    service, provider, job, _ = make(tmp_path, inward_notes="K")
    provider.values.append([job.id, "", "", "", "", "", "", "", "", "", "Remote note"])
    sync(service)
    proposal = service.summary()["inward"][0]
    service.remove(1)
    with pytest.raises(ValueError, match="disconnected"):
        service.resolve(proposal["id"], True)
    service.resolve(proposal["id"], False)


def test_malformed_credentials_and_google_errors_are_safe():
    for value in (
        "[]",
        "{}",
        '{"type":"external_account","credential_source":{"url":"http://localhost"}}',
    ):
        with pytest.raises(ValueError, match="valid Google"):
            credential_info(value)
    for status, kind in (
        (401, "revoked"),
        (403, "revoked"),
        (429, "retry"),
        (503, "retry"),
        (400, "invalid"),
    ):

        def respond(request, status=status):
            if request.url.host == "oauth2.googleapis.com":
                return httpx.Response(
                    200,
                    json={"access_token": "synthetic", "expires_in": 3600, "token_type": "Bearer"},
                )
            return httpx.Response(status, json={"secret": "do-not-expose"})

        provider = GoogleSheets(
            credential_info(synthetic_key()),
            "synthetic-sheet-id",
            transport=httpx.MockTransport(respond),
        )
        with pytest.raises(SheetsFailure) as error:
            provider.rows("Jobs")
        assert error.value.status == kind and "do-not-expose" not in str(error.value)
        provider.close()
