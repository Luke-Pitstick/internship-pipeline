"""Coordinate independently retryable matching, generation and delivery work."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from internship_pipeline.models import (
    CandidateProfile,
    Job,
    MatchResult,
    ResumeArtifact,
    Settings,
    utcnow,
)
from internship_pipeline.queue import Queue, Task
from internship_pipeline.storage import Store, enqueue


class ResumeGenerator(Protocol):
    def generate(
        self,
        job: Job,
        match: MatchResult,
        profile: CandidateProfile,
        checkpoint: dict[str, object] | None = None,
    ) -> ResumeArtifact: ...


class DeliveryFailed(RuntimeError):
    pass


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        profile: CandidateProfile,
        store: Store,
        resume_service: ResumeGenerator | None = None,
        matcher: Callable[[Job, CandidateProfile, Settings], MatchResult] | None = None,
        notifier: Callable[[str, str, str, Path | None], bool] | None = None,
    ):
        from internship_pipeline.matching import match_job
        from internship_pipeline.notifications import send_notification
        from internship_pipeline.resumes.service import ResumeService

        self.settings = settings
        self.profile = profile
        self.store = store
        self.queue = Queue(store, settings.lease_seconds, settings.max_attempts)
        self.resume_service = resume_service or ResumeService(settings)
        self.matcher = matcher or match_job
        self.notifier = notifier or send_notification
        self.destinations = {
            hashlib.sha256(url.encode()).hexdigest()[:16]: url for url in settings.notification_urls
        }
        if settings.recording_notifications_path is not None:
            self.destinations["recording"] = "recording"

    def process_next(self, kinds: list[str]) -> bool:
        task = self.queue.claim(kinds)
        if task is None:
            return False
        try:
            with self.queue.heartbeat(task):
                if task.kind == "match":
                    self._match(task)
                elif task.kind == "resume":
                    self._resume(task)
                elif task.kind == "delivery":
                    self._deliver(task)
                else:
                    raise ValueError("Unknown task kind")
            self.queue.complete(task)
        except Exception as exc:
            # Error bodies from providers can include candidate data, tokens or prompts.
            error = type(exc).__name__
            if error in {"ResumeReconciliationRequired", "ResumeValidationError"}:
                self.queue.needs_attention(task, error)
            else:
                self.queue.fail(task, error)
        return True

    def _match(self, task: Task) -> None:
        job = self.store.get_job(task.payload["job_id"])
        if job.status != "open" or job.applied_at is not None:
            return
        result = self.matcher(job, self.profile, self.settings)
        self.store.save_match(job, result, self.profile.revision, list(self.destinations))

    def _resume(self, task: Task) -> None:
        job = self.store.get_job(task.payload["job_id"])
        if job.status != "open" or job.applied_at is not None:
            return
        if (
            task.payload["profile_revision"] != self.profile.revision
            or task.payload["content_hash"] != job.content_hash
        ):
            with self.store.transaction() as connection:
                enqueue(
                    connection,
                    "match",
                    f"match:{job.id}:{job.content_hash}:{self.profile.revision}",
                    {"job_id": job.id, "profile_revision": self.profile.revision},
                    utcnow().timestamp(),
                )
            return
        match = MatchResult.model_validate(task.payload["match"])
        artifact = self.resume_service.generate(job, match, self.profile)
        self.store.save_artifact(artifact, list(self.destinations))

    def _deliver(self, task: Task) -> None:
        from internship_pipeline.notifications import (
            opening_message,
            record_notification,
            resume_message,
        )

        if self.store.delivered(task.key):
            return
        job = self.store.get_job(task.payload["job_id"])
        if job.status != "open" or job.applied_at is not None:
            return
        destination_id = task.payload["destination_id"]
        destination = self.destinations.get(destination_id)
        if destination is None:
            raise DeliveryFailed("Configured destination has been removed")
        attachment = None
        if task.payload["kind"] == "opening":
            title, body = opening_message(job, MatchResult.model_validate(task.payload["match"]))
        else:
            artifact = self.store.get_artifact(task.payload["artifact_key"])
            title, body = resume_message(job, artifact)
            attachment = artifact.pdf_path
            if not attachment.is_file():
                raise DeliveryFailed("Saved resume file is missing")
        if destination_id == "recording":
            path = self.settings.recording_notifications_path
            assert path is not None
            sent = record_notification(path, title, body, attachment)
        else:
            sent = self.notifier(destination, title, body, attachment)
        if not sent:
            raise DeliveryFailed("Notification service did not accept delivery")
        self.store.record_delivery(task.key, job.id, task.payload["kind"], destination_id)

    def drain(self, limit: int = 100) -> int:
        """Run currently available work once; retries keep their future due times."""
        completed = 0
        while completed < limit:
            # Openings are sent before local generation when running the one-shot command.
            did_work = self.process_next(["delivery"])
            if not did_work:
                did_work = self.process_next(["match", "resume"])
            if not did_work:
                break
            completed += 1
        return completed
