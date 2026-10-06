"""Shared contracts between collection, matching, generation and delivery."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleFamily(StrEnum):
    SWE = "swe"
    PM = "pm"
    ML_AI = "ml_ai"
    DS = "ds"


class Constraints(Record):
    countries: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    term_keywords: list[str] = Field(default_factory=list)
    degree_level: str | None = None
    graduation_date: str | None = None
    requires_sponsorship: bool | None = None
    work_authorization: list[str] = Field(default_factory=list)


class ExperienceFact(Record):
    id: str
    text: str
    skills: list[str] = Field(default_factory=list)
    role_families: list[RoleFamily] = Field(default_factory=list)


class CandidateProfile(Record):
    settings_revision: int = 0
    availability_start: str | None = None
    availability_end: str | None = None
    preferred_roles: list[RoleFamily] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    name: str = ""
    email: str = ""
    constraints: Constraints = Field(default_factory=Constraints)
    facts: list[ExperienceFact] = Field(default_factory=list)
    protected_values: list[str] = Field(default_factory=list)
    master_resume_path: Path | None = None
    max_resume_pages: int = Field(default=1, ge=1, le=10)

    @property
    def revision(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class Company(Record):
    id: str
    name: str
    careers_url: str
    provider: str = "auto"
    priority: bool = False
    enabled: bool = True


class SourceJob(Record):
    source: str
    source_id: str
    board_id: str
    company: str
    title: str
    apply_url: str
    description: str
    source_url: str = ""
    locations: list[str] = Field(default_factory=list)
    employment_type: str | None = None
    requisition_id: str | None = None
    published_at: datetime | None = None
    timestamp_kind: str = "unknown"
    compensation: str | None = None
    deadline: str | None = None


class FetchResult(Record):
    jobs: list[SourceJob] = Field(default_factory=list)
    complete: bool = True
    coverage_limited: bool = False
    error: str | None = None
    retry_after_seconds: float | None = None


class Job(Record):
    id: str
    posting: SourceJob
    content_hash: str
    first_seen_at: datetime
    last_seen_at: datetime
    last_verified_at: datetime
    status: str = "open"
    event: str = "new"
    opening_revision: int = 0
    applied_at: datetime | None = None


class MatchResult(Record):
    fit: str
    eligible: bool | None = None
    role_family: RoleFamily | None = None
    reasons: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    missing_qualifications: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)
    requirement_excerpts: list[str] = Field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.fit in {"strong", "possible"} and self.eligible is not False


class ResumeArtifact(Record):
    key: str
    job_id: str
    pdf_path: Path
    resume_id: str
    engine: str = "legacy-resume-matcher"
    change_summary: list[str] = Field(default_factory=list)
    review_warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class SearchQuery(Record):
    id: str
    search_term: str
    location: str = ""
    country: str = "USA"
    sites: list[str] = Field(default_factory=lambda: ["indeed"])
    hours_old: int = Field(default=72, ge=1)
    results_wanted: int = Field(default=100, ge=1, le=1000)


class Settings(Record):
    database_path: Path = Path("data/pipeline.sqlite3")
    artifact_dir: Path = Path("artifacts")
    resume_model: str = Field(default="gpt-5.6-sol", min_length=1)
    resume_reasoning_effort: Literal["low", "high"] = "low"
    companies_path: Path = Path("config/companies.local.yaml")
    searches_path: Path | None = None
    notification_urls: list[str] = Field(default_factory=list, repr=False)
    recording_notifications_path: Path | None = None
    dot_outbox_path: Path | None = None
    priority_interval_seconds: int = Field(default=300, ge=120)
    standard_interval_seconds: int = Field(default=900, ge=300)
    search_interval_seconds: int = Field(default=3600, ge=1800)
    request_timeout_seconds: float = Field(default=30, gt=0)
    generation_timeout_seconds: float = Field(default=180, gt=0)
    lease_seconds: int = Field(default=300, ge=30)
    max_attempts: int = Field(default=5, ge=1)
