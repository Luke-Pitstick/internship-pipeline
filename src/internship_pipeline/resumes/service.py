"""Durable generation steps; ambiguous writes are reconciled before any retry."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from internship_pipeline.models import (
    CandidateProfile,
    Job,
    MatchResult,
    ResumeArtifact,
    Settings,
)
from internship_pipeline.resumes.client import (
    UPSTREAM_REVISION,
    ResumeMatcherClient,
    ResumeMatcherError,
    ResumeReconciliationRequired,
)
from internship_pipeline.resumes.validation import (
    ResumeValidationError,
    validate_facts,
    validate_master,
    validate_pdf,
)

GENERATION_CONFIG: dict[str, Any] = {
    "upstream_revision": UPSTREAM_REVISION,
    "template": "swiss-single",
    "prompt_id": "keywords",
    "page_size": "A4",
    "max_bullets": 4,
    "validation_revision": 1,
}


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            os.chmod(temporary, 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _save(path: Path, checkpoint: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(checkpoint, sort_keys=True).encode())


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ValueError("Expected checkpoint object")
        return value
    except (ValueError, OSError) as exc:
        raise ResumeReconciliationRequired(
            "Unreadable resume checkpoint; inspect before retry"
        ) from exc


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a") as stream:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ResumeMatcherError(
                "Resume generation is already in progress", retryable=True
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class ResumeService:
    def __init__(self, settings: Settings, *, client: ResumeMatcherClient | None = None):
        self.settings = settings
        self.client = client or ResumeMatcherClient(
            settings.resume_matcher_url, settings.request_timeout_seconds
        )
        self.root = settings.artifact_dir.resolve()
        self.checkpoints = self.root / ".checkpoints"

    def close(self) -> None:
        self.client.close()

    def generation_key(self, job: Job, match: MatchResult, profile: CandidateProfile) -> str:
        master_digest = self._master_digest(profile)
        return _hash(
            {
                "job_id": job.id,
                "description": job.posting.description,
                "profile_revision": profile.revision,
                "master_digest": master_digest,
                "role_family": match.role_family,
                "fact_ids": sorted(match.fact_ids),
                "config": GENERATION_CONFIG,
                "backend": self.settings.resume_matcher_url,
            }
        )

    @staticmethod
    def _master_digest(profile: CandidateProfile) -> str:
        if profile.master_resume_id:
            return _hash({"remote_master_id": profile.master_resume_id})
        path = profile.master_resume_path
        if path is None or not path.is_file():
            raise ResumeValidationError("A factual master resume PDF/DOCX or remote ID is required")
        if path.stat().st_size > 10 * 1024 * 1024:
            raise ResumeValidationError("Master resume exceeds the 10 MB upload limit")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def generate(
        self,
        job: Job,
        match: MatchResult,
        profile: CandidateProfile,
        checkpoint: dict[str, object] | None = None,
    ) -> ResumeArtifact:
        if not match.accepted:
            raise ResumeValidationError("Only accepted matches can generate a resume")
        if not profile.name.strip() or not profile.email.strip() or not profile.facts:
            raise ResumeValidationError("Candidate name, email and factual experience are required")
        known_ids = {fact.id for fact in profile.facts}
        if not set(match.fact_ids).issubset(known_ids):
            raise ResumeValidationError("Match references unsupported factual experience")
        if not job.posting.description.strip():
            raise ResumeValidationError("Job description is empty")
        key = self.generation_key(job, match, profile)
        state_path = self.checkpoints / f"{key}.json"
        with _lock(state_path.with_suffix(".lock")):
            state = _load(state_path) or dict(checkpoint or {})
            if state.get("key", key) != key:
                raise ResumeReconciliationRequired("Checkpoint belongs to a different generation")
            state["key"] = key
            if checkpoint is not None:
                checkpoint.clear()
                checkpoint.update(state)
                state = checkpoint
            manifest_path = self.root / key / "manifest.json"
            cached = self._cached(manifest_path, key, job.id)
            if cached is not None:
                return cached
            self.client.deadline = time.monotonic() + self.settings.generation_timeout_seconds
            try:
                master_id, master = self._master(profile)
                state["master_id"] = master_id
                _save(state_path, state)
                if state.get("pending") == "job":
                    raise ResumeReconciliationRequired(
                        "Job upload outcome is unknown; inspect upstream storage and supply job_id "
                        "in the disk checkpoint before clearing pending"
                    )
                if not state.get("job_id"):
                    self._mutation(
                        state_path,
                        state,
                        "job",
                        lambda: self.client.upload_job(job.posting.description, master_id),
                        "job_id",
                    )
                if state.get("pending") == "tailor":
                    self._reconcile_tailor(state_path, state)
                if not state.get("resume_id"):
                    self._mutation(
                        state_path,
                        state,
                        "tailor",
                        lambda: self.client.tailor(
                            master_id, str(state["job_id"]), GENERATION_CONFIG
                        ),
                        "tailor_result",
                    )
                    result = state["tailor_result"]
                    state["resume_id"] = result["resume_id"]
                    _save(state_path, state)
                resume_id = str(state["resume_id"])
                resume = self._ready(resume_id)
                if resume.get("parent_id") != master_id:
                    raise ResumeValidationError("Tailored resume does not reference the master")
                context = self.client.job_context(resume_id)
                if context.get("job_id") != state["job_id"]:
                    raise ResumeValidationError("Tailored resume references a different job")
                tailored = resume["processed_resume"]
                report = validate_facts(master, tailored, profile)
                pdf = self.client.download_pdf(resume_id, GENERATION_CONFIG["template"])
                pdf_report = validate_pdf(pdf, profile, tailored)
                result = state.get("tailor_result", {})
                warnings = report.warnings + pdf_report.warnings
                if isinstance(result, dict):
                    warnings.extend(str(value) for value in result.get("warnings", []))
                pdf_path = self.root / key / "resume.pdf"
                artifact = ResumeArtifact(
                    key=key,
                    job_id=job.id,
                    pdf_path=pdf_path,
                    resume_id=resume_id,
                    change_summary=report.changes,
                    review_warnings=list(dict.fromkeys(warnings)),
                )
                _atomic_write(pdf_path, pdf)
                manifest = {
                    "key": key,
                    "config": GENERATION_CONFIG,
                    "profile_revision": profile.revision,
                    "fact_ids": sorted(match.fact_ids),
                    "job_id": state["job_id"],
                    "master_id": master_id,
                    "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
                    "status": "review_needed" if warnings else "validated",
                    "artifact": artifact.model_dump(mode="json"),
                }
                _save(manifest_path, manifest)
                state["complete"] = True
                _save(state_path, state)
                return artifact
            finally:
                self.client.deadline = None

    def _cached(self, path: Path, key: str, job_id: str) -> ResumeArtifact | None:
        if not path.exists():
            return None
        manifest = _load(path)
        try:
            artifact = ResumeArtifact.model_validate(manifest["artifact"])
        except (KeyError, ValueError):
            return None
        expected_path = self.root / key / "resume.pdf"
        if (
            artifact.key != key
            or artifact.job_id != job_id
            or artifact.pdf_path != expected_path
            or not expected_path.is_file()
            or manifest.get("config") != GENERATION_CONFIG
        ):
            return None
        if hashlib.sha256(expected_path.read_bytes()).hexdigest() != manifest.get("pdf_sha256"):
            return None
        return artifact

    def _mutation(
        self, path: Path, state: dict[str, Any], stage: str, operation: Any, output: str
    ) -> None:
        state["pending"] = stage
        _save(path, state)
        try:
            state[output] = operation()
        except ResumeMatcherError as exc:
            if not exc.ambiguous:
                state.pop("pending", None)
                _save(path, state)
            raise
        state.pop("pending", None)
        if output == "tailor_result":
            state["resume_id"] = state[output]["resume_id"]
        _save(path, state)

    def _master(self, profile: CandidateProfile) -> tuple[str, dict[str, Any]]:
        master_key = _hash(
            {
                "profile": profile.revision,
                "digest": self._master_digest(profile),
                "backend": self.settings.resume_matcher_url,
                "version": UPSTREAM_REVISION,
            }
        )
        path = self.checkpoints / f"master-{master_key}.json"
        with _lock(path.with_suffix(".lock")):
            state = _load(path)
            if profile.master_resume_id:
                state["master_id"] = profile.master_resume_id
            filename = (
                f"pipeline-master-{master_key}{profile.master_resume_path.suffix.lower()}"
                if profile.master_resume_path
                else ""
            )
            if state.get("pending") == "master":
                matches = [
                    row
                    for row in self.client.list_resumes()
                    if row.get("filename") == filename and row.get("is_master")
                ]
                if len(matches) != 1:
                    raise ResumeReconciliationRequired(
                        "Master upload outcome unknown; inspect deterministic upload filename"
                    )
                state["master_id"] = matches[0]["resume_id"]
                state.pop("pending", None)
                _save(path, state)
            if not state.get("master_id"):
                if profile.master_resume_path is None:
                    raise ResumeValidationError("Master resume path is required")
                self._mutation(
                    path,
                    state,
                    "master",
                    lambda: self.client.upload_master(profile.master_resume_path, filename),
                    "master_id",
                )
            master_id = str(state["master_id"])
            resume = self._ready(master_id)
            if resume.get("is_master") is not True:
                raise ResumeValidationError("Configured source is not an upstream master resume")
            master = resume["processed_resume"]
            validate_master(master, profile)
            return master_id, master

    def _ready(self, resume_id: str) -> dict[str, Any]:
        while True:
            resume = self.client.get_resume(resume_id)
            status = resume.get("raw_resume", {}).get("processing_status")
            if status == "ready" and isinstance(resume.get("processed_resume"), dict):
                return resume
            if status == "failed":
                raise ResumeValidationError("Upstream master parsing failed; inspect before retry")
            if status not in {"pending", "processing"}:
                raise ResumeValidationError("Upstream resume lacks ready structured content")
            remaining = (self.client.deadline or time.monotonic()) - time.monotonic()
            if remaining <= 0:
                raise ResumeMatcherError("Resume processing deadline exceeded", retryable=True)
            time.sleep(min(0.25, remaining))

    def _reconcile_tailor(self, path: Path, state: dict[str, Any]) -> None:
        matches = []
        for row in self.client.list_resumes():
            if row.get("parent_id") != state["master_id"]:
                continue
            resume_id = self.client._id(row.get("resume_id"))
            context = self.client.job_context(resume_id)
            if context.get("job_id") == state["job_id"]:
                matches.append(resume_id)
        if len(matches) != 1:
            raise ResumeReconciliationRequired(
                "Tailoring outcome unknown; inspect remote draft before clearing pending"
            )
        state["resume_id"] = matches[0]
        state.pop("pending", None)
        _save(path, state)
