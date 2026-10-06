"""Authenticated upload, source review, and atomic profile/provenance confirmation."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, ValidationError
from starlette.concurrency import run_in_threadpool

from internship_pipeline.models import Record, utcnow
from internship_pipeline.profile_settings import (
    Education,
    Fact,
    ProfileSettings,
    RevisionConflict,
    SaveSettings,
    Snapshot,
)
from internship_pipeline.profiles.extract import MAX_UPLOAD, DocumentError
from internship_pipeline.storage import Store

_PROCESS_SLOT = threading.BoundedSemaphore(1)


class Selection(Record):
    line_id: str = Field(max_length=10)
    kind: Literal["experience", "project", "skill", "name", "email", "education"]
    institution: str = Field(default="", max_length=200)
    degree: str = Field(default="", max_length=200)
    skills: list[str] = Field(default_factory=list, max_length=30)
    source_line_ids: list[str] = Field(default_factory=list, max_length=3)
    value: str = Field(default="", max_length=2000)


class Review(Record):
    expected_revision: int = Field(ge=0, strict=True)
    selections: list[Selection] = Field(default_factory=list, max_length=120)
    remove_ids: list[str] = Field(default_factory=list, max_length=120)
    confirmed: bool = False


def extract_bounded(data: bytes, kind: str) -> list[dict[str, str]]:
    if not _PROCESS_SLOT.acquire(blocking=False):
        raise HTTPException(429, "Another document is processing. Try again shortly.")
    try:
        process = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).with_name("extract.py")), kind],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=12,
        )
        if process.returncode or len(process.stdout) > 700_000:
            raise DocumentError(
                "Document processing exceeded resource limits. Export a smaller file."
            )
        result = json.loads(process.stdout)
        if "error" in result:
            raise DocumentError(result["error"])
        return list(result["lines"])
    except subprocess.TimeoutExpired:
        raise DocumentError(
            "Document processing took too long. Export a simpler PDF or DOCX."
        ) from None
    finally:
        _PROCESS_SLOT.release()


def suggestions(lines: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Draft only literal source claims; leave unrecognized sections unselected."""
    result = []
    kind = "uncertain"
    headings = {
        "skills": "skill",
        "technical skills": "skill",
        "projects": "project",
        "experience": "experience",
        "work experience": "experience",
        "professional experience": "experience",
        "education": "education",
        "certifications": "uncertain",
        "interests": "uncertain",
        "summary": "uncertain",
        "objective": "uncertain",
    }
    consumed: set[str] = set()
    degree_pattern = re.compile(
        r"\b(?:Bachelor(?: of [A-Za-z ]+)?|Master(?: of [A-Za-z ]+)?|"
        r"B\.?Sc\.?|B\.?S\.?|B\.?A\.?|M\.?Sc\.?|M\.?S\.?|Ph\.?D\.?)\b"
    )
    for index, line in enumerate(lines):
        if line["id"] in consumed:
            continue
        value = line["text"]
        if value.lower().rstrip(":") in headings:
            kind = headings[value.lower().rstrip(":")]
            continue
        proposed = kind if kind in {"experience", "project", "skill"} else "experience"
        selected = kind in {"experience", "project", "skill"}
        skills: list[str] = []
        source_ids: list[str] = []
        institution = degree = excerpt = ""
        email = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value)
        if email:
            proposed = "email"
            selected = True
            excerpt = email.group()
        elif (
            index == 0
            and len(value) <= 100
            and len(value.split()) in {2, 3, 4}
            and all(word.replace("-", "").replace("'", "").isalpha() for word in value.split())
        ):
            proposed = "name"
            selected = True
        if kind == "education":
            school = re.search(r"(?:University|College|Institute|School)\b", value)
            if school:
                parts = [part.strip() for part in value.split("|")]
                degree_source = next((part for part in parts if degree_pattern.search(part)), "")
                institution = next(
                    (
                        part
                        for part in parts
                        if re.search(r"(?:University|College|Institute|School)\b", part)
                    ),
                    "",
                )
                if not degree_source and index + 1 < len(lines):
                    following = lines[index + 1]
                    if degree_pattern.search(following["text"]):
                        degree_source = following["text"]
                        source_ids = [following["id"]]
                        consumed.add(following["id"])
                if degree_source and len(institution) <= 200 and len(degree_source) <= 200:
                    proposed, selected, degree = "education", True, degree_source
        if kind == "skill" and proposed == "skill":
            # Delimited skills are literal claims, not interests or inferred abilities.
            skill_text = value
            if ":" in value and len(value.partition(":")[0]) <= 30:
                skill_text = value.partition(":")[2]
            items = [item.strip() for item in re.split(r"[,;|]", skill_text)]
            if len(items) <= 30 and all(item and len(item) <= 200 for item in items):
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


class ResumeImports:
    def __init__(self, store: Store):
        self.store = store
        self.settings = ProfileSettings(store)
        with store.connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS resume_imports (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, format TEXT NOT NULL,
                    digest TEXT NOT NULL, base_revision INTEGER NOT NULL, lines TEXT NOT NULL,
                    approved_revision INTEGER, evidence TEXT
                );
            """)

    def upload(self, data: bytes, kind: str, expected_revision: int) -> dict[str, Any]:
        if kind not in {"pdf", "docx"}:
            raise DocumentError("Only PDF and DOCX are supported.")
        if not data or len(data) > MAX_UPLOAD:
            raise DocumentError("Upload a nonempty document of at most 5 MiB.")
        if self.settings.read().revision != expected_revision:
            raise RevisionConflict("Settings changed. Reload saved settings before importing.")
        lines = extract_bounded(data, kind)
        if self.settings.read().revision != expected_revision:
            raise RevisionConflict("Settings changed during extraction. Reload and upload again.")
        identifier = str(uuid4())
        with self.store.transaction() as connection:
            connection.execute(
                "DELETE FROM resume_imports WHERE approved_revision IS NULL AND created_at < ?",
                ((utcnow() - timedelta(days=1)).isoformat(),),
            )
            if (
                connection.execute(
                    "SELECT COUNT(*) FROM resume_imports WHERE approved_revision IS NULL"
                ).fetchone()[0]
                >= 10
            ):
                connection.execute("""DELETE FROM resume_imports WHERE id = (
                    SELECT id FROM resume_imports WHERE approved_revision IS NULL
                    ORDER BY created_at LIMIT 1)""")
            connection.execute(
                "INSERT INTO resume_imports VALUES(?,?,?,?,?,?,NULL,NULL)",
                (
                    identifier,
                    utcnow().isoformat(),
                    kind,
                    hashlib.sha256(data).hexdigest(),
                    expected_revision,
                    json.dumps(lines),
                ),
            )
        return {
            "id": identifier,
            "expected_revision": expected_revision,
            "lines": lines,
            "suggestions": self.draft_suggestions(lines),
            "removable": self.removable(),
        }

    def draft_suggestions(self, lines: list[dict[str, str]]) -> list[dict[str, Any]]:
        proposed = suggestions(lines)
        snapshot = self.settings.read()
        facts_left = 100 - len(snapshot.profile.facts)
        education_left = 20 - len(snapshot.profile.education)
        selected = 0
        for item in proposed:
            if not item["selected"]:
                continue
            if item["kind"] in {"experience", "project", "skill"}:
                if facts_left <= 0:
                    item["selected"] = False
                else:
                    facts_left -= 1
            elif item["kind"] == "education":
                if education_left <= 0:
                    item["selected"] = False
                else:
                    education_left -= 1
            if selected >= 120:
                item["selected"] = False
            if item["selected"]:
                selected += 1
        return proposed

    def removable(self) -> list[dict[str, Any]]:
        snapshot = self.settings.read()
        items: list[Fact | Education] = [*snapshot.profile.facts, *snapshot.profile.education]
        values = {item.id: item.model_dump(mode="json") for item in items}
        imported: dict[str, dict[str, Any]] = {}
        with self.store.connection() as connection:
            for row in connection.execute(
                "SELECT evidence FROM resume_imports WHERE approved_revision IS NOT NULL "
                "ORDER BY approved_revision"
            ):
                for evidence in json.loads(row["evidence"]):
                    if (
                        evidence["field"] in values
                        and evidence["value"] == values[evidence["field"]]
                    ):
                        imported[evidence["field"]] = {
                            "id": evidence["field"],
                            "text": evidence["source_text"],
                        }
        return list(imported.values())

    def prepare(self, identifier: str, review: Review) -> tuple[SaveSettings, list[dict[str, Any]]]:
        current = self.settings.read()
        with self.store.connection() as connection:
            row = connection.execute(
                "SELECT * FROM resume_imports WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            raise HTTPException(404, "Import expired or unavailable. Upload the document again.")
        if datetime.fromisoformat(row["created_at"]) < utcnow() - timedelta(days=1):
            raise HTTPException(404, "Import expired. Upload the document again.")
        if row["approved_revision"] is not None:
            raise RevisionConflict(
                "This import was already confirmed. Upload a replacement to continue."
            )
        if review.expected_revision != current.revision or row["base_revision"] != current.revision:
            raise RevisionConflict("Settings changed. Reload saved settings and upload again.")
        if len({s.line_id for s in review.selections}) != len(review.selections):
            raise DocumentError("Choose each source line only once.")
        if not review.selections and not review.remove_ids:
            raise DocumentError("Select at least one source field or an imported fact to remove.")
        allowed = {item["id"] for item in self.removable()}
        if not set(review.remove_ids) <= allowed:
            raise DocumentError(
                "Manual or edited facts are protected. Change them in the profile editor."
            )
        profile = current.profile.model_copy(deep=True)
        profile.facts = [f for f in profile.facts if f.id not in review.remove_ids]
        profile.education = [e for e in profile.education if e.id not in review.remove_ids]
        lines = {line["id"]: line for line in json.loads(row["lines"])}
        evidence = []
        contacts: set[str] = set()

        def imported_id(signature: str) -> str:
            identifier = "import_" + hashlib.sha256(signature.encode()).hexdigest()[:32]
            # A manually edited import retains its ID; reintroducing the original claim
            # must preserve that edited entry and give the new claim its own stable ID.
            existing_items: list[Fact | Education] = [*profile.facts, *profile.education]
            existing_ids = {item.id for item in existing_items}
            if identifier in existing_ids:
                identifier = (
                    "import_"
                    + hashlib.sha256(
                        (signature + f"\0revision:{current.revision}").encode()
                    ).hexdigest()[:32]
                )
            return identifier

        for selection in review.selections:
            if selection.line_id not in lines:
                raise DocumentError("A selected source line is unavailable.")
            line = lines[selection.line_id]
            source_ids = list(dict.fromkeys([selection.line_id, *selection.source_line_ids]))
            if any(source_id not in lines for source_id in source_ids):
                raise DocumentError("A selected source line is unavailable.")
            source_text = "\n".join(lines[source_id]["text"] for source_id in source_ids)
            if selection.value and selection.value not in source_text:
                raise DocumentError("A selected value must be an exact excerpt of the source.")
            text = selection.value or source_text
            if any(
                not skill.strip() or len(skill) > 200 or skill not in text
                for skill in selection.skills
            ):
                raise DocumentError("Skills must be exact excerpts of the selected source line.")
            field: str = selection.kind
            value: Any = text
            if field in {"name", "email"}:
                if field in contacts:
                    raise DocumentError("Choose only one source line for each contact field.")
                contacts.add(field)
                setattr(profile, field, text)
            elif field == "education":
                if not all(
                    v.strip() and v in text for v in (selection.institution, selection.degree)
                ):
                    raise DocumentError(
                        "Institution and degree must be exact excerpts of the source line."
                    )
                existing = next(
                    (
                        e
                        for e in profile.education
                        if e.institution == selection.institution and e.degree == selection.degree
                    ),
                    None,
                )
                if existing:
                    continue
                stable_id = imported_id(selection.institution + "\0" + selection.degree)
                entry = Education(
                    id=stable_id,
                    status="confirmed",
                    institution=selection.institution,
                    degree=selection.degree,
                )
                profile.education.append(entry)
                field, value = entry.id, entry.model_dump(mode="json")
            else:
                if any(f.text == text and f.kind == selection.kind for f in profile.facts):
                    continue
                # Import identity remains stable between preview and save, and across replacement.
                stable_id = imported_id(selection.kind + "\0" + text)
                fact = Fact(
                    id=stable_id,
                    status="confirmed",
                    kind=cast(Literal["experience", "project", "skill"], selection.kind),
                    text=text,
                    skills=selection.skills,
                )
                profile.facts.append(fact)
                field, value = fact.id, fact.model_dump(mode="json")
            evidence.append(
                {
                    "field": field,
                    "value": value,
                    "line_id": selection.line_id,
                    "source_line_ids": source_ids,
                    "location": line["location"],
                    "source_text": source_text,
                }
            )
        data = SaveSettings.model_validate(
            {
                "expected_revision": current.revision,
                "profile": profile.model_dump(mode="json"),
                "preferences": current.preferences.model_dump(mode="json"),
            }
        )
        return data, evidence

    def confirm(self, identifier: str, review: Review) -> Snapshot:
        if not review.confirmed:
            raise DocumentError(
                "Explicitly confirm that you reviewed these changes against the source."
            )
        data, evidence = self.prepare(identifier, review)

        def record(connection: sqlite3.Connection, revision: int) -> None:
            result = connection.execute(
                "UPDATE resume_imports SET approved_revision=?, evidence=? "
                "WHERE id=? AND approved_revision IS NULL",
                (revision, json.dumps(evidence), identifier),
            )
            if result.rowcount != 1:
                raise RevisionConflict("This import is no longer available. Upload again.")

        return self.settings.save(data, record_import=record)

    def current(self) -> dict[str, Any]:
        with self.store.connection() as connection:
            row = connection.execute(
                "SELECT * FROM resume_imports WHERE approved_revision IS NOT NULL "
                "ORDER BY approved_revision DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return {"import": None}
        return {
            "import": {
                "id": row["id"],
                "format": row["format"],
                "digest": row["digest"],
                "approved_revision": row["approved_revision"],
                "lines": json.loads(row["lines"]),
                "evidence": json.loads(row["evidence"]),
            }
        }


def build_resume_import_router(store: Store, owner: Callable[..., Any]) -> APIRouter:
    service = ResumeImports(store)
    router = APIRouter(prefix="/api/resume-imports", dependencies=[Depends(owner)])

    def safely(action: Callable[[], Any]) -> Any:
        try:
            return action()
        except RevisionConflict as exc:
            raise HTTPException(409, str(exc)) from None
        except DocumentError as exc:
            raise HTTPException(422, str(exc)) from None
        except ValidationError:
            raise HTTPException(
                422, "Selected fields exceed profile limits or have invalid values."
            ) from None

    @router.post("/upload")
    async def upload(request: Request, format: str, expected_revision: int) -> Any:
        if expected_revision < 0:
            raise HTTPException(422, "Use the saved nonnegative profile revision.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_UPLOAD:
                raise HTTPException(413, "Upload at most 5 MiB.")
        return await run_in_threadpool(
            safely, lambda: service.upload(bytes(body), format, expected_revision)
        )

    @router.post("/{identifier}/preview")
    def preview(identifier: str, body: Review) -> Any:
        def prepare() -> dict[str, Any]:
            data, evidence = service.prepare(identifier, body)
            return {"before": service.settings.read(), "after": data, "evidence": evidence}

        return safely(prepare)

    @router.post("/{identifier}/confirm")
    def confirm(identifier: str, body: Review) -> Any:
        return safely(lambda: service.confirm(identifier, body))

    @router.get("/current")
    def current() -> Any:
        return service.current()

    return router
