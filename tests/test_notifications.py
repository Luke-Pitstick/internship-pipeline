from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from internship_pipeline.models import Job, MatchResult, ResumeArtifact, RoleFamily, SourceJob
from internship_pipeline.notifications import (
    opening_message,
    record_notification,
    resume_message,
    send_notification,
)


@pytest.fixture
def job() -> Job:
    seen = datetime(2026, 10, 5, 16, tzinfo=UTC)
    return Job(
        id="synthetic-job-1",
        posting=SourceJob(
            source="synthetic",
            source_id="1",
            board_id="synthetic",
            company="Example Labs",
            title="Summer 2027 Software Engineering Intern",
            description="Build Python services.",
            apply_url="https://example.test/apply/1",
            locations=["Remote, USA"],
            published_at=datetime(2026, 9, 25, tzinfo=UTC),
            timestamp_kind="updated",
            compensation="$30/hour",
            deadline="2026-11-01",
        ),
        content_hash="synthetic-hash",
        first_seen_at=seen,
        last_seen_at=seen,
        last_verified_at=seen,
        event="backlog",
    )


def test_opening_is_actionable_and_timestamps_are_distinct(job: Job) -> None:
    title, body = opening_message(
        job,
        MatchResult(
            fit="possible",
            role_family=RoleFamily.SWE,
            reasons=["Python is supported by project-1."],
            unknowns=["Confirm work authorization."],
            missing_qualifications=["Confirm SQL experience."],
        ),
    )
    assert "Initial backlog" in title
    assert "First observed: 2026-10-05" in body
    assert "Source timestamp (updated): 2026-09-25" in body
    assert "Job reference: synthetic-job-1" in body
    assert "Summer 2027" in body
    assert "Remote, USA" in body
    assert "2026-11-01" in body
    assert "$30/hour" in body
    assert "Python is supported by project-1." in body
    assert "Confirm work authorization." in body
    assert "Confirm SQL experience." in body
    assert job.posting.apply_url in body
    assert "not submitted" in body
    assert "%" not in body


def test_missing_posting_details_are_visible(job: Job) -> None:
    job.posting.published_at = None
    job.posting.timestamp_kind = "unknown"
    job.posting.deadline = None
    job.posting.compensation = None
    job.posting.locations = []
    job.posting.title = "Software Engineer Intern"
    _, body = opening_message(job, MatchResult(fit="possible"))
    for label in [
        "Source timestamp (unknown)",
        "Deadline",
        "Compensation",
        "Location",
        "Internship term",
    ]:
        assert f"{label}: Not supplied" in body


def test_resume_repeats_reference_link_summary_and_warnings(job: Job, tmp_path: Path) -> None:
    artifact = ResumeArtifact(
        key="synthetic-revision",
        job_id=job.id,
        pdf_path=tmp_path / "resume.pdf",
        resume_id="synthetic-resume",
        change_summary=["Moved Python project first."],
        review_warnings=["Check the summary wording."],
    )
    title, body = resume_message(job, artifact)
    assert "Tailored resume ready (review needed)" in title
    assert f"Job reference: {job.id}" in body
    assert "Moved Python project first." in body
    assert "Check the summary wording." in body
    assert job.posting.apply_url in body
    artifact.job_id = "another-job"
    with pytest.raises(ValueError, match="different job"):
        resume_message(job, artifact)


def mock_apprise(
    monkeypatch: pytest.MonkeyPatch, accepted: bool | None = True, attachment_support: bool = True
) -> MagicMock:
    import apprise

    client = MagicMock()
    client.add.return_value = True
    client.notify.return_value = accepted
    client.__iter__.return_value = iter([SimpleNamespace(attachment_support=attachment_support)])
    monkeypatch.setattr(apprise, "Apprise", lambda: client)
    return client


def test_pdf_delegated_to_real_apprise_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import apprise

    pdf = tmp_path / "synthetic.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic test artifact")
    client = mock_apprise(monkeypatch)
    assert send_notification("synthetic://destination", "Resume", "Details", pdf)
    client.add.assert_called_once_with("synthetic://destination")
    client.notify.assert_called_once_with(
        title="Resume",
        body="Details",
        body_format=apprise.NotifyFormat.TEXT,
        attach=str(pdf.resolve()),
    )


@pytest.mark.parametrize("accepted", [False, None])
def test_failure_or_no_targets_remains_failure(
    monkeypatch: pytest.MonkeyPatch, accepted: bool | None
) -> None:
    mock_apprise(monkeypatch, accepted)
    assert not send_notification("synthetic://destination", "Opening", "Details")


def test_timeout_is_not_delivery_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = mock_apprise(monkeypatch)
    client.notify.side_effect = TimeoutError("synthetic destination secret")
    assert not send_notification("synthetic://secret", "Opening", "Details")


def test_invalid_destination_is_not_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    client = mock_apprise(monkeypatch)
    client.add.return_value = False
    assert not send_notification("synthetic://destination", "Opening", "Details")
    client.notify.assert_not_called()


def test_unsupported_attachment_cannot_claim_pdf_delivered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pdf = tmp_path / "synthetic.pdf"
    pdf.write_bytes(b"synthetic fixture")
    client = mock_apprise(monkeypatch, attachment_support=False)
    assert not send_notification("synthetic://destination", "Resume", "Details", pdf)
    client.notify.assert_not_called()


def test_missing_or_empty_attachment_prevents_delivery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = mock_apprise(monkeypatch)
    missing = tmp_path / "missing.pdf"
    assert not send_notification("synthetic://destination", "Resume", "Details", missing)
    missing.touch()
    assert not send_notification("synthetic://destination", "Resume", "Details", missing)
    client.notify.assert_not_called()


def test_recording_transport_is_offline_and_preserves_attachment(tmp_path: Path) -> None:
    path = tmp_path / "recording" / "events.jsonl"
    attachment = tmp_path / "synthetic.pdf"
    attachment.write_bytes(b"synthetic fixture")
    assert record_notification(path, "Opening", "Apply: https://example.test/apply/1")
    assert record_notification(path, "Resume", "Summary", attachment)
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert [event["transport"] for event in events] == ["recording", "recording"]
    assert events[1]["attachment"] == str(attachment.resolve())
    assert "url" not in events[0]
    assert not record_notification(path, "Resume", "Details", tmp_path / "missing.pdf")
