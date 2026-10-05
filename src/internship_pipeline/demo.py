"""A synthetic offline demonstration, explicitly separate from real resume generation."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from internship_pipeline.models import (
    CandidateProfile,
    ExperienceFact,
    FetchResult,
    Job,
    MatchResult,
    ResumeArtifact,
    Settings,
    SourceJob,
)
from internship_pipeline.pipeline import Pipeline
from internship_pipeline.storage import Store


def synthetic_pdf(path: Path) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    content = DecodedStreamObject()
    content.set_data(
        b"BT /F1 12 Tf 40 740 Td (SYNTHETIC OFFLINE DEMO - NOT A TAILORED RESUME) Tj "
        b"0 -30 Td (Example Candidate - demo@example.invalid) Tj "
        b"0 -30 Td (Projects: Built a Python internship search prototype.) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as output:
        writer.write(output)


class DemoGenerator:
    def __init__(self, directory: Path):
        self.directory = directory
        self.calls = 0

    def generate(
        self,
        job: Job,
        match: MatchResult,
        profile: CandidateProfile,
        checkpoint: dict[str, object] | None = None,
    ) -> ResumeArtifact:
        self.calls += 1
        path = self.directory / "synthetic-demo.pdf"
        synthetic_pdf(path)
        return ResumeArtifact(
            key=f"demo:{job.id}",
            job_id=job.id,
            pdf_path=path,
            resume_id="synthetic-demo",
            change_summary=["Synthetic fixture; Resume Matcher was not called."],
            review_warnings=["Demo only: this PDF must not be used for an application."],
        )


def run_demo(directory: Path) -> dict[str, Any]:
    # A unique child protects previously observed state and makes repeated demos explicit.
    directory = directory / uuid.uuid4().hex[:12]
    settings = Settings(
        database_path=directory / "pipeline.sqlite3",
        artifact_dir=directory / "artifacts",
        recording_notifications_path=directory / "notifications.jsonl",
    )
    profile = CandidateProfile(
        name="Example Candidate",
        email="demo@example.invalid",
        facts=[
            ExperienceFact(
                id="python-project", text="Built a Python search prototype.", skills=["Python"]
            )
        ],
    )
    store = Store(settings.database_path)
    store.register_target("demo", "company", "{}", "synthetic")
    store.ingest("demo", FetchResult(), profile.revision)
    result = FetchResult(
        jobs=[
            SourceJob(
                source="synthetic",
                source_id="demo-internship",
                board_id="example",
                company="Example Company",
                title="Software Engineering Intern - Summer 2027",
                apply_url="https://example.invalid/internship",
                employment_type="Intern",
                description=(
                    "Software engineering internship using Python. Build a search prototype."
                ),
            )
        ]
    )
    store.ingest("demo", result, profile.revision)
    generator = DemoGenerator(settings.artifact_dir)
    pipeline = Pipeline(settings, profile, store, resume_service=generator)
    pipeline.drain()
    store.ingest("demo", result, profile.revision)
    pipeline.drain()
    path = settings.recording_notifications_path
    assert path is not None
    messages = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return {
        "mode": "synthetic offline demo; no external services called",
        "directory": str(directory),
        "recorded_messages": len(messages),
        "generation_calls": generator.calls,
        "repeat_scan_added_messages": len(messages) - 2,
        "health": store.health(),
    }
