"""Tailor the original LaTeX source and compile it without changing its template."""

from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from pypdf import PdfReader

from internship_pipeline.models import CandidateProfile, Job, MatchResult, ResumeArtifact, Settings
from internship_pipeline.resumes.client import ResumeMatcherError, ResumeReconciliationRequired
from internship_pipeline.resumes.codex import CodexResumeGenerator
from internship_pipeline.resumes.latex import LatexCompiler, apply_plan, editable_spans, load_source
from internship_pipeline.resumes.validation import ResumeValidationError, contains_value, normalized

GENERATION_CONFIG = {
    "engine": "original-latex",
    "source_policy_revision": 1,
    "validation_revision": 3,
    "formatting": "preserve-original",
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


def _plain_latex(text: str) -> str:
    # Only textbf/textit/emph/underline and escaped punctuation are editable.
    text = re.sub(r"\\(?:textbf|textit|emph|underline)\s*", "", text)
    text = re.sub(r"\\([%&#_$])", r"\1", text)
    return text.replace("{", "").replace("}", "")


def _pdf_text(pdf: bytes, profile: CandidateProfile) -> tuple[str, int]:
    if not pdf.startswith(b"%PDF-"):
        raise ResumeValidationError("LaTeX output is not a PDF")
    try:
        reader = PdfReader(io.BytesIO(pdf), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= profile.max_resume_pages:
            raise ResumeValidationError("LaTeX PDF is encrypted or exceeds the allowed page count")
        pages = [page.extract_text() or "" for page in reader.pages]
        if any(len(page.strip()) < 20 for page in pages):
            raise ResumeValidationError("Blank or unreadable LaTeX PDF page")
        text = normalized("\n".join(pages))
    except ResumeValidationError:
        raise
    except Exception as exc:
        raise ResumeValidationError("Malformed LaTeX PDF output") from exc
    if len(text) < 80:
        raise ResumeValidationError("Insufficient readable LaTeX PDF text")
    for value in (profile.name, profile.email, *profile.protected_values):
        if value and not contains_value(text, value):
            raise ResumeValidationError(
                "LaTeX PDF omitted contact or protected factual information"
            )
    return text, len(reader.pages)


class ResumeService:
    def __init__(
        self,
        settings: Settings,
        *,
        generator: CodexResumeGenerator | None = None,
        compiler: LatexCompiler | None = None,
        codex_model: str | None = None,
    ):
        self.settings = settings
        self.generator = generator or CodexResumeGenerator(model=codex_model)
        self.compiler = compiler or LatexCompiler()
        self.root = settings.artifact_dir.resolve()
        self.checkpoints = self.root / ".checkpoints"

    def generation_key(self, job: Job, match: MatchResult, profile: CandidateProfile) -> str:
        source = load_source(profile.master_resume_path)
        return self._key(job, match, profile, source)

    def _key(self, job: Job, match: MatchResult, profile: CandidateProfile, source: str) -> str:
        return _hash(
            {
                "job_id": job.id,
                "description": job.posting.description,
                "profile": profile.revision,
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                "role_family": match.role_family,
                "fact_ids": sorted(match.fact_ids),
                "config": GENERATION_CONFIG,
                "generator": self.generator.identity,
                "compiler": self.compiler.identity,
            }
        )

    def generate(
        self,
        job: Job,
        match: MatchResult,
        profile: CandidateProfile,
        checkpoint: dict[str, object] | None = None,
    ) -> ResumeArtifact:
        # Check source before starting Codex or looking at legacy Swiss checkpoints.
        source = load_source(profile.master_resume_path)
        spans = editable_spans(source)
        if not match.accepted:
            raise ResumeValidationError("Only accepted matches can generate a resume")
        if not profile.name.strip() or not profile.email.strip() or not profile.facts:
            raise ResumeValidationError("Candidate name, email and factual experience are required")
        if not set(match.fact_ids).issubset({fact.id for fact in profile.facts}):
            raise ResumeValidationError("Match references unsupported factual experience")
        if not job.posting.description.strip():
            raise ResumeValidationError("Job description is empty")
        deadline = time.monotonic() + self.settings.generation_timeout_seconds
        key = self._key(job, match, profile, source)
        state_path = self.checkpoints / f"{key}.json"
        with _lock(state_path.with_suffix(".lock")):
            cached = self._cached(key, job.id)
            if cached is not None:
                return cached
            state = _load(state_path)
            if state.get("key", key) != key:
                raise ResumeReconciliationRequired("Checkpoint belongs to another LaTeX generation")
            state["key"] = key
            if checkpoint is not None:
                checkpoint.clear()
                checkpoint.update(state)
                state = checkpoint
            baseline_key = _hash(
                {"source": source, "profile": profile.revision, "compiler": self.compiler.identity}
            )
            baseline_path = self.checkpoints / f"latex-baseline-{baseline_key}.pdf"
            with _lock(baseline_path.with_suffix(".lock")):
                if not baseline_path.exists():
                    baseline = self.compiler.compile(source, deadline)
                    _pdf_text(baseline, profile)
                    _atomic_write(baseline_path, baseline)
                baseline = baseline_path.read_bytes()
            _, original_pages = _pdf_text(baseline, profile)
            if "plan" not in state:
                state["plan"] = self.generator.tailor(
                    source, [span.prompt_record() for span in spans], job, match, profile, deadline
                )
                apply_plan(source, spans, state["plan"], job, profile)
                _save(state_path, state)
            tailored, changes = apply_plan(source, spans, state["plan"], job, profile)
            output = self.root / key
            tex_path = output / "resume.tex"
            pdf_path = output / "resume.pdf"
            _atomic_write(tex_path, tailored.encode("utf-8"))
            # A compile failure preserves the verified plan/source for an interruption-safe retry.
            pdf = self.compiler.compile(tailored, deadline)
            text, pages = _pdf_text(pdf, profile)
            if pages != original_pages:
                raise ResumeValidationError("Tailoring changed the original PDF page count")
            for span in editable_spans(tailored):
                if normalized(_plain_latex(span.text)) not in text:
                    raise ResumeValidationError(
                        "Compiled PDF omitted original/tailored bullet content"
                    )
            warnings = [
                "Semantic grounding is unverified; compare edited claims "
                "against factual experience",
                "Original LaTeX syntax and character counts are preserved; "
                "visually review line wrapping",
            ]
            summary = [str(change["reason"]) for change in changes]
            if not changes:
                summary = [
                    "Preserved the original source; no supported wording edits were proposed"
                ]
            artifact = ResumeArtifact(
                key=key,
                job_id=job.id,
                pdf_path=pdf_path,
                resume_id=f"latex-{key}",
                engine="original-latex",
                change_summary=summary,
                review_warnings=warnings,
            )
            _atomic_write(pdf_path, pdf)
            report_path = output / "changes.json"
            _save(
                report_path,
                {
                    "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                    "source_policy": GENERATION_CONFIG,
                    "changes": changes,
                    "ranked_keywords": state["plan"]["keywords"],
                    "matched_fact_ids": sorted(match.fact_ids),
                    "warnings": warnings,
                },
            )
            _save(
                output / "manifest.json",
                {
                    "key": key,
                    "config": GENERATION_CONFIG,
                    "profile_revision": profile.revision,
                    "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                    "tex_sha256": hashlib.sha256(tailored.encode()).hexdigest(),
                    "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
                    "status": "review_needed",
                    "artifact": artifact.model_dump(mode="json"),
                },
            )
            state["complete"] = True
            _save(state_path, state)
            return artifact

    def _cached(self, key: str, job_id: str) -> ResumeArtifact | None:
        output = self.root / key
        try:
            manifest = _load(output / "manifest.json")
            artifact = ResumeArtifact.model_validate(manifest["artifact"])
            if (
                artifact.key != key
                or artifact.job_id != job_id
                or artifact.pdf_path != output / "resume.pdf"
                or manifest["config"] != GENERATION_CONFIG
                or hashlib.sha256((output / "resume.pdf").read_bytes()).hexdigest()
                != manifest["pdf_sha256"]
                or hashlib.sha256((output / "resume.tex").read_bytes()).hexdigest()
                != manifest["tex_sha256"]
            ):
                return None
            return artifact
        except (KeyError, ValueError, OSError, ResumeReconciliationRequired):
            return None
