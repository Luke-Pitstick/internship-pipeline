"""Conservative eligibility checks and evidence-grounded role assessments."""

from __future__ import annotations

import json
import re
from importlib.resources import files
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from internship_pipeline.models import CandidateProfile, Job, MatchResult, RoleFamily, Settings

_INTERNSHIP = re.compile(r"\b(intern(?:ship)?s?|co[ -]?op(?:erative)?)\b", re.I)
_ROLES = (
    (RoleFamily.ML_AI, r"\b(machine learning|artificial intelligence|deep learning|ml|ai)\b"),
    (RoleFamily.DS, r"\b(data scien(?:ce|tist)|data (?:analytics|analyst|analysis))\b"),
    (RoleFamily.PM, r"\b(product manag(?:er|ement)|associate product manager|apm)\b"),
    (
        RoleFamily.SWE,
        r"\b(software (?:engineer(?:ing)?|develop(?:er|ment)|intern(?:ship)?)|swe|sde|"
        r"(?:front[ -]?end|back[ -]?end|full[ -]?stack) (?:engineer|developer)|"
        r"(?:front[ -]?end|back[ -]?end|full[ -]?stack) intern(?:ship)?|data engineer(?:ing)?|"
        r"(?:web|mobile|application) develop(?:er|ment))\b",
    ),
)
_COUNTRIES = {
    "us": "united states",
    "usa": "united states",
    "u.s.": "united states",
    "united states of america": "united states",
    "uk": "united kingdom",
    "u.k.": "united kingdom",
    "england": "united kingdom",
}
_DEGREES = {
    "associate": 1,
    "bachelor": 2,
    "bachelors": 2,
    "undergraduate": 2,
    "master": 3,
    "masters": 3,
    "graduate": 3,
    "phd": 4,
    "doctorate": 4,
    "doctoral": 4,
}
_DEGREE = re.compile(
    r"\b(bachelor(?:['’]?s)?|master(?:['’]?s)?|ph\.?d\.?|doctorate|doctoral)\b", re.I
)


class MatchAssessmentError(RuntimeError):
    """A configured assessment failed; retain the preliminary match and retry."""

    retryable = True

    def __init__(self, message: str, deterministic_result: MatchResult) -> None:
        super().__init__(message)
        self.deterministic_result = deterministic_result


class _Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    role_family: Literal["swe", "pm", "ml_ai", "ds"]
    fit: Literal["strong", "possible", "weak"]
    fact_ids: list[str]
    requirement_excerpts: list[str]
    missing_qualifications: list[str]
    unknowns: list[str]


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def _country(text: str) -> str:
    normalized = _normalized(text).strip(" ,.")
    return _COUNTRIES.get(normalized, normalized)


def _role(job: Job) -> RoleFamily | None:
    title = job.posting.title
    # Project/program management is not product management, even when working with PMs.
    if re.search(r"\b(?:project|program) manag(?:er|ement)\b", title, re.I):
        return None
    for family, pattern in _ROLES:
        if re.search(pattern, title, re.I):
            return family
    if re.search(r"\b(marketing|finance|accounting|sales|nursing|human resources)\b", title, re.I):
        return None
    for family, pattern in _ROLES:
        if re.search(pattern, job.posting.description, re.I):
            return family
    return None


def _degree_rank(text: str) -> int | None:
    normalized = re.sub(r"[.'’]", "", _normalized(text))
    return _DEGREES.get(normalized)


def _requirements(description: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"[\n;]|(?<=[.!?])\s+(?!required\b|preferred\b)", description)
        if part.strip()
    ]


def _hard_constraints(job: Job, profile: CandidateProfile) -> tuple[list[str], list[str]]:
    constraints = profile.constraints
    conflicts: list[str] = []
    unknowns: list[str] = []
    description = job.posting.description
    requirements = _requirements(description)

    remote = bool(
        re.search(
            r"\bremote\b", " ".join([description, job.posting.title, *job.posting.locations]), re.I
        )
    )
    # Reject only when every listed location identifies a conflicting country.
    if constraints.countries:
        allowed = {_country(item) for item in constraints.countries}
        known_countries = (
            set(_COUNTRIES.values())
            | {
                "canada",
                "germany",
                "france",
                "india",
                "australia",
                "ireland",
                "singapore",
            }
            | allowed
        )
        location_countries = [
            {_country(part) for part in location.split(",") if _country(part) in known_countries}
            for location in job.posting.locations
        ]
        observed = set().union(*location_countries)
        all_known = bool(location_countries) and all(location_countries)
        if all_known and not observed & allowed and not remote:
            conflicts.append(
                "All explicitly listed countries conflict with the configured countries."
            )
        elif not all_known or remote:
            unknowns.append("Country eligibility or remote work jurisdiction needs confirmation.")
    if constraints.locations:
        posted = {_normalized(item) for item in job.posting.locations}
        if not posted & {_normalized(item) for item in constraints.locations}:
            unknowns.append("Location compatibility needs confirmation.")
    if not job.posting.locations:
        unknowns.append("Work location is not supplied.")

    term_data = job.posting.title + "\n" + description
    terms = set(re.findall(r"\b(summer|spring|fall|autumn|winter)\b", term_data, re.I))
    terms = {"fall" if item.casefold() == "autumn" else item.casefold() for item in terms}
    if constraints.term_keywords:
        wanted = set()
        for term in constraints.term_keywords:
            wanted.update(re.findall(r"\b(summer|spring|fall|autumn|winter)\b", term.casefold()))
        wanted = {"fall" if item == "autumn" else item for item in wanted}
        # Seasonal mentions elsewhere in a JD aren't proof of an exclusive internship term.
        explicit_terms = (
            set(re.findall(r"\b(summer|spring|fall|autumn|winter)\b", job.posting.title, re.I))
            if _INTERNSHIP.search(job.posting.title)
            else set()
        )
        explicit_terms.update(
            re.findall(
                r"\b(summer|spring|fall|autumn|winter)\s+(?:20\d{2}\s+)?intern(?:ship)?\b",
                description,
                re.I,
            )
        )
        explicit_terms.update(
            re.findall(
                r"\binternship\s+(?:term|period)\s*:\s*(summer|spring|fall|autumn|winter)\b",
                description,
                re.I,
            )
        )
        explicit_terms = {
            "fall" if term.casefold() == "autumn" else term.casefold() for term in explicit_terms
        }
        if wanted and explicit_terms and not wanted & explicit_terms:
            conflicts.append(
                "The explicitly stated internship term conflicts with the configured term."
            )
        elif not wanted or not explicit_terms:
            unknowns.append("Internship term compatibility needs confirmation.")
        wanted_years = {
            int(year)
            for term in constraints.term_keywords
            for year in re.findall(r"\b20\d{2}\b", term)
        }
        term_sources = [job.posting.title] if _INTERNSHIP.search(job.posting.title) else []
        term_sources.extend(
            re.findall(
                r"\b(?:summer|spring|fall|autumn|winter)\s+(?:20\d{2}\s+)?intern(?:ship)?(?:\s+20\d{2})?\b",
                description,
                re.I,
            )
        )
        term_sources.extend(
            re.findall(
                r"\binternship\s+(?:term|period)\s*:\s*([^\n.;]+)",
                description,
                re.I,
            )
        )
        posted_years = {
            int(year) for term in term_sources for year in re.findall(r"\b20\d{2}\b", term)
        }
        if wanted_years and posted_years:
            if not wanted_years & posted_years:
                conflicts.append(
                    "The explicitly stated internship year conflicts with the configured term."
                )
        elif wanted_years:
            unknowns.append("Internship year compatibility needs confirmation.")
    elif not terms:
        unknowns.append("Internship term is not supplied.")

    degree_rank = _degree_rank(constraints.degree_level) if constraints.degree_level else None
    degree_requirements = [line for line in requirements if _DEGREE.search(line)]
    for line in degree_requirements:
        ranks = [rank for match in _DEGREE.finditer(line) if (rank := _degree_rank(match[0]))]
        # Associate mandatory language with the degree, not an unrelated skill clause.
        mandatory = bool(
            re.search(
                rf"{_DEGREE.pattern}(?:\.)?(?:\s+(?:degree|candidates|students|program))?"
                r"\s+(?:is\s+)?(?:required|only)\b|"
                r"\b(?:must|requires?|minimum)\s+"
                r"(?:(?:be|currently|pursuing|enrolled|in|have|hold|possess|a|an)\s+){0,8}"
                rf"{_DEGREE.pattern}",
                line,
                re.I,
            )
        )
        preferred = bool(re.search(r"\b(preferred|desirable|nice to have)\b", line, re.I))
        optional = bool(
            re.search(r"\b(?:not required|no .{0,20}required|equivalent experience)\b", line, re.I)
        )
        if (
            mandatory
            and not preferred
            and not optional
            and degree_rank is not None
            and min(ranks) > degree_rank
        ):
            conflicts.append(f"Confirmed degree conflicts with the explicit requirement: {line}")
        elif degree_rank is None or (not mandatory and not preferred):
            unknowns.append(f"Degree eligibility is unverified: {line}")
        elif mandatory and optional:
            unknowns.append(f"Confirm degree or alternative-experience requirements: {line}")
    if not degree_requirements:
        unknowns.append("Degree requirements are not supplied.")

    no_sponsorship = re.search(
        r"\b(?:no (?:visa )?sponsorship|(?:cannot|will not|does not|do not|unable to) "
        r"(?:offer|provide|sponsor)(?:\s+\w+){0,3}\s+(?:sponsorship|visas?)|"
        r"(?:without|not eligible for) (?:visa )?sponsorship)\b",
        description,
        re.I,
    )
    if no_sponsorship and constraints.requires_sponsorship is True:
        conflicts.append(
            "The candidate requires sponsorship and the employer explicitly excludes it."
        )
    elif constraints.requires_sponsorship is None or not no_sponsorship:
        unknowns.append("Work authorization and sponsorship eligibility need confirmation.")
    if re.search(r"\b(?:u\.?s\.?|united states) citizenship (?:is )?required\b", description, re.I):
        # Authorization to work is not evidence either for or against citizenship.
        unknowns.append("Required US citizenship needs confirmation.")

    graduation = constraints.graduation_date
    for line in requirements:
        years = [int(year) for year in re.findall(r"\b20\d{2}\b", line)]
        if (
            re.search(r"\bgraduat", line, re.I)
            and len(years) == 2
            and re.search(r"\b(?:must|required|between)\b", line, re.I)
            and not re.search(r"\b(?:preferred|desirable|not required)\b", line, re.I)
        ):
            if graduation and re.match(r"20\d{2}", graduation):
                year = int(graduation[:4])
                if year < min(years) or year > max(years):
                    conflicts.append(f"Confirmed graduation date conflicts with: {line}")
                elif year in {min(years), max(years)}:
                    unknowns.append(f"Confirm the exact graduation-date bounds: {line}")
            else:
                unknowns.append(f"Graduation eligibility is unverified: {line}")
        elif re.search(r"\bgraduat", line, re.I):
            unknowns.append(f"Confirm graduation requirements: {line}")
    return conflicts, list(dict.fromkeys(unknowns))


def _deterministic_match(job: Job, profile: CandidateProfile) -> MatchResult:
    family = _role(job)
    title_internship = bool(_INTERNSHIP.search(job.posting.title)) or bool(
        _INTERNSHIP.fullmatch(job.posting.employment_type or "")
    )
    internship = title_internship or bool(
        re.search(
            r"\b(?:internship|co[ -]?op|as an intern|intern (?:will|responsibilities))\b",
            job.posting.description,
            re.I,
        )
    )
    conflicts, unknowns = _hard_constraints(job, profile)
    if conflicts:
        return MatchResult(
            fit="weak", eligible=False, role_family=family, reasons=conflicts, unknowns=unknowns
        )
    if family is None:
        return MatchResult(
            fit="weak",
            role_family=None,
            reasons=[
                "No supported SWE, product management, ML/AI or data science role is evidenced."
            ],
            unknowns=unknowns,
        )
    explicit_noninternship = re.search(
        r"\b(?:permanent|senior|staff|principal)\b",
        job.posting.title,
        re.I,
    ) or re.search(r"\bpermanent\b", job.posting.employment_type or "", re.I)
    full_time = re.search(
        r"\bfull[ -]time\b",
        job.posting.title + " " + (job.posting.employment_type or ""),
        re.I,
    )
    if not title_internship and (explicit_noninternship or (full_time and not internship)):
        return MatchResult(
            fit="weak",
            role_family=family,
            reasons=["The posting explicitly describes a non-internship role."],
            unknowns=unknowns,
        )
    if not title_internship and re.search(
        r"\b(?:permanent (?:position|role|employment)|this (?:position|role) is permanent)\b",
        job.posting.description,
        re.I,
    ):
        return MatchResult(
            fit="weak",
            role_family=family,
            reasons=["The posting explicitly describes permanent employment."],
            unknowns=unknowns,
        )
    if not internship:
        unknowns.append("Internship or co-op status needs confirmation.")
    description = _normalized(job.posting.description)
    fact_ids = []
    excerpts: list[str] = []
    reasons = [
        f"The posting describes a {family.value} {'internship/co-op' if internship else 'role'}."
    ]
    for fact in profile.facts:
        overlaps = [
            skill
            for skill in fact.skills
            if re.search(rf"(?<!\w){re.escape(_normalized(skill))}(?!\w)", description)
        ]
        if overlaps:
            fact_ids.append(fact.id)
            reasons.append(
                f"Candidate fact {fact.id} supports requested skills: {', '.join(overlaps)}."
            )
            excerpts.extend(
                line
                for line in _requirements(job.posting.description)
                if any(_normalized(skill) in _normalized(line) for skill in overlaps)
            )
    if not fact_ids:
        unknowns.append("Candidate experience against the posting requirements needs confirmation.")
    return MatchResult(
        fit="possible",
        eligible=None if unknowns else True,
        role_family=family,
        reasons=reasons[:4],
        unknowns=unknowns,
        fact_ids=fact_ids,
        requirement_excerpts=list(dict.fromkeys(excerpts)),
    )


def _llm_assessment(
    job: Job, profile: CandidateProfile, settings: Settings, preliminary: MatchResult
) -> MatchResult:
    prompt = files("internship_pipeline").joinpath("prompts/match.txt").read_text()
    payload = {
        "job": job.posting.model_dump(mode="json"),
        "candidate_facts": [fact.model_dump(mode="json") for fact in profile.facts],
        "confirmed_constraints": profile.constraints.model_dump(mode="json"),
        "preliminary_assessment": preliminary.model_dump(mode="json"),
    }
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
    if settings.llm_base_url is None:
        raise MatchAssessmentError("A model base URL is required.", preliminary)
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json={
                    "model": settings.llm_model,
                    "temperature": 0,
                    "max_tokens": 900,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": json.dumps(payload)},
                    ],
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            assessment = _Assessment.model_validate_json(content)
        valid_fact_ids = {fact.id for fact in profile.facts}
        if set(assessment.fact_ids) - valid_fact_ids:
            raise ValueError("Unknown candidate fact ID")
        evidence = (
            assessment.requirement_excerpts
            + assessment.missing_qualifications
            + assessment.unknowns
        )
        description = _normalized(job.posting.description)
        if not assessment.requirement_excerpts or any(
            not _normalized(excerpt) or _normalized(excerpt) not in description
            for excerpt in evidence
        ):
            raise ValueError("Missing or unsupported posting excerpt")
        if assessment.fit == "strong" and not assessment.fact_ids:
            raise ValueError("Strong fit lacks supported candidate facts")
        family = RoleFamily(assessment.role_family)
        if family != preliminary.role_family:
            raise ValueError("Assessment contradicts the evidenced role family")
    except (httpx.HTTPError, ValidationError, ValueError, TypeError, KeyError, IndexError) as exc:
        # Avoid leaking response bodies, URLs or credentials into durable queue errors.
        raise MatchAssessmentError(
            "Configured model assessment failed or returned unsupported evidence; retry required.",
            preliminary,
        ) from exc
    reasons = [preliminary.reasons[0]]
    selected_ids = set(assessment.fact_ids)
    reasons.extend(
        f"Candidate evidence ({fact.id}): {fact.text}"
        for fact in profile.facts
        if fact.id in selected_ids
    )
    reasons.extend(
        f"Posting evidence: {excerpt}" for excerpt in assessment.requirement_excerpts[:2]
    )
    return MatchResult(
        fit=assessment.fit,
        eligible=preliminary.eligible,
        role_family=family,
        reasons=reasons,
        fact_ids=list(dict.fromkeys(assessment.fact_ids)),
        requirement_excerpts=list(dict.fromkeys(assessment.requirement_excerpts)),
        missing_qualifications=assessment.missing_qualifications,
        unknowns=list(
            dict.fromkeys(
                preliminary.unknowns
                + [f"Unverified requirement: {excerpt}" for excerpt in assessment.unknowns]
            )
        ),
    )


def match_job(job: Job, profile: CandidateProfile, settings: Settings) -> MatchResult:
    """Match without network access unless a model and compatible base URL are configured."""
    preliminary = _deterministic_match(job, profile)
    if not preliminary.accepted:
        return preliminary
    if bool(settings.llm_model) != bool(settings.llm_base_url):
        raise MatchAssessmentError("Both llm_model and llm_base_url are required.", preliminary)
    if settings.llm_model and settings.llm_base_url:
        return _llm_assessment(job, profile, settings, preliminary)
    return preliminary
