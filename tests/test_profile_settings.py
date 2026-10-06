"""Synthetic owner settings, immutable revisions, and task-boundary consumption."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from internship_pipeline import cli
from internship_pipeline.app import create_app
from internship_pipeline.models import FetchResult, MatchResult, Settings, SourceJob
from internship_pipeline.pipeline import Pipeline
from internship_pipeline.profile_settings import (
    Education,
    Fact,
    Preferences,
    Profile,
    ProfileSettings,
    RevisionConflict,
    SaveSettings,
)
from internship_pipeline.storage import Store


def save(profiles: ProfileSettings, name: str = "Synthetic Candidate"):
    return profiles.save(
        SaveSettings(
            expected_revision=profiles.read().revision,
            profile=Profile(name=name),
            preferences=Preferences(),
        )
    )


def test_revisions_persist_and_cannot_be_modified(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.sqlite3")
    profiles = ProfileSettings(store)
    empty = profiles.read()
    assert empty.revision == 0
    assert empty.profile.requires_sponsorship is None
    assert empty.candidate().constraints.degree_level is None
    first = save(profiles)
    second = save(profiles, "Updated Synthetic Candidate")
    assert second.revision == 2
    assert ProfileSettings(Store(store.path)).read() == second
    with store.connection() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM profile_settings_revisions").fetchone()[0] == 2
        )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM profile_settings_revisions WHERE revision=1")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE profile_settings_revisions SET profile='{}'")
    assert first.profile.name == "Synthetic Candidate"


def test_confirmed_evidence_and_hard_soft_separation(tmp_path: Path) -> None:
    profiles = ProfileSettings(Store(tmp_path / "state.sqlite3"))
    profile = Profile(
        facts=[
            Fact(id="supported", status="confirmed", text="Built a Python tool."),
            Fact(id="unknown", text="Unverified award"),
        ],
        education=[
            Education(
                id="school",
                status="confirmed",
                institution="Example U",
                degree="Bachelor",
                field="Computing",
            ),
            Education(id="unknown-school"),
        ],
    )
    preferences = Preferences.model_validate(
        {"hard": {"countries": ["Canada"]}, "soft": {"skills": ["Rust"], "locations": ["Toronto"]}}
    )
    first = profiles.save(
        SaveSettings(expected_revision=0, profile=profile, preferences=preferences)
    )
    candidate = first.candidate()
    assert [fact.id for fact in candidate.facts] == ["supported", "school"]
    assert candidate.constraints.countries == ["Canada"]
    assert candidate.constraints.locations == []
    assert candidate.preferred_locations == ["Toronto"]
    assert candidate.preferred_skills == ["Rust"]
    assert candidate.constraints.requires_sponsorship is None
    assert candidate.constraints.graduation_date is None
    assert "Unverified" not in candidate.model_dump_json()
    profile.facts[0].text = "Edited supported claim."
    second = profiles.save(
        SaveSettings(expected_revision=1, profile=profile, preferences=preferences)
    )
    assert second.profile.facts[0].id == "supported"
    assert first.candidate().revision != second.candidate().revision
    profile.education.append(
        Education(
            id="second-school", status="confirmed", institution="Second Example U", degree="Master"
        )
    )
    third = profiles.save(
        SaveSettings(expected_revision=2, profile=profile, preferences=preferences)
    )
    assert third.candidate().constraints.degree_level is None
    assert len(third.candidate().facts) == 3


@pytest.mark.parametrize(
    "profile",
    [
        {"email": "invalid"},
        {"available_from": "2027-08-01", "available_until": "2027-06-01"},
        {"facts": [{"id": "same"}, {"id": "same"}]},
        {"facts": [{"id": "same"}], "education": [{"id": "same"}]},
        {"facts": [{"status": "confirmed", "text": "  "}]},
        {"education": [{"status": "confirmed", "degree": "Bachelor"}]},
        {"requires_sponsorship": "unknown"},
        {"made_up_field": "not supported"},
    ],
)
def test_invalid_profiles_are_rejected(profile: dict) -> None:
    with pytest.raises(ValidationError):
        Profile.model_validate(profile)


def test_concurrent_save_has_exactly_one_winner(tmp_path: Path) -> None:
    profiles = ProfileSettings(Store(tmp_path / "state.sqlite3"))
    request = SaveSettings(expected_revision=0, profile=Profile(), preferences=Preferences())

    def attempt(_):
        try:
            return profiles.save(request).revision
        except RevisionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, range(2)))
    assert sorted(map(str, results)) == ["1", "conflict"]
    assert profiles.read().revision == 1


def test_authenticated_api_csrf_validation_and_conflict(tmp_path: Path) -> None:
    app = create_app(tmp_path, origin="http://localhost", static_dir=tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        url = "/api/profile-settings"
        assert client.get(url).status_code == 401
        csrf = client.get("/api/session").json()["csrf"]
        claim = client.post(
            "/api/claim",
            headers={"X-CSRF-Token": csrf},
            json={
                "setup_token": app.state.identity.setup_token(rotate=True),
                "username": "synthetic",
                "password": "synthetic-profile-password",
            },
        )
        headers = {"X-CSRF-Token": claim.json()["csrf"]}
        assert client.get(url).json()["revision"] == 0
        payload = {
            "expected_revision": 0,
            "profile": {"name": "Synthetic Candidate"},
            "preferences": {},
        }
        assert client.post(url, json=payload).status_code == 403
        assert (
            client.post(
                url, headers={**headers, "Origin": "https://evil.test"}, json=payload
            ).status_code
            == 403
        )
        result = client.post(url, headers=headers, json=payload)
        assert result.status_code == 200
        assert result.json()["revision"] == 1
        assert client.post(url, headers=headers, json=payload).status_code == 409
        assert client.get(url).json() == result.json()
        assert client.get(url).headers["cache-control"] == "no-store"
        invalid = client.post(
            url, headers=headers, json={**payload, "profile": {"email": "private-invalid-marker"}}
        )
        assert invalid.status_code == 422
        assert "private-invalid-marker" not in invalid.text
        assert invalid.json()["fields"][0]["field"] == "profile.email"
        assert client.post(url, headers=headers, content=b"x" * 262145).status_code == 413


def test_collector_refreshes_only_between_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path / "state.sqlite3")
    profiles = ProfileSettings(store)
    save(profiles, "First synthetic")
    companies = tmp_path / "companies.yaml"
    companies.write_text("[]")
    settings = Settings(database_path=store.path, companies_path=companies)
    observed = []

    class StopAfterTwo:
        def is_set(self):
            return len(observed) >= 2

        def set(self):
            pass

        def wait(self, _):
            pass

    async def collect(_store, profile, _settings):
        observed.append((profile.settings_revision, profile.name))
        if len(observed) == 1:
            save(profiles, "Second synthetic")
            assert profile.name == "First synthetic"
            assert profile.settings_revision == 1

    monkeypatch.setattr(cli.threading, "Event", StopAfterTwo)
    monkeypatch.setattr(cli, "collect_due", collect)
    assert cli.run_worker(settings, store, "collector", False) == 0
    assert observed == [(1, "First synthetic"), (2, "Second synthetic")]


def test_inflight_old_profile_match_cannot_publish_or_enqueue(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.sqlite3")
    profiles = ProfileSettings(store)
    snapshot = save(profiles)
    profile = snapshot.candidate()
    store.register_target("synthetic", "company", "{}", "ashby")
    store.ingest("synthetic", FetchResult(), profile.revision)
    store.ingest(
        "synthetic",
        FetchResult(
            jobs=[
                SourceJob(
                    source="ashby",
                    source_id="one",
                    board_id="synthetic",
                    company="Example",
                    title="Intern",
                    description="Synthetic job",
                    apply_url="https://example.test/job",
                )
            ]
        ),
        profile.revision,
    )
    job = store.list_jobs()[0]

    def matcher(*_):
        save(profiles, "Changed while inference ran")
        return MatchResult(fit="strong", eligible=True)

    pipeline = Pipeline(
        Settings(database_path=store.path),
        profile,
        store,
        matcher=matcher,
        settings_revision=snapshot.revision,
    )
    assert pipeline.process_next(["match"])
    assert store.get_match(job, profile.revision) is None
    with store.connection() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM tasks WHERE kind != 'match'").fetchone()[0]
            == 0
        )
    assert store.get_job(job.id).first_seen_at == job.first_seen_at
    assert store.get_job(job.id).applied_at is None
