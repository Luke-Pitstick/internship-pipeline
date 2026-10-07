from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import pytest
from test_dashboard_api import api as dashboard_fixture
from test_dashboard_api import job

from internship_pipeline import job_workspace
from internship_pipeline.assessments import Assessment, identity, rubric_revision

api = dashboard_fixture


def seed(api, count=130):
    with sqlite3.connect(api.settings.database_path) as db:
        db.execute("DELETE FROM jobs")
        for i in range(count):
            item = job(f"synthetic-{i:05d}").model_copy(
                update={
                    "posting": job("x").posting.model_copy(
                        update={
                            "company": "Same" if i % 3 else "Alpha",
                            "title": "Same" if i % 3 else "Analytics",
                            "published_at": None
                            if i % 4 == 0
                            else datetime(2026, 1, 1 + i % 20, tzinfo=UTC),
                            "locations": [] if i % 4 == 0 else ["Denver" if i % 2 else "Boston"],
                            "deadline": None if i % 4 == 0 else f"2027-01-{1 + i % 20:02d}",
                        }
                    )
                }
            )
            db.execute(
                "INSERT INTO "
                "jobs(id,data,canonical_url,company_key,content_hash,status,first_seen,last_seen) "
                "VALUES(?,?,?,?,?,'open',?,?)",
                (
                    item.id,
                    item.model_dump_json(),
                    item.posting.apply_url,
                    "synthetic",
                    item.content_hash,
                    i % 20,
                    i % 20,
                ),
            )
            if i % 4:
                fingerprint = identity(item, 0, 0, None)
                assessment = Assessment(
                    identity=fingerprint,
                    job_id=item.id,
                    job_revision=item.content_hash,
                    opening_revision=0,
                    profile_revision=0,
                    connection_revision=0,
                    selected_model="synthetic",
                    effective_model="synthetic",
                    rubric_revision=rubric_revision(),
                    recommendation="recommended" if i % 2 else "review",
                    eligible=None,
                    normalized_fit=i % 20,
                    criteria={},
                    dimensions={},
                    evidence={},
                    candidate_evidence={},
                    uncertainty=["Synthetic gap"],
                    exact_checks={},
                    input_tokens=0,
                    output_tokens=0,
                    assessed_at=0,
                )
                db.execute(
                    "INSERT INTO assessments VALUES(?,?,?,0)",
                    (fingerprint, item.id, assessment.model_dump_json()),
                )


@pytest.mark.parametrize("sort", list(job_workspace.SORTS))
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_sql_sort_unknown_last_and_stable_across_pages(api, sort, direction):
    seed(api)
    rows = []
    for page in range(1, 7):
        result = api.jobs(page=page, sort=sort, direction=direction)
        if page <= result["pagination"]["pages"]:
            rows.extend(result["jobs"])
    assert len(rows) == 130 and len({r["id"] for r in rows}) == 130
    keys = {
        "postedAt": "source_timestamp",
        "firstObservedAt": "first_seen",
        "company": "company",
        "title": "title",
        "location": "locations",
        "deadline": "deadline",
        "score": "fit",
    }
    values = [r[keys[sort]] for r in rows]
    values = [(", ".join(v) or None) if isinstance(v, list) else v for v in values]
    known = [v for v in values if v is not None]
    assert values == known + [None] * (130 - len(known))
    assert known == sorted(known, reverse=direction == "desc")
    for left, right, x, y in zip(rows, rows[1:], values, values[1:], strict=False):
        if x == y:
            assert left["id"] < right["id"]
    assert api.jobs(page=999)["pagination"]["page"] == 6


def test_owner_views_history_persistence_and_no_model_overwrite(api):
    seed(api)
    selected = "synthetic-00001"
    before = api.detail(selected)["evaluation"]["result"]
    assert api.update_workspace(selected, {"notes": "Owner note <script>", "saved": True})["saved"]
    assert api.jobs(view="Saved")["jobs"][0]["id"] == selected
    api.update_workspace(selected, {"decision": "rejected", "reason": "Owner reviewed requirement"})
    rejected = api.jobs(view="Rejected")["jobs"][0]
    assert rejected["id"] == selected and rejected["evaluation"]["result"] == before
    assert rejected["workspace"]["history"][0]["assessment_identity"] == before["identity"]
    api.update_workspace(selected, {"decision": None, "reason": "Restore original decision"})
    assert api.jobs(view="Rejected")["pagination"]["total"] == 0
    api.update_workspace(selected, {"dismissed": True})
    assert api.jobs(view="Rejected")["jobs"][0]["id"] == selected
    assert all(r["id"] != selected for r in api.jobs(view="Recommendations")["jobs"])
    api.mark_applied(selected)
    assert api.jobs(view="Applied")["jobs"][0]["id"] == selected
    assert api.detail(selected)["workspace"]["notes"] == "Owner note <script>"
    assert len(api.detail(selected)["workspace"]["history"]) == 2
    assert api.detail("missing") is None


@pytest.mark.parametrize(
    "body",
    [
        {"saved": 1},
        {"notes": "x" * 10001},
        {"decision": "rejected"},
        {"decision": "other", "reason": "x"},
        {"job_id": "bad"},
        {},
    ],
)
def test_workspace_validates_owner_actions(api, body):
    with pytest.raises(ValueError):
        api.update_workspace("relevant", body)


def test_filters_selection_read_only_and_stale_assessment(api):
    seed(api)
    before = api.settings.database_path.read_bytes()
    result = api.jobs(search="Analytics", page=2, selected="synthetic-00001")
    assert result["pagination"]["total"] == 44
    assert result["selected"]["id"] == "synthetic-00001"
    assert all(r["title"] == "Analytics" for r in result["jobs"])
    assert api.settings.database_path.read_bytes() == before
    with sqlite3.connect(api.settings.database_path) as db:
        row = db.execute("SELECT data FROM jobs WHERE id='synthetic-00001'").fetchone()
        data = json.loads(row[0])
        data["opening_revision"] = 1
        db.execute("UPDATE jobs SET data=? WHERE id='synthetic-00001'", (json.dumps(data),))
    stale = api.detail("synthetic-00001")
    assert stale["fit"] is None and stale["evaluation"]["state"] == "stale"
    assert all(r["id"] != "synthetic-00001" for r in api.jobs(view="Recommendations")["jobs"])
