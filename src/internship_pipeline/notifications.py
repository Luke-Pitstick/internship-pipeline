"""Actionable plain-text alerts and a single-destination Apprise transport."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from internship_pipeline.models import Job, MatchResult, ResumeArtifact


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        return f"{value.isoformat(sep=' ', timespec='seconds')} (timezone unspecified)"
    return value.astimezone(UTC).isoformat(sep=" ", timespec="seconds")


def _term(job: Job) -> str:
    terms = re.findall(
        r"\b(?:summer|fall|autumn|winter|spring)\s*(?:20\d{2})?\b", job.posting.title, re.I
    )
    if not terms:
        terms = re.findall(
            r"\binternship\s+(?:term|period)\s*:\s*([^\n.;]+)",
            job.posting.description,
            re.I,
        )
    return "; ".join(dict.fromkeys(term.strip() for term in terms)) or "Not supplied"


def opening_message(job: Job, match: MatchResult) -> tuple[str, str]:
    """Render source time and observation time with separate, truthful labels."""
    labels = {
        "backlog": "Initial backlog",
        "baseline": "Initial backlog",
        "reopened": "Reopened posting",
        "updated": "Posting updated",
        "new": "Opening found",
    }
    event = labels.get(job.event, f"Posting observed ({job.event})")
    title = f"{event}: {job.posting.company} — {job.posting.title}"
    posting = job.posting
    source_time = _timestamp(posting.published_at) if posting.published_at else "Not supplied"
    eligibility = {
        True: "Confirmed checks passed",
        False: "Explicit conflict",
        None: "Unverified",
    }[match.eligible]
    lines = [
        f"Job reference: {job.id}",
        f"Company: {posting.company}",
        f"Role: {posting.title}",
        f"Location: {'; '.join(posting.locations) or 'Not supplied'}",
        f"Internship term: {_term(job)}",
        f"Fit: {match.fit} ({match.role_family.value if match.role_family else 'unclassified'})",
        f"Eligibility: {eligibility}",
        f"First observed: {_timestamp(job.first_seen_at)}",
        f"Source timestamp ({posting.timestamp_kind}): {source_time}",
        f"Last verified: {_timestamp(job.last_verified_at)}",
        f"Deadline: {posting.deadline or 'Not supplied'}",
        f"Compensation: {posting.compensation or 'Not supplied'}",
        "Fit reasons:",
        *(f"- {reason}" for reason in match.reasons[:3]),
    ]
    if match.missing_qualifications:
        lines.extend(
            ["Qualification gaps:", *(f"- {item}" for item in match.missing_qualifications)]
        )
    if match.unknowns:
        lines.extend(["Questions to confirm:", *(f"- {item}" for item in match.unknowns)])
    lines.extend(
        [f"Apply: {posting.apply_url}", "Application status: not submitted by this pipeline."]
    )
    return title, "\n".join(lines)


def resume_message(job: Job, artifact: ResumeArtifact) -> tuple[str, str]:
    """Render the second message for an already validated tailored artifact."""
    if artifact.job_id != job.id:
        raise ValueError("Resume artifact belongs to a different job")
    qualifier = " (review needed)" if artifact.review_warnings else ""
    title = f"Tailored resume ready{qualifier}: {job.posting.company} — {job.posting.title}"
    lines = [
        f"Job reference: {job.id}",
        f"Artifact reference: {artifact.key}",
        f"Created: {_timestamp(artifact.created_at)}",
        "Tailoring summary:",
    ]
    lines.extend(f"- {item}" for item in artifact.change_summary)
    if not artifact.change_summary:
        lines.append("- Change summary not supplied; review the attached draft.")
    if artifact.review_warnings:
        lines.extend(
            ["Review before applying:", *(f"- {item}" for item in artifact.review_warnings)]
        )
    lines.extend(
        [f"Apply: {job.posting.apply_url}", "Application status: not submitted by this pipeline."]
    )
    return title, "\n".join(lines)


def _valid_attachment(attachment: Path | None) -> bool:
    if attachment is None:
        return True
    try:
        return attachment.is_file() and attachment.stat().st_size > 0
    except OSError:
        return False


def send_notification(url: str, title: str, body: str, attachment: Path | None = None) -> bool:
    """Return provider acceptance; the caller owns durable delivery records and retries."""
    if not _valid_attachment(attachment):
        return False
    import apprise

    try:
        client = apprise.Apprise()
        if not client.add(url):
            return False
        # Apprise may send text successfully while ignoring unsupported attachments.
        if attachment is not None and any(not service.attachment_support for service in client):
            return False
        return (
            client.notify(
                title=title,
                body=body,
                body_format=apprise.NotifyFormat.TEXT,
                attach=str(attachment.resolve()) if attachment else None,
            )
            is True
        )
    except Exception:
        # No URL/exception logging: destination URLs can contain credentials.
        # Timeout acceptance is ambiguous; a retry can duplicate a delivered message.
        return False


def record_notification(path: Path, title: str, body: str, attachment: Path | None = None) -> bool:
    """Append an offline transport event, never a claim of live provider delivery."""
    if not _valid_attachment(attachment):
        return False
    event = {
        "transport": "recording",
        "title": title,
        "body": body,
        "attachment": str(attachment.resolve()) if attachment else None,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(event) + "\n")
        return True
    except OSError:
        return False
