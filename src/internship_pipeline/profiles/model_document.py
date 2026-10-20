"""Typed model extraction with server-owned fields and reviewable source evidence."""

from __future__ import annotations

import json
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter

from internship_pipeline.profiles.entries import education_field, month_date
from internship_pipeline.profiles.extract import MAX_TEXT


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ModelEducation(SourceRecord):
    page: int = Field(ge=1)
    institution: str = Field(max_length=200)
    degree: str = Field(max_length=200)
    field: str = Field(max_length=200)
    graduation: str = Field(max_length=100)


class ModelEntry(SourceRecord):
    page: int = Field(ge=1)
    kind: Literal["experience", "project"]
    title: str = Field(max_length=200)
    company: str = Field(max_length=200)
    location: str = Field(max_length=200)
    start: str = Field(max_length=100)
    end: str = Field(max_length=100)
    bullets: list[str] = Field(max_length=30)
    skills: list[str] = Field(max_length=30)
    links: list[str] = Field(max_length=10)


class ModelDocument(SourceRecord):
    name: str = Field(max_length=200)
    email: str = Field(max_length=254)
    education: list[ModelEducation] = Field(max_length=20)
    entries: list[ModelEntry] = Field(max_length=100)
    skills: list[str] = Field(max_length=100)


def schema() -> dict[str, Any]:
    """Portable strict schema; runtime validation enforces provider-unsupported bounds."""

    def portable(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: portable(child)
                for key, child in value.items()
                if key not in {"title", "maxLength", "minLength", "maxItems", "minimum", "maximum"}
                or isinstance(child, dict)  # Keep the actual property named title.
            }
        if isinstance(value, list):
            return [portable(child) for child in value]
        return value

    return dict(portable(ModelDocument.model_json_schema()))


def source_lines(
    result: Any, pages: int, key: str, original: str | None = None
) -> list[dict[str, str]]:
    """Keep model grouping as data; never guess a second time from pseudo-PDF rows."""
    document = ModelDocument.model_validate(result)
    if original is not None:

        def normalized(text: str) -> str:
            return " ".join(
                unicodedata.normalize("NFKC", text)
                .translate(str.maketrans("’‘“”|", "''\"\" "))
                .split()
            )

        source = normalized(" ".join(row["text"] for row in json.loads(original)))

        def check(value: Any, field: str = "") -> None:
            if isinstance(value, str) and field != "kind" and normalized(value) not in source:
                raise ValueError("Model value is not in the source")
            if isinstance(value, dict):
                for key, child in value.items():
                    check(child, key)
            if isinstance(value, list):
                for child in value:
                    check(child, field)

        grounded = document.model_dump()
        for education in grounded["education"]:
            # Splitting two explicit degrees into their fields is a deterministic
            # transformation, even when the joined field string is not contiguous.
            if normalized(education["field"]) == normalized(education_field(education["degree"])):
                education["field"] = ""
        check(grounded)
    lines: list[dict[str, str]] = []

    def append(text: str, page: int, fields: dict[str, Any]) -> None:
        if not 1 <= page <= pages or not text.strip() or len(text) > 2000:
            raise ValueError("Invalid model source entry")
        if key in text:
            raise ValueError("Invalid model content")
        lines.append(
            {
                "id": str(len(lines)),
                "location": f"Page {page} · AI transcription; review against original",
                "text": text,
                "fields": json.dumps(fields),
            }
        )

    for kind in ("name", "email"):
        value = getattr(document, kind).strip()
        if value:
            append(value, 1, {"kind": kind})
    for education in document.education:
        if not education.institution.strip() or not education.degree.strip():
            raise ValueError("Incomplete education entry")
        append(
            " | ".join(
                filter(
                    None,
                    [
                        education.institution,
                        education.degree,
                        education.field,
                        education.graduation,
                    ],
                )
            ),
            education.page,
            {
                "kind": "education",
                "institution": education.institution,
                "degree": education.degree,
                "field": education.field,
            },
        )
    for entry in document.entries:
        if not entry.title.strip() and not any(bullet.strip() for bullet in entry.bullets):
            raise ValueError("Empty entry")
        for link in entry.links:
            if len(link) > 2048:
                raise ValueError("Invalid link")
            TypeAdapter(HttpUrl).validate_python(link)
        if any(not skill.strip() or len(skill) > 200 for skill in entry.skills):
            raise ValueError("Invalid skills")
        current = entry.end.lower() in {"present", "current", "now"}
        start, end = month_date(entry.start), month_date(entry.end)
        if start and end and start > end:
            raise ValueError("Reversed dates")
        dates = " – ".join(filter(None, [entry.start, entry.end]))
        header = " | ".join(filter(None, [entry.title, entry.company, entry.location, dates]))
        bullets = "\n".join("• " + " ".join(bullet.split()) for bullet in entry.bullets)
        source = "\n".join(filter(None, [header, bullets, ", ".join(entry.skills), *entry.links]))
        partial = (entry.start and not start) or (entry.end and not end and not current)
        text = "\n".join(filter(None, [header if partial else "", bullets]))
        append(
            source,
            entry.page,
            {
                "kind": entry.kind,
                "title": entry.title,
                "company": entry.company,
                "location": entry.location,
                "start_date": start,
                "end_date": end,
                "current": current,
                "text": text,
                "skills": entry.skills,
                "links": entry.links,
            },
        )
    for offset in range(0, len(document.skills), 30):
        skills = document.skills[offset : offset + 30]
        if any(not skill.strip() or len(skill) > 200 for skill in skills):
            raise ValueError("Invalid skills")
        append(", ".join(skills), 1, {"kind": "skill", "skills": skills})
    if not lines or sum(len(line["text"]) for line in lines) > MAX_TEXT:
        raise ValueError("Invalid document")
    return lines
