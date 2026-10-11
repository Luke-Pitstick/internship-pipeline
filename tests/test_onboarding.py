"""Fresh synthetic owner/API/SQLite/worker setup, without remote side effects."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from test_model_connections import config
from test_owner_app import claim
from test_sheets_integration import synthetic_key

from internship_pipeline.app import create_app, runtime_settings
from internship_pipeline.email_integrations import EmailInput
from internship_pipeline.models import FetchResult, SourceJob
from internship_pipeline.onboarding import Checkpoint, Finish, Onboarding
from internship_pipeline.preference_searches import preference_searches
from internship_pipeline.profile_settings import (
    HardConstraints,
    Preferences,
    Profile,
    SaveSettings,
    SoftPreferences,
)
from internship_pipeline.providers.connections import ProbeResult
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
    finished = restored.finish(Finish(preview=state["preview_token"]))
    assert finished["complete"]
    assert not finished["has_jobs"]
    runs = restored.searches.history()["runs"]
    assert len(runs) == 1
    assert restored.finish(Finish(preview=state["preview_token"]))["complete"]
    assert restored.searches.history()["runs"] == runs

    def fetch(query, timeout):
        return FetchResult(
            jobs=[
                SourceJob(
                    source="jobspy:linkedin",
                    source_id="synthetic-1",
                    board_id=query.id,
                    company="Synthetic",
                    title="Python internship",
                    description="Python",
                    apply_url="https://example.test/jobs/1",
                    source_url="https://example.test/jobs/1",
                )
            ]
        )

    monkeypatch.setattr("internship_pipeline.sources.jobspy.fetch_search", fetch)
    assert asyncio.run(restored.searches.process_next(settings))
    assert restored.searches.view(runs[0]["id"])["run"]["collected"] == 1
    assert restored.view()["complete"]
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
        service.finish(Finish(preview=state["preview_token"]))
    assert service.searches.history()["runs"] == []
    assert service.view()["preview"]["profile_revision"] == 2


def test_owner_csrf_boundary_and_progress_survives_application_restart(tmp_path):
    app, service, settings = make(tmp_path)
    client = TestClient(app, base_url="http://localhost")
    assert client.get("/api/onboarding").status_code == 401
    headers = claim(client)
    assert client.post("/api/onboarding/visit", json={"step": "filters"}).status_code == 403
    response = client.post("/api/onboarding/visit", json={"step": "filters"}, headers=headers)
    assert response.json()["step"] == "filters"
    other = create_app(tmp_path, origin="http://localhost", settings=settings)
    resumed = TestClient(other, base_url="http://localhost")
    resumed.cookies.update(client.cookies)
    assert resumed.get("/api/onboarding").json()["step"] == "filters"
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


def test_searches_follow_roles_and_hard_locations_without_adding_eligibility_claims():
    preferences = Preferences(
        hard=HardConstraints(
            countries=["Canada", "US"],
            locations=["Toronto", "Denver"],
            term_keywords=["Summer 2027"],
        ),
        soft=SoftPreferences(
            roles=["Software engineering", "UX research"], locations=["London"], skills=["Python"]
        ),
    )
    searches = preference_searches(preferences)
    assert len(searches) == 8
    assert {search.country for search in searches} == {"canada", "usa"}
    assert {search.location for search in searches} == {"Toronto", "Denver"}
    assert {search.search_term for search in searches} == {
        "Software engineering internship",
        "UX research internship",
    }
    assert all(search.sites == ["indeed"] for search in searches)
    assert preferences.hard.term_keywords == ["Summer 2027"]
    assert preferences.soft.skills == ["Python"]


def test_unrestricted_and_unsupported_regions_do_not_default_to_usa():
    search = preference_searches(Preferences())[0]
    assert (search.country, search.location, search.sites) == ("worldwide", "", ["linkedin"])
    search = preference_searches(
        Preferences(
            hard=HardConstraints(countries=["Antarctica"]),
            soft=SoftPreferences(locations=["McMurdo"]),
        )
    )[0]
    assert (search.country, search.location, search.sites) == (
        "worldwide",
        "McMurdo, Antarctica",
        ["linkedin"],
    )


def test_finish_saves_latest_queries_once_and_preserves_manual_sources(tmp_path):
    from internship_pipeline.search_runs import SourceSave

    _, service, _ = make(tmp_path)
    state = review(service)
    service.searches.save(SourceSave(expected_revision=0, name="Manual", board="example"))
    service.profiles.save(
        SaveSettings(
            expected_revision=1,
            profile=Profile(),
            preferences=Preferences(
                hard=HardConstraints(countries=["CA"]),
                soft=SoftPreferences(roles=["Design", "Engineering"]),
            ),
        )
    )
    with pytest.raises(ValueError, match="Settings changed"):
        service.finish(Finish(preview=state["preview_token"]))
    state = service.view()
    assert len(state["preview"]["searches"]) == 2
    assert service.finish(Finish(preview=state["preview_token"]))["complete"]
    assert len(service.searches.settings()["searches"]) == 3
    assert len(service.searches.history()["runs"]) == 2
    service.finish(Finish(preview=state["preview_token"]))
    assert len(service.searches.settings()["searches"]) == 3


@pytest.mark.parametrize("failed", [False, True])
def test_empty_or_failed_collection_cannot_reopen_completed_setup(tmp_path, monkeypatch, failed):
    app, service, settings = make(tmp_path)
    state = review(service)
    service.finish(Finish(preview=state["preview_token"]))
    monkeypatch.setattr(
        "internship_pipeline.sources.jobspy.fetch_search",
        lambda *args: FetchResult(
            jobs=[],
            complete=not failed,
            error="synthetic outage" if failed else None,
        ),
    )
    assert asyncio.run(service.searches.process_next(settings))
    restored = Onboarding(service.store, app.state.model_connections, service.email, service.sheets)
    assert restored.view()["complete"]
    assert not restored.view()["has_jobs"]
    assert len(restored.searches.history()["runs"]) == 1


def test_finish_requires_review_and_rolls_back_if_queueing_fails(tmp_path, monkeypatch):
    _, service, _ = make(tmp_path)
    with pytest.raises(ValueError, match="Review this setup step"):
        service.finish(Finish(preview=service.view()["preview_token"]))
    state = review(service)

    def failed_queue(*args):
        raise ValueError("synthetic queue failure")

    monkeypatch.setattr(service.searches, "_start", failed_queue)
    with pytest.raises(ValueError, match="synthetic queue failure"):
        service.finish(Finish(preview=state["preview_token"]))
    assert not service.view()["complete"]
    assert service.searches.settings()["searches"] == []


def test_unknown_checkpoint_resumes_at_an_existing_step_and_finish_requires_csrf(tmp_path):
    app, service, _ = make(tmp_path)
    with service.store.transaction() as db:
        db.execute("UPDATE onboarding_state SET data=json_set(data,'$.step','removed-step')")
    assert service.view()["step"] == "models"
    client = TestClient(app, base_url="http://localhost")
    assert client.post("/api/onboarding/finish", json={"preview": "0" * 64}).status_code == 401
    claim(client)
    assert client.post("/api/onboarding/finish", json={"preview": "0" * 64}).status_code == 403
