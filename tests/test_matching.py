"""Historic semantic scenarios now exercise Jev inputs, never a regex acceptance gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from internship_pipeline.assessments import request_body
from internship_pipeline.models import Job
from internship_pipeline.profile_settings import (
    Education,
    Fact,
    HardConstraints,
    Preferences,
    Profile,
    Snapshot,
)

CASES = json.loads(
    Path(__file__).with_name("fixtures").joinpath("jev_semantic_regressions.json").read_text()
)


@pytest.mark.parametrize(
    "case", CASES, ids=[f"{i}-{x['job']['posting']['title']}" for i, x in enumerate(CASES)]
)
def test_historic_semantic_input_remains_available_for_typed_criteria(case):
    job = Job.model_validate(case["job"])
    original = case["candidate"]
    constraints = original["constraints"]
    facts = [
        Fact(id=f["id"], text=f["text"], skills=f["skills"], status="confirmed")
        for f in original["facts"]
    ]
    education = []
    if constraints["degree_level"]:
        education.append(
            Education(
                id="degree",
                institution="Synthetic institution",
                degree=constraints["degree_level"],
                status="confirmed",
            )
        )
    snapshot = Snapshot(
        revision=1,
        profile=Profile(
            facts=facts,
            education=education,
            requires_sponsorship=constraints["requires_sponsorship"],
            work_authorization=constraints["work_authorization"],
        ),
        preferences=Preferences(
            hard=HardConstraints(
                **{k: constraints[k] for k in ("countries", "locations", "term_keywords")}
            )
        ),
    )
    body, evidence = request_body(job, snapshot, "jev-1.13.0")
    assert evidence["title"] == job.posting.title
    assert (
        "".join(v for k, v in evidence.items() if k.startswith("p") and k[1:].isdigit())
        == job.posting.description
    )
    assert body["state"]["candidate"]["confirmed_evidence"] == {
        f["id"]: f["text"] for f in original["facts"]
    } | {e.id: " — ".join([e.institution, e.degree]) for e in education}
    assert set(body["questions"]) == {
        "role",
        "authorization",
        "education",
        "location",
        "required_skills",
        "role_evidence",
        "authorization_evidence",
        "education_evidence",
        "location_evidence",
        "required_skills_evidence",
        "skills",
        "projects",
        "responsibilities",
        "preferences",
    }
    assert "violated" in body["questions"]["required_skills"]["criteria"]
