from __future__ import annotations

import copy
import json
import re
import shutil
import sys
import time
from pathlib import Path

import pytest
from test_resumes import job as job_fixture
from test_resumes import master as master_fixture
from test_resumes import match as match_fixture
from test_resumes import profile as profile_fixture
from test_resumes import textual_pdf

from internship_pipeline.models import Settings
from internship_pipeline.resumes.client import ResumeMatcherError
from internship_pipeline.resumes.latex import LatexCompiler, apply_plan, editable_spans, load_source
from internship_pipeline.resumes.service import ResumeService
from internship_pipeline.resumes.validation import ResumeValidationError

job = job_fixture
master = master_fixture
match = match_fixture
profile = profile_fixture


@pytest.fixture
def source(tmp_path, profile):
    text = (Path(__file__).parent / "fixtures/resume_original.tex").read_text()
    path = tmp_path / "original.tex"
    path.write_text(text)
    profile.master_resume_path = path
    return text


@pytest.fixture
def plan():
    return {
        "edits": [
            {
                "span_id": 0,
                "old": "serving",
                "new": "helping",
                "fact_ids": ["python"],
                "reason": "Emphasize the existing API's users without changing its metric.",
            }
        ],
        "keywords": [{"phrase": "Python", "fact_ids": ["python"], "reason": "Core requirement"}],
    }


class Generator:
    identity = {"engine": "synthetic-latex"}

    def __init__(self, plan):
        self.plan = plan
        self.calls = 0

    def tailor(self, source, spans, job, match, profile, deadline):
        self.calls += 1
        assert deadline > time.monotonic()
        return copy.deepcopy(self.plan)


class Compiler:
    identity = {"engine": "synthetic-compiler"}

    def __init__(self):
        self.sources = []
        self.fail_tailored = False
        self.pages = 1

    def compile(self, source, deadline):
        self.sources.append(source)
        if self.fail_tailored and "helping" in source:
            raise ResumeMatcherError("Synthetic interruption", retryable=True)
        text = re.sub(r"\\[A-Za-z]+\*?", " ", source.replace(r"\\", " "))
        text = text.replace("{", "").replace("}", "")
        return textual_pdf(text, pages=self.pages if "helping" in source else 1)


def test_source_and_layout_are_preserved_byte_for_byte(source, plan, job, profile):
    result, report = apply_plan(source, editable_spans(source), plan, job, profile)
    assert result == source.replace("serving", "helping")
    assert len(result) == len(source)
    assert report[0]["fact_ids"] == ["python"]


@pytest.mark.parametrize(
    "change", ["syntax", "number", "skill", "fact", "length", "outside", "keyword"]
)
def test_unsafe_edit_plans_fail_closed(change, source, plan, job, profile):
    edit = plan["edits"][0]
    if change == "syntax":
        edit.update(old="serving", new="\\inputx")
    elif change == "number":
        edit.update(old="12", new="99")
    elif change == "skill":
        edit.update(old="Python", new="Cobolx")
    elif change == "fact":
        edit["fact_ids"] = ["invented"]
    elif change == "length":
        edit["new"] = "supporting"
    elif change == "outside":
        edit.update(old="Example Labs", new="Invented Inc")
    else:
        plan["keywords"][0]["phrase"] = "Not in the description"
    with pytest.raises(ResumeValidationError):
        apply_plan(source, editable_spans(source), plan, job, profile)


def test_sentence_and_bullet_counts_are_protected(source, plan, job, profile):
    plan["edits"][0].update(old="serving", new="help.  ")
    with pytest.raises(ResumeValidationError, match="sentence"):
        apply_plan(source, editable_spans(source), plan, job, profile)


def test_bold_commands_are_preserved_and_unknown_nested_macros_are_not_editable(source):
    source = source.replace("Python", r"\textbf{Python}", 1)
    assert len(editable_spans(source)) == 2
    source = source.replace(r"\textbf{Python}", r"\href{https://example.test}{Python}")
    assert len(editable_spans(source)) == 1


def test_generate_compiles_original_source_and_persists_provenance(
    tmp_path, source, plan, job, match, profile
):
    generator, compiler = Generator(plan), Compiler()
    service = ResumeService(
        Settings(artifact_dir=tmp_path / "artifacts"), generator=generator, compiler=compiler
    )
    artifact = service.generate(job, match, profile)
    assert compiler.sources == [source, source.replace("serving", "helping")]
    assert artifact.resume_id.startswith("latex-")
    assert artifact.review_warnings
    output = artifact.pdf_path.parent
    assert (output / "resume.tex").read_text() == compiler.sources[1]
    report = json.loads((output / "changes.json").read_text())
    assert report["ranked_keywords"][0]["phrase"] == "Python"
    assert report["changes"][0]["fact_ids"] == ["python"]
    service.generate(job, match, profile)
    assert generator.calls == 1 and len(compiler.sources) == 2
    artifact.pdf_path.write_bytes(b"corrupt")
    service.generate(job, match, profile)
    assert generator.calls == 1 and len(compiler.sources) == 3


def test_compile_retry_reuses_verified_plan(tmp_path, source, plan, job, match, profile):
    generator, compiler = Generator(plan), Compiler()
    compiler.fail_tailored = True
    service = ResumeService(
        Settings(artifact_dir=tmp_path / "artifacts"), generator=generator, compiler=compiler
    )
    with pytest.raises(ResumeMatcherError):
        service.generate(job, match, profile)
    compiler.fail_tailored = False
    service.generate(job, match, profile)
    assert generator.calls == 1
    assert compiler.sources.count(source) == 1


def test_tailoring_cannot_change_page_count(tmp_path, source, plan, job, match, profile):
    profile.max_resume_pages = 2
    compiler = Compiler()
    compiler.pages = 2
    service = ResumeService(
        Settings(artifact_dir=tmp_path / "artifacts"), generator=Generator(plan), compiler=compiler
    )
    with pytest.raises(ResumeValidationError, match="page count"):
        service.generate(job, match, profile)


def test_missing_tex_fails_before_generator_and_does_not_reuse_legacy(
    tmp_path, plan, job, match, profile
):
    generator = Generator(plan)
    service = ResumeService(Settings(artifact_dir=tmp_path / "artifacts"), generator=generator)
    profile.master_resume_id = "legacy-resume"
    with pytest.raises(ResumeValidationError, match="Original .tex source is required"):
        service.generate(job, match, profile)
    assert generator.calls == 0
    assert list((tmp_path / "artifacts").glob("**/manifest.json")) == []
    with pytest.raises(ResumeValidationError):
        load_source(None)


def test_missing_compiler_is_actionable(source, tmp_path):
    with pytest.raises(ResumeValidationError, match="compiler is unavailable"):
        LatexCompiler(str(tmp_path / "missing-tex")).compile(source, time.monotonic() + 2)


def test_actual_latex_compile_preserves_original_template(
    tmp_path, source, plan, job, match, profile
):
    executable = shutil.which("pdflatex")
    if not executable:
        pytest.skip("Install pdflatex to run the actual synthetic template compile")
    artifact = ResumeService(
        Settings(artifact_dir=tmp_path / "real-artifacts", generation_timeout_seconds=30),
        generator=Generator(plan),
        compiler=LatexCompiler(executable),
    ).generate(job, match, profile)
    assert artifact.pdf_path.read_bytes().startswith(b"%PDF-")
    assert (artifact.pdf_path.parent / "resume.tex").read_text() == source.replace(
        "serving", "helping"
    )


def test_compiler_deadline_kills_child_process_group(tmp_path, source):
    executable = tmp_path / "sleeping-tex"
    executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(20)\n")
    executable.chmod(0o700)
    started = time.monotonic()
    with pytest.raises(ResumeMatcherError, match="deadline"):
        LatexCompiler(str(executable)).compile(source, started + 0.2)
    assert time.monotonic() - started < 3
