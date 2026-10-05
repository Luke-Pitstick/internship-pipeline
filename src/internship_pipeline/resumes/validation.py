"""Structural factual checks and PDF checks; semantic grounding still needs review."""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from typing import Any

from pypdf import PdfReader

from internship_pipeline.models import CandidateProfile


class ResumeValidationError(ValueError):
    """The artifact is unsafe to deliver as a usable tailored resume."""


@dataclass
class ValidationReport:
    warnings: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)


def normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def resume_text(data: dict[str, Any]) -> str:
    def strings(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [text for item in value for text in strings(item)]
        if isinstance(value, dict):
            return [
                text
                for key, item in value.items()
                if key not in {"sectionMeta", "descriptionStyles", "id"}
                for text in strings(item)
            ]
        return []

    return "\n".join(strings(data))


def validate_schema(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("personalInfo"), dict):
        raise ResumeValidationError("Missing structured personal information")
    personal = data["personalInfo"]
    if any(
        not isinstance(personal.get(key), str) or not personal[key].strip()
        for key in ("name", "email")
    ):
        raise ResumeValidationError("Missing structured contact fields")
    protected = {
        "workExperience": ("title", "company", "years"),
        "education": ("institution", "degree", "years"),
        "personalProjects": ("name", "role", "years"),
    }
    for section, fields in protected.items():
        rows = data.get(section, [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ResumeValidationError(f"Invalid structured {section}")
        for row in rows:
            if any(not isinstance(row.get(key, ""), str) for key in fields):
                raise ResumeValidationError(f"Invalid protected fields in {section}")
            description = row.get("description", [] if section != "education" else None)
            if section == "education":
                valid = description is None or isinstance(description, str)
            else:
                valid = isinstance(description, list) and all(
                    isinstance(item, str) for item in description
                )
            if not valid:
                raise ResumeValidationError(f"Invalid description in {section}")
    additional = data.get("additional", {})
    if not isinstance(additional, dict):
        raise ResumeValidationError("Invalid additional section")
    for key in ("technicalSkills", "certificationsTraining", "languages", "awards"):
        values = additional.get(key, [])
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise ResumeValidationError(f"Invalid {key} list")
    if not isinstance(data.get("summary", ""), str):
        raise ResumeValidationError("Invalid summary")
    if not isinstance(data.get("customSections", {}), dict):
        raise ResumeValidationError("Invalid custom sections")
    return data


def validate_master(data: dict[str, Any], profile: CandidateProfile) -> None:
    validate_schema(data)
    personal = data["personalInfo"]
    for field_name in ("name", "email"):
        if normalized(personal[field_name]) != normalized(getattr(profile, field_name)):
            raise ResumeValidationError(f"Master {field_name} disagrees with factual profile")
    text = normalized(resume_text(data))
    for value in profile.protected_values:
        if normalized(value) not in text:
            raise ResumeValidationError("Master is missing a protected factual value")
    allowed_skills = {normalized(skill) for fact in profile.facts for skill in fact.skills}
    skills = data.get("additional", {}).get("technicalSkills", [])
    if any(normalized(skill) not in allowed_skills for skill in skills):
        raise ResumeValidationError("Master skills are not supported by profile fact skills")


def validate_facts(
    master: dict[str, Any], tailored: dict[str, Any], profile: CandidateProfile
) -> ValidationReport:
    validate_schema(tailored)
    report = ValidationReport()
    original_personal = master["personalInfo"]
    current_personal = tailored["personalInfo"]
    for key in ("name", "email", "phone", "location", "website", "linkedin", "github"):
        if normalized(str(current_personal.get(key) or "")) != normalized(
            str(original_personal.get(key) or "")
        ):
            raise ResumeValidationError(f"Tailoring changed protected contact field {key}")
    identities = {
        "workExperience": ("title", "company", "years", "location"),
        "education": ("institution", "degree", "years"),
        "personalProjects": ("name", "role", "years", "github", "website"),
    }
    for section, keys in identities.items():

        def identity(row: dict[str, Any], fields: tuple[str, ...] = keys) -> tuple[str, ...]:
            return tuple(normalized(str(row.get(key) or "")) for key in fields)

        original_rows = [identity(row) for row in master.get(section, [])]
        for row in tailored.get(section, []):
            row_identity = identity(row)
            if row_identity not in original_rows:
                raise ResumeValidationError(f"Tailoring changed or invented {section} identity")
            original_rows.remove(row_identity)
        if original_rows:
            report.changes.append(f"Selected a subset of {section} entries")
    text = normalized(resume_text(tailored))
    for value in profile.protected_values:
        if normalized(value) not in text:
            raise ResumeValidationError("Tailoring removed a protected factual value")
    supported_skills = {normalized(skill) for fact in profile.facts for skill in fact.skills}
    current_additional = tailored.get("additional", {})
    for skill in current_additional.get("technicalSkills", []):
        if normalized(skill) not in supported_skills:
            report.warnings.append(f"Unsupported skill requires review: {skill}")
    for key in ("certificationsTraining", "languages", "awards"):
        baseline = {normalized(item) for item in master.get("additional", {}).get(key, [])}
        if any(normalized(item) not in baseline for item in current_additional.get(key, [])):
            report.warnings.append(f"New {key} claim requires review")
    factual_text = resume_text(master) + "\n" + "\n".join(fact.text for fact in profile.facts)
    number_pattern = r"(?<!\w)\d[\d.,]*(?:%|\+)?(?!\w)"
    new_numbers = set(re.findall(number_pattern, resume_text(tailored))) - set(
        re.findall(number_pattern, factual_text)
    )
    if new_numbers:
        report.warnings.append(
            "New numerical claims require review: " + ", ".join(sorted(new_numbers))
        )
    if json.dumps(master, sort_keys=True) != json.dumps(tailored, sort_keys=True):
        report.changes.append("Resume content or ordering changed; compare against the master")
    report.warnings.append(
        "Semantic grounding is unverified; review rewritten claims against factual experience"
    )
    return report


def validate_pdf(
    content: bytes, profile: CandidateProfile, tailored: dict[str, Any]
) -> ValidationReport:
    if not content.startswith(b"%PDF-"):
        raise ResumeValidationError("Download is not a PDF")
    report = ValidationReport()
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise ResumeValidationError("Encrypted resume PDF")
        if not 1 <= len(reader.pages) <= profile.max_resume_pages:
            raise ResumeValidationError("Resume PDF exceeds the allowed page count")
        texts: list[str] = []
        for page in reader.pages:
            bounds = page.mediabox

            def visit(
                text: str,
                cm: list[float],
                tm: list[float],
                font: Any,
                size: float,
                rectangle: Any = bounds,
            ) -> None:
                x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                if text.strip() and not (
                    float(rectangle.left) - 2 <= x <= float(rectangle.right) + 2
                    and float(rectangle.bottom) - 2 <= y <= float(rectangle.top) + 2
                ):
                    report.warnings.append("Text origin outside the page requires visual review")

            text = page.extract_text(visitor_text=visit) or ""
            if len(text.strip()) < 20:
                raise ResumeValidationError("Blank or unreadable resume PDF page")
            texts.append(text)
    except ResumeValidationError:
        raise
    except Exception as exc:
        raise ResumeValidationError("Malformed or unreadable resume PDF") from exc
    text = normalized("\n".join(texts))
    if len(text) < 80:
        raise ResumeValidationError("Insufficient readable resume PDF text")
    for value in (profile.name, profile.email, *profile.protected_values):
        if value and normalized(value) not in text:
            raise ResumeValidationError("PDF is missing contact or protected factual text")
    sections = {
        "workExperience": ("experience",),
        "education": ("education",),
        "personalProjects": ("projects", "project"),
        "summary": ("summary", "profile"),
    }
    for section, headings in sections.items():
        if tailored.get(section) and not any(
            re.search(r"\b" + heading + r"\b", text) for heading in headings
        ):
            raise ResumeValidationError(f"PDF is missing the {section} section")
    if tailored.get("additional", {}).get("technicalSkills") and "skills" not in text:
        raise ResumeValidationError("PDF is missing the skills section")
    for section in ("workExperience", "personalProjects"):
        for row in tailored.get(section, []):
            for bullet in row.get("description", []):
                if bullet.strip() and normalized(bullet) not in text:
                    raise ResumeValidationError("PDF omitted structured resume content")
    report.warnings = list(dict.fromkeys(report.warnings))
    return report
