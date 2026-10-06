"""Production adaptation of the T02 rubric; automatic rejection remains disabled."""

from typing import Any

RUBRIC: dict[str, Any] = {
    "version": "jev-eligibility-fit-v2-owner-preferences",
    "criteria": {
        "role": (
            "Is this opening explicitly an internship or co-op? Assess mandatory term "
            "constraints from candidate.preferences.hard. Preferred roles are optional."
        ),
        "authorization": (
            "Does candidate.profile satisfy mandatory citizenship, work authorization "
            "and sponsorship restrictions? If restrictions are omitted choose not_stated; "
            "never infer sponsorship from silence. Unknown candidate inputs are ambiguous."
        ),
        "education": (
            "Does confirmed candidate.profile.education satisfy mandatory degree, subject "
            "and enrollment requirements? Preferred degrees are optional. Equivalent "
            "experience is an alternative; review when its adequacy is unclear. Semantic "
            "graduation or experience date constraints need review, not model arithmetic."
        ),
        "location": (
            "Does the posting satisfy mandatory country and location constraints in "
            "candidate.preferences.hard? Empty constraints impose no restriction. "
            "Remote alone does not establish jurisdiction."
        ),
        "required_skills": (
            "Does confirmed candidate evidence satisfy explicitly REQUIRED skills? "
            "Missing preferred skills never violate. Missing proof is ambiguous, not "
            "confirmed absence. Numerical years requirements need review, not model arithmetic."
        ),
    },
    "outcomes": {
        "satisfied": "Explicit evidence confirms compatibility or explicitly no restriction.",
        "violated": "A mandatory restriction conflicts with an explicitly confirmed fact.",
        "not_stated": "The relevant requirement is omitted; compatibility is unconfirmed.",
        "ambiguous": "Requirements conflict or candidate evidence is insufficient.",
    },
    "dimensions": {
        "skills": "Rate coverage of required and preferred skills by confirmed candidate facts.",
        "projects": "Rate demonstrated project relevance to the advertised responsibilities.",
        "responsibilities": "Rate alignment of duties with confirmed candidate experience.",
        "preferences": (
            "Rate alignment with candidate.preferences.soft roles, locations and skills. "
            "Interests cannot establish acquired skills."
        ),
    },
    "levels": [
        "No demonstrated alignment or missing relevant information",
        "Limited alignment: only indirect evidence",
        "Substantial alignment: several direct overlaps but meaningful gaps",
        "Strong alignment: direct evidence supports almost all important aspects",
    ],
    "weights": {"skills": 0.35, "projects": 0.30, "responsibilities": 0.25, "preferences": 0.10},
    "policy": {
        "violation_probability": 0.95,
        "confidence": 0.80,
        "evidence_probability": 0.95,
        "automatic_rejection_enabled": False,
    },
}
