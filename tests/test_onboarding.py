"""Fresh synthetic owner/API/SQLite/worker setup, without remote side effects."""

import asyncio
import json

import httpx
import pytest
from ats_scrapers.fetch import Fetcher, FetchResponse
from fastapi.testclient import TestClient
from test_model_connections import config
from test_owner_app import claim
from test_sheets_integration import synthetic_key

from internship_pipeline.app import create_app, runtime_settings
from internship_pipeline.email_integrations import EmailInput
from internship_pipeline.onboarding import Checkpoint, Onboarding, Start
from internship_pipeline.profile_settings import Preferences, Profile, SaveSettings
from internship_pipeline.providers.connections import ProbeResult
from internship_pipeline.search_runs import SourceSave
from internship_pipeline.sheets_integration import SheetsInput
from internship_pipeline.sheets_provider import GoogleSheets, SheetsFailure
from internship_pipeline.storage import Store


def make(root):
    settings = runtime_settings(root, None)
    app = create_app(root, origin="http://localhost", settings=settings)
    service = Onboarding(
        Store(settings.database_path),
        app.state.model_connections,
        app.state.email_integrations,
        app.state.sheets_integration,
    )
    return app, service, settings


def review(service, *, email="skip", sheets="skip", defer=True):
    service.checkpoint(Checkpoint(step="models", defer_models=defer))
    service.profiles.save(
        SaveSettings(expected_revision=0, profile=Profile(), preferences=Preferences())
    )
    for step in ("profile", "filters"):
        service.checkpoint(Checkpoint(step=step))
    service.searches.save(
        SourceSave(
            expected_revision=0, name="Synthetic search", source="greenhouse", board="example"
        )
    )
    service.checkpoint(Checkpoint(step="search"))
    return service.checkpoint(Checkpoint(step="integrations", email=email, sheets=sheets))


@pytest.mark.parametrize(
    "email,sheets",
    [("skip", "skip"), ("connect", "skip"), ("skip", "connect"), ("connect", "connect")],
)
def test_independent_integration_choices_resume_and_first_useful_result(
    tmp_path, monkeypatch, email, sheets
):
    app, service, settings = make(tmp_path)
    if email == "connect":
        service.email.transport = lambda *args: "accepted"
        service.email.save(
            EmailInput(
                expected_revision=0,
                host="smtp.example.test",
                username="synthetic",
                password="synthetic-secret",
                sender="from@example.test",
                recipient="to@example.test",
            )
        )
        service.email.test(1)
        assert service.email.process_next()
    if sheets == "connect":
        requests = []

        def transport(request):
            requests.append(request)
            if request.url.host == "oauth2.googleapis.com":
                return httpx.Response(
                    200,
                    json={"access_token": "synthetic", "expires_in": 3600, "token_type": "Bearer"},
                )
            return httpx.Response(
                200,
                json={
                    "properties": {"title": "Synthetic"},
                    "sheets": [
                        {"properties": {"title": "Jobs", "gridProperties": {"rowCount": 100}}}
                    ],
                },
            )

        service.sheets.provider_factory = lambda info, sheet: GoogleSheets(
            info, sheet, transport=httpx.MockTransport(transport)
        )
        service.sheets.save(
            SheetsInput(
                expected_revision=0,
                spreadsheet_id="synthetic-sheet",
                tab="Jobs",
                service_account=synthetic_key(),
            )
        )
        service.sheets.test(1)
        assert all(
            r.url.host in {"oauth2.googleapis.com", "sheets.googleapis.com"} for r in requests
        )
        assert not any(
            r.method == "POST" and r.url.host == "sheets.googleapis.com" for r in requests
        )
    state = review(service, email=email, sheets=sheets)
    assert not state["blockers"]
    restored = Onboarding(service.store, app.state.model_connections, service.email, service.sheets)
    assert restored.view()["step"] == "review"
    search_id = state["preview"]["searches"][0]["id"]
    started = restored.start(Start(preview=state["preview_token"], search_id=search_id))
    replay = restored.start(Start(preview=state["preview_token"], search_id=search_id))
    assert replay["run_id"] == started["run_id"]
    with pytest.raises(ValueError, match="Wait for"):
        restored.finish()

    async def perform(self, *args, **kwargs):
        return FetchResponse(
            200,
            json.dumps(
                {
                    "jobs": [
                        {
                            "id": 1,
                            "title": "Python internship",
                            "content": "Python",
                            "absolute_url": "https://boards.greenhouse.io/example/jobs/1",
                        }
                    ]
                }
            ),
            {},
            "synthetic",
        )

    monkeypatch.setattr(Fetcher, "_perform", perform)
    assert asyncio.run(restored.searches.process_next(settings))
    assert restored.view()["run"]["collected"] == 1
    assert restored.finish()["complete"]
    assert service.store.list_jobs()[0].applied_at is None
    assert "synthetic-secret" not in json.dumps(restored.view())


def test_failed_model_is_distinct_from_missing_and_correction_uses_authoritative_revision(tmp_path):
    app, service, _ = make(tmp_path)
    assert service.view()["preview"]["models"]["jev"]["status"] == "incomplete"
    saved = app.state.model_connections.save("jev", config())
    attempt, _, _ = app.state.model_connections.reserve_test("jev", saved["revision"])
    app.state.model_connections.complete_test(attempt, ProbeResult("timeout"))
    state = review(service, defer=False)
    assert state["preview"]["models"]["jev"]["status"] == "failed"
    assert any(b["step"] == "models" for b in state["blockers"])
    state = service.checkpoint(Checkpoint(step="models", defer_models=True))
    service.visit("review")
    assert not state["blockers"]
    assert state["preview"]["models"]["jev"]["status"] == "failed"


def test_missing_integrations_block_connect_but_skipping_does_not_mask_recorded_failures(tmp_path):
    _, service, _ = make(tmp_path)
    state = review(service, email="connect", sheets="connect")
    assert state["preview"]["email"]["status"] == "incomplete"
    assert len([b for b in state["blockers"] if b["step"] == "integrations"]) == 2
    service.email.transport = lambda *args: "credential_unavailable"
    service.email.save(
        EmailInput(
            expected_revision=0,
            host="smtp.example.test",
            username="synthetic",
            password="synthetic-secret",
            sender="from@example.test",
            recipient="to@example.test",
        )
    )
    service.email.test(1)
    service.email.process_next()
    assert service.view()["preview"]["email"]["status"] == "failed"
    state = service.checkpoint(Checkpoint(step="integrations", email="skip", sheets="skip"))
    assert not state["blockers"] and state["preview"]["email"]["status"] == "failed"


def test_preview_is_invalidated_by_saved_settings_and_no_run_is_admitted(tmp_path):
    _, service, _ = make(tmp_path)
    state = review(service)
    service.profiles.save(
        SaveSettings(
            expected_revision=1,
            profile=Profile(name="Synthetic updated"),
            preferences=Preferences(),
        )
    )
    with pytest.raises(ValueError, match="Settings changed"):
        service.start(
            Start(preview=state["preview_token"], search_id=state["preview"]["searches"][0]["id"])
        )
    assert service.searches.history()["runs"] == []
    assert service.view()["preview"]["profile_revision"] == 2


def test_owner_csrf_boundary_and_progress_survives_application_restart(tmp_path):
    app, service, settings = make(tmp_path)
    client = TestClient(app, base_url="http://localhost")
    assert client.get("/api/onboarding").status_code == 401
    headers = claim(client)
    assert client.post("/api/onboarding/visit", json={"step": "search"}).status_code == 403
    response = client.post("/api/onboarding/visit", json={"step": "search"}, headers=headers)
    assert response.json()["step"] == "search"
    other = create_app(tmp_path, origin="http://localhost", settings=settings)
    resumed = TestClient(other, base_url="http://localhost")
    resumed.cookies.update(client.cookies)
    assert resumed.get("/api/onboarding").json()["step"] == "search"
    assert service.profiles.read().revision == 0


def test_sheets_failed_access_check_is_durable_and_does_not_look_unconfigured(tmp_path):
    _, service, _ = make(tmp_path)
    service.sheets.save(
        SheetsInput(
            expected_revision=0,
            spreadsheet_id="synthetic-sheet",
            tab="Jobs",
            service_account=synthetic_key(),
        )
    )

    def revoked(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(
                200, json={"access_token": "synthetic", "expires_in": 3600, "token_type": "Bearer"}
            )
        return httpx.Response(403, json={})

    service.sheets.provider_factory = lambda info, sheet: GoogleSheets(
        info, sheet, transport=httpx.MockTransport(revoked)
    )
    with pytest.raises(SheetsFailure):
        service.sheets.test(1)
    assert not service.sheets.summary()["tested"]
    assert service.view()["preview"]["sheets"]["status"] == "failed"
    assert (
        Onboarding(service.store, service.models, service.email, service.sheets).view()["preview"][
            "sheets"
        ]["status"]
        == "failed"
    )
    saved = service.sheets.summary()["config"]
    service.sheets.save(SheetsInput(**saved, expected_revision=1))
    assert service.view()["preview"]["sheets"]["status"] == "incomplete"
