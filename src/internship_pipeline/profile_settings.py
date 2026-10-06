"""Immutable owner-edited profile and search snapshots, separate from infrastructure config."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from datetime import date
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator, model_validator

from internship_pipeline.models import (
    CandidateProfile,
    Constraints,
    ExperienceFact,
    Record,
    RoleFamily,
    utcnow,
)
from internship_pipeline.storage import Store


class Fact(Record):
    id: str = Field(default_factory=lambda: str(uuid4()), pattern=r"^[A-Za-z0-9_-]{1,80}$")
    kind: Literal["experience", "project", "skill"] = "experience"
    status: Literal["confirmed", "unknown"] = "unknown"
    text: str = Field(default="", max_length=2000)
    skills: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def confirmed_text(self) -> Fact:
        if self.status == "confirmed" and not self.text.strip():
            raise ValueError("Confirmed facts need supporting text")
        return self


class Education(Record):
    id: str = Field(default_factory=lambda: str(uuid4()), pattern=r"^[A-Za-z0-9_-]{1,80}$")
    status: Literal["confirmed", "unknown"] = "unknown"
    institution: str = Field(default="", max_length=200)
    degree: str = Field(default="", max_length=200)
    field: str = Field(default="", max_length=200)
    graduation_date: date | None = None

    @model_validator(mode="after")
    def confirmed_education(self) -> Education:
        if self.status == "confirmed" and not (self.institution.strip() and self.degree.strip()):
            raise ValueError("Confirmed education needs an institution and degree")
        return self


class Profile(Record):
    name: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=254)
    facts: list[Fact] = Field(default_factory=list, max_length=100)
    education: list[Education] = Field(default_factory=list, max_length=20)
    available_from: date | None = None
    available_until: date | None = None
    requires_sponsorship: bool | None = None
    work_authorization: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip()
        if value and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email or leave it unknown")
        return value

    @model_validator(mode="after")
    def valid_profile(self) -> Profile:
        ids = [item.id for item in self.facts] + [item.id for item in self.education]
        if len(ids) != len(set(ids)):
            raise ValueError("Fact identifiers must be unique")
        if (
            self.available_from
            and self.available_until
            and self.available_until < self.available_from
        ):
            raise ValueError("Availability end must be on or after its start")
        return self


class HardConstraints(Record):
    countries: list[str] = Field(default_factory=list, max_length=30)
    locations: list[str] = Field(default_factory=list, max_length=30)
    term_keywords: list[str] = Field(default_factory=list, max_length=30)


class SoftPreferences(Record):
    roles: list[RoleFamily] = Field(default_factory=list, max_length=4)
    locations: list[str] = Field(default_factory=list, max_length=30)
    skills: list[str] = Field(default_factory=list, max_length=50)


class Preferences(Record):
    hard: HardConstraints = Field(default_factory=HardConstraints)
    soft: SoftPreferences = Field(default_factory=SoftPreferences)


class SaveSettings(Record):
    expected_revision: int = Field(ge=0, strict=True)
    profile: Profile
    preferences: Preferences

    @model_validator(mode="after")
    def bounded_items(self) -> SaveSettings:
        groups = [
            self.profile.work_authorization,
            self.preferences.hard.countries,
            self.preferences.hard.locations,
            self.preferences.hard.term_keywords,
            self.preferences.soft.locations,
            self.preferences.soft.skills,
        ]
        groups += [fact.skills for fact in self.profile.facts]
        if any(not item.strip() or len(item) > 200 for group in groups for item in group):
            raise ValueError("List entries must contain 1–200 characters")
        return self


class Snapshot(Record):
    revision: int = 0
    saved_at: str | None = None
    profile: Profile = Field(default_factory=Profile)
    preferences: Preferences = Field(default_factory=Preferences)

    def candidate(self) -> CandidateProfile:
        """Only confirmed claims enter downstream candidate evidence."""
        facts = [
            ExperienceFact(id=f.id, text=f.text, skills=f.skills)
            for f in self.profile.facts
            if f.status == "confirmed"
        ]
        for education in self.profile.education:
            if education.status == "confirmed":
                facts.append(
                    ExperienceFact(
                        id=education.id,
                        text=" — ".join(
                            filter(
                                None,
                                [
                                    education.institution,
                                    education.degree,
                                    education.field,
                                    str(education.graduation_date)
                                    if education.graduation_date
                                    else "",
                                ],
                            )
                        ),
                    )
                )
        confirmed = [e for e in self.profile.education if e.status == "confirmed"]
        degree = confirmed[0].degree if len(confirmed) == 1 else None
        graduation = confirmed[0].graduation_date if len(confirmed) == 1 else None
        return CandidateProfile(
            settings_revision=self.revision,
            name=self.profile.name,
            email=self.profile.email,
            facts=facts,
            constraints=Constraints(
                **self.preferences.hard.model_dump(),
                degree_level=degree,
                graduation_date=str(graduation) if graduation else None,
                requires_sponsorship=self.profile.requires_sponsorship,
                work_authorization=self.profile.work_authorization,
            ),
            availability_start=str(self.profile.available_from)
            if self.profile.available_from
            else None,
            availability_end=str(self.profile.available_until)
            if self.profile.available_until
            else None,
            preferred_roles=self.preferences.soft.roles,
            preferred_locations=self.preferences.soft.locations,
            preferred_skills=self.preferences.soft.skills,
        )


class RevisionConflict(ValueError):
    pass


class ProfileSettings:
    def __init__(self, store: Store):
        self.store = store
        with store.connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS profile_settings_revisions (
                    revision INTEGER PRIMARY KEY, saved_at TEXT NOT NULL,
                    profile TEXT NOT NULL, preferences TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS profile_settings_no_update
                BEFORE UPDATE ON profile_settings_revisions BEGIN
                    SELECT RAISE(ABORT, 'Profile/settings revisions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS profile_settings_no_delete
                BEFORE DELETE ON profile_settings_revisions BEGIN
                    SELECT RAISE(ABORT, 'Profile/settings revisions are immutable');
                END;
            """)

    def read(self) -> Snapshot:
        with self.store.connection() as connection:
            row = connection.execute(
                "SELECT * FROM profile_settings_revisions ORDER BY revision DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return Snapshot()
        return Snapshot(
            revision=row["revision"],
            saved_at=row["saved_at"],
            profile=Profile.model_validate_json(row["profile"]),
            preferences=Preferences.model_validate_json(row["preferences"]),
        )

    def save(
        self,
        data: SaveSettings,
        *,
        record_import: Callable[[sqlite3.Connection, int], None] | None = None,
    ) -> Snapshot:
        saved_at = utcnow().isoformat()
        with self.store.transaction() as connection:
            revision = connection.execute(
                "SELECT COALESCE(MAX(revision),0) FROM profile_settings_revisions"
            ).fetchone()[0]
            if revision != data.expected_revision:
                raise RevisionConflict(
                    "Settings changed in another tab. Reload saved settings before saving."
                )
            connection.execute(
                "INSERT INTO profile_settings_revisions VALUES(?,?,?,?)",
                (
                    revision + 1,
                    saved_at,
                    data.profile.model_dump_json(),
                    data.preferences.model_dump_json(),
                ),
            )
            if record_import is not None:
                record_import(connection, revision + 1)
        return Snapshot(
            revision=revision + 1,
            saved_at=saved_at,
            profile=data.profile,
            preferences=data.preferences,
        )


def profile_settings_router(settings: ProfileSettings, owner: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/profile-settings", dependencies=[Depends(owner)])

    @router.get("")
    def get_settings() -> Snapshot:
        return settings.read()

    @router.post("")
    def save_settings(body: SaveSettings) -> Snapshot:
        try:
            return settings.save(body)
        except RevisionConflict as exc:
            raise HTTPException(409, str(exc)) from None

    return router
