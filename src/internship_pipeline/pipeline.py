"""Process matching work independently of generation and integrations."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from internship_pipeline.models import (
    CandidateProfile,
    Job,
    MatchResult,
    Settings,
)
from internship_pipeline.queue import Queue, Task
from internship_pipeline.storage import Store


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        profile: CandidateProfile,
        store: Store,
        matcher: Callable[[Job, CandidateProfile, Settings], MatchResult] | None = None,
        settings_revision: int | None = None,
    ):
        self.settings_revision = settings_revision
        self.settings = settings
        self.profile = profile
        self.store = store
        self.queue = Queue(store, settings.lease_seconds, settings.max_attempts)
        self.matcher = matcher

    def process_next(self, kinds: list[str]) -> bool:
        task = self.queue.claim(kinds)
        if task is None:
            return False
        try:
            with self.queue.heartbeat(task):
                if task.kind == "match":
                    self._match(task)
                else:
                    raise ValueError("Unknown task kind")
            self.queue.complete(task)
        except Exception as exc:
            # Error bodies from providers can include candidate data, tokens or prompts.
            from internship_pipeline.assessments import MAX_ATTEMPTS, EvaluationError

            error = str(exc) if isinstance(exc, EvaluationError) else type(exc).__name__
            if isinstance(exc, EvaluationError) and error == "evaluation_busy":
                self.queue.defer(task)
            elif isinstance(exc, EvaluationError) and task.attempts >= MAX_ATTEMPTS:
                self.queue.needs_attention(task, error)
            elif isinstance(exc, EvaluationError) and error not in {
                "timeout",
                "provider_unavailable",
                "rate_limit",
            }:
                self.queue.needs_attention(task, error)
            else:
                self.queue.fail(task, error)
        return True

    def _match(self, task: Task) -> None:
        job = self.store.get_job(task.payload["job_id"])
        if job.status != "open" or job.applied_at is not None:
            return
        if self.matcher is None:
            import os

            from internship_pipeline.assessments import Assessments
            from internship_pipeline.model_connections import ModelConnectionStore

            root = Path(os.getenv("PIPELINE_DATA_DIR", str(self.settings.database_path.parent)))
            assessments = Assessments(
                self.store, ModelConnectionStore(self.store.path, root / "model-credentials.key")
            )
            assessments.evaluate(job.id, task.payload.get("assessment_identity"))
            return
        result = self.store.get_match(job, self.profile.revision)
        if result is None:
            result = self.matcher(job, self.profile, self.settings)
        self.store.save_match(
            job,
            result,
            self.profile.revision,
            settings_revision=self.settings_revision,
        )

    def drain(self, limit: int = 100) -> int:
        """Run currently available work once; retries keep their future due times."""
        completed = 0
        while completed < limit:
            did_work = self.process_next(["match"])
            if not did_work:
                break
            completed += 1
        return completed
