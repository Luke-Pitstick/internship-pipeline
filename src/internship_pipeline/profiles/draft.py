"""Literal resume field selection, shared by PDF, Word and LaTeX imports."""

from __future__ import annotations

import re
from typing import Any

from internship_pipeline.profiles.entries import entry_start

HEADINGS = {
    "skills": "skill",
    "technical skills": "skill",
    "core skills": "skill",
    "core competencies": "skill",
    "technologies": "skill",
    "skills and technologies": "skill",
    "technical proficiencies": "skill",
    "programming skills": "skill",
    "programming languages": "skill",
    "skills and interests": "uncertain",
    "projects": "project",
    "selected projects": "project",
    "personal projects": "project",
    "technical projects": "project",
    "academic projects": "project",
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "employment": "experience",
    "employment history": "experience",
    "work history": "experience",
    "relevant experience": "experience",
    "research experience": "experience",
    "leadership experience": "experience",
    "volunteer experience": "experience",
    "education": "education",
    "academic background": "education",
    "education and qualifications": "education",
    "education and certifications": "education",
    "certifications": "uncertain",
    "interests": "uncertain",
    "summary": "uncertain",
    "professional summary": "uncertain",
    "objective": "uncertain",
    "awards": "uncertain",
    "honors and awards": "uncertain",
    "publications": "uncertain",
    "references": "uncertain",
    "activities": "uncertain",
    "languages": "skill",
    "additional information": "uncertain",
    "extracurricular activities": "uncertain",
}
BULLET = re.compile(r"^[•●▪◦‣*\-–]\s+")
SCHOOL = re.compile(r"\b(?:University|College|Institute|School|Polytechnic|Academy)\b", re.I)
DEGREE = re.compile(
    r"\b(?:Bachelor(?:['’]s)?|Master(?:['’]s)?|Associate(?:['’]s)?|Doctor(?:ate)?|"
    r"B\.?\s?Sc\.?|B\.?\s?S\.?|B\.?\s?A\.?|M\.?\s?Sc\.?|M\.?\s?S\.?|"
    r"M\.?\s?A\.?|M\.?B\.?A\.?|Ph\.?\s?D\.?)(?=\W|$)",
    re.I,
)


def heading(text: str) -> str | None:
    normalized = BULLET.sub("", text).strip(" :|—–-").lower().replace("&", "and")
    return HEADINGS.get(" ".join(normalized.split()))


def suggestions(lines: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Select only source excerpts, keeping wrapped claims and education rows together."""
    result: list[dict[str, Any]] = []
    consumed: set[str] = set()
    contacts: set[str] = set()
    section = "uncertain"
    for index, line in enumerate(lines):
        if line["id"] in consumed:
            continue
        value = line["text"]
        found = heading(value)
        if found is not None:
            section = found
            continue
        # Inline labels are common in Word tables and compact PDF skill sections.
        label, separator, rest = value.partition(":")
        if separator and heading(label) == "skill" and rest.strip():
            section = "skill"
        proposed = section if section in {"experience", "project", "skill"} else "experience"
        selected = section in {"experience", "project", "skill"}
        skills: list[str] = []
        source_ids: list[str] = []
        institution = degree = excerpt = ""
        email = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value)
        if index == 0:
            name = re.split(r"\s*[|•]\s*|\s{2,}", value)[0].strip()
            if (
                len(name) <= 100
                and 2 <= len(name.split()) <= 4
                and all(
                    word.rstrip(".").replace("-", "").replace("'", "").isalpha()
                    for word in name.split()
                )
            ):
                if email:
                    result.append(
                        {
                            "line_id": line["id"],
                            "kind": "name",
                            "selected": True,
                            "skills": [],
                            "institution": "",
                            "degree": "",
                            "source_line_ids": [],
                            "value": name,
                        }
                    )
                else:
                    proposed, selected, excerpt = "name", True, name
        if email and "email" not in contacts:
            proposed, selected, excerpt = "email", True, email.group()
            contacts.add("email")

        if section == "education":
            # Match either school-first or degree-first layouts within this entry.
            rows = [line]
            for following in lines[index + 1 : index + 4]:
                if heading(following["text"]) is not None:
                    break
                if SCHOOL.search(following["text"]) and SCHOOL.search(value):
                    break
                if DEGREE.search(following["text"]) and DEGREE.search(value):
                    break
                rows.append(following)
            parts = [part.strip() for row in rows for part in row["text"].split("|")]
            school_part = next((part for part in parts if SCHOOL.search(part)), "")
            degree_part = next((part for part in parts if DEGREE.search(part)), "")
            if school_part and degree_part:
                if school_part == degree_part:
                    match = DEGREE.search(school_part)
                    assert match is not None
                    school_part, degree_part = (
                        school_part[: match.start()].strip(" ,;—–-"),
                        school_part[match.start() :],
                    )
                if school_part and len(school_part) <= 200 and len(degree_part) <= 200:
                    institution, degree = school_part, degree_part
                    proposed, selected = "education", True
                    needed = [
                        row for row in rows if institution in row["text"] or degree in row["text"]
                    ]
                    source_ids = [row["id"] for row in needed if row is not line]
                    consumed.update(source_ids)

        if proposed in {"experience", "project", "skill"} and selected:
            # A bullet can wrap across PDF drawing operations or source paragraphs.
            # Stop at the next bullet, heading, entry row, or labeled skill category.
            rows = [line]
            entry = proposed != "skill" and entry_start(lines, index, proposed)
            for next_index, following in enumerate(lines[index + 1 : index + 40], index + 1):
                text = following["text"]
                if entry:
                    if heading(text) is not None or (
                        next_index > index + 1 and entry_start(lines, next_index, proposed)
                    ):
                        break
                    if sum(len(row["text"]) + 1 for row in [*rows, following]) > 2000:
                        break
                    rows.append(following)
                    continue
                if (
                    heading(text) is not None
                    or BULLET.match(text)
                    or "|" in text
                    or ":" in text
                    or re.search(r"\b(?:19|20)\d{2}\b", text)
                ):
                    break
                wrapped_skill = proposed == "skill" and rows[-1]["text"].endswith((",", ";"))
                wrapped_bullet = proposed != "skill" and BULLET.match(value)
                if not wrapped_skill and not wrapped_bullet:
                    break
                if wrapped_bullet and rows[-1]["text"].endswith((".", "!", "?")):
                    break
                if sum(len(row["text"]) + 1 for row in [*rows, following]) > 2000:
                    break
                rows.append(following)
            source_ids = [row["id"] for row in rows[1:]]
            consumed.update(source_ids)
            if BULLET.match(value):
                excerpt = BULLET.sub("", "\n".join(row["text"] for row in rows))
            if proposed == "skill":
                text = "\n".join(row["text"] for row in rows)
                text = BULLET.sub("", text)
                if ":" in text and len(text.partition(":")[0]) <= 50:
                    text = text.partition(":")[2]
                items = [item.strip() for item in re.split(r"[,;|•·]", text) if item.strip()]
                if len(items) <= 30 and all(len(item) <= 200 for item in items):
                    skills = items
        result.append(
            {
                "line_id": line["id"],
                "kind": proposed,
                "selected": selected,
                "skills": skills,
                "institution": institution,
                "degree": degree,
                "source_line_ids": source_ids,
                "value": excerpt,
            }
        )
    return result
