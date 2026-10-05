"""Source-preserving resume edits and bounded compilation of a trusted .tex file."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from internship_pipeline.models import CandidateProfile, Job
from internship_pipeline.resumes.client import ResumeMatcherError
from internship_pipeline.resumes.codex import LatexPlan
from internship_pipeline.resumes.validation import ResumeValidationError

TOKEN = re.compile(r"\\(?:[A-Za-z@]+\*?|.)|[{}$&%#_^~\r\n\t]")
MONTHS = (
    "january february march april may june july august september october november december "
    "jan feb mar apr jun jul aug sep sept oct nov dec present"
).split()
# Ordinary connective/action wording may change; substantive additions need a factual source.
PROSE = set(
    (
        "a an the and or for to of in on with by from as into through that which using "
        "built created developed implemented designed analyzed helped helping serving served "
        "supported supporting improved maintained delivered collaborated"
    ).split()
)


@dataclass(frozen=True)
class EditableSpan:
    id: int
    start: int
    end: int
    text: str

    def prompt_record(self) -> dict[str, Any]:
        return {"id": self.id, "text": self.text}


def _brace_end(source: str, start: int) -> int:
    depth = 0
    position = start
    while position < len(source):
        char = source[position]
        if char == "\\":
            position += 2
            continue
        if char == "%":
            position = source.find("\n", position)
            if position < 0:
                break
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return position
        position += 1
    raise ResumeValidationError("Original LaTeX has an unbalanced resume bullet")


def editable_spans(source: str) -> list[EditableSpan]:
    begin = source.find(r"\begin{document}")
    end = source.rfind(r"\end{document}")
    if begin < 0 or end <= begin:
        raise ResumeValidationError("Original source must be a standalone LaTeX document")
    spans: list[EditableSpan] = []
    for match in re.finditer(r"\\resumeItem\s*\{", source[begin:end]):
        start = begin + match.end() - 1
        finish = _brace_end(source, start)
        text = source[start + 1 : finish]
        # Known text formatting is retained. Unknown nested macros/URLs are never editable.
        commands = re.findall(r"\\([A-Za-z@]+\*?)", text)
        if any(command not in {"textbf", "textit", "emph", "underline"} for command in commands):
            continue
        if "%" in text or "\n" in text or len(text) < 20:
            continue
        spans.append(EditableSpan(len(spans), start + 1, finish, text))
    if not spans:
        raise ResumeValidationError(
            "Original LaTeX has no supported editable resumeItem bullets; "
            "configure content spans for the actual template before generation"
        )
    return spans


def load_source(path: Path | None) -> str:
    if path is None or path.suffix.lower() != ".tex" or not path.is_file():
        raise ResumeValidationError(
            "Original .tex source is required: set master_resume_path to the original LaTeX file. "
            "A PDF or Resume Matcher ID cannot preserve its formatting."
        )
    if path.stat().st_size > 512 * 1024:
        raise ResumeValidationError("Original LaTeX source exceeds 512 KiB")
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ResumeValidationError("Original LaTeX must be readable UTF-8 source") from exc


def _words(value: str) -> set[str]:
    return set(re.findall(r"[A-Za-z][A-Za-z0-9+.-]*", value.casefold()))


def apply_plan(
    source: str,
    spans: list[EditableSpan],
    plan: dict[str, Any],
    job: Job,
    profile: CandidateProfile,
) -> tuple[str, list[dict[str, Any]]]:
    try:
        parsed = LatexPlan.model_validate(plan)
    except ValueError as exc:
        raise ResumeValidationError("Invalid LaTeX edit plan") from exc
    facts = {fact.id: fact for fact in profile.facts}
    for keyword in parsed.keywords:
        if not keyword.phrase.strip() or keyword.phrase not in job.posting.description:
            raise ResumeValidationError("Ranked keyword is not verbatim job-description data")
        if not set(keyword.fact_ids).issubset(facts):
            raise ResumeValidationError("Keyword references an unsupported fact")
    indexed = {span.id: span for span in spans}
    edits: list[tuple[int, int, str]] = []
    report = []
    for edit in parsed.edits:
        span = indexed.get(edit.span_id)
        if span is None or not edit.old or span.text.count(edit.old) != 1:
            raise ResumeValidationError("Edit is not a unique substring of an allowed bullet")
        if not edit.fact_ids or not set(edit.fact_ids).issubset(facts):
            raise ResumeValidationError("Edit lacks supported factual provenance")
        if len(edit.new) != len(edit.old) or not edit.new.strip():
            raise ResumeValidationError("Edit changed the original character count")
        if TOKEN.findall(edit.old) != TOKEN.findall(edit.new):
            raise ResumeValidationError("Edit changed protected LaTeX syntax or layout")
        if re.findall(r"[.!?](?=\s|$)", edit.old) != re.findall(r"[.!?](?=\s|$)", edit.new):
            raise ResumeValidationError("Edit changed the original sentence punctuation count")
        # Preserve names/dates/protected identities wherever an editable bullet mentions them.
        for protected in (profile.name, profile.email, *profile.protected_values, *MONTHS):
            if protected and protected.casefold() in edit.old.casefold():
                if edit.old.casefold().count(protected.casefold()) != edit.new.casefold().count(
                    protected.casefold()
                ):
                    raise ResumeValidationError("Edit changed a protected factual value")
        old_numbers = re.findall(r"(?<!\w)\d[\d.,]*(?:%|\+)?(?!\w)", edit.old)
        new_numbers = re.findall(r"(?<!\w)\d[\d.,]*(?:%|\+)?(?!\w)", edit.new)
        if old_numbers != new_numbers:
            raise ResumeValidationError("Edit changed an original numerical claim")
        support = edit.old + " " + " ".join(facts[key].text for key in edit.fact_ids)
        support += " " + " ".join(skill for key in edit.fact_ids for skill in facts[key].skills)
        if _words(edit.new) - _words(support) - PROSE:
            raise ResumeValidationError("Edit introduced vocabulary unsupported by factual sources")
        start = span.start + span.text.index(edit.old)
        finish = start + len(edit.old)
        if any(start < other_end and finish > other_start for other_start, other_end, _ in edits):
            raise ResumeValidationError("LaTeX edits overlap")
        edits.append((start, finish, edit.new))
        report.append(edit.model_dump())
    result = source
    for start, end, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[end:]
    return result, report


class LatexCompiler:
    def __init__(self, executable: str = "pdflatex"):
        self.executable = executable

    @property
    def identity(self) -> dict[str, str]:
        return {"engine": self.executable, "flags_revision": "1"}

    def compile(self, source: str, deadline: float) -> bytes:
        with tempfile.TemporaryDirectory(prefix="internship-latex-") as directory:
            root = Path(directory)
            root.chmod(0o700)
            path = root / "resume.tex"
            path.write_bytes(source.encode("utf-8"))
            path.chmod(0o600)
            environment = os.environ.copy()
            environment.update({"openin_any": "p", "openout_any": "p", "TEXMFOUTPUT": str(root)})
            for _ in range(2):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ResumeMatcherError("LaTeX compilation deadline exceeded", retryable=True)
                try:
                    process = subprocess.Popen(
                        [
                            self.executable,
                            "-no-shell-escape",
                            "-interaction=nonstopmode",
                            "-halt-on-error",
                            "-file-line-error",
                            path.name,
                        ],
                        cwd=root,
                        env=environment,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                except OSError as exc:
                    raise ResumeValidationError(
                        "LaTeX compiler is unavailable; install the original template's "
                        "TeX dependencies"
                    ) from exc
                try:
                    process.communicate(timeout=remaining)
                except subprocess.TimeoutExpired as exc:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                    raise ResumeMatcherError(
                        "LaTeX compilation deadline exceeded", retryable=True
                    ) from exc
                except BaseException:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.communicate()
                    raise
                if process.returncode != 0:
                    raise ResumeValidationError(
                        "Original LaTeX did not compile; check template packages/assets locally"
                    )
            log_path = root / "resume.log"
            if log_path.is_file() and re.search(
                r"Overfull \\[hv]box", log_path.read_text(errors="replace")
            ):
                raise ResumeValidationError(
                    "LaTeX reports text overflow; inspect the original/tailored source layout"
                )
            pdf = root / "resume.pdf"
            if not pdf.is_file() or pdf.stat().st_size > 16 * 1024 * 1024:
                raise ResumeValidationError(
                    "LaTeX compiler produced missing or excessive PDF output"
                )
            return pdf.read_bytes()
