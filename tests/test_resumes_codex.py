from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

import pytest
from test_resumes import job as job_fixture
from test_resumes import master as master_fixture
from test_resumes import match as match_fixture
from test_resumes import profile as profile_fixture

from internship_pipeline.resumes.client import ResumeMatcherError
from internship_pipeline.resumes.codex import DISABLED_FEATURES, CodexResumeGenerator
from internship_pipeline.resumes.validation import ResumeValidationError

job = job_fixture
master = master_fixture
match = match_fixture
profile = profile_fixture


def executable(tmp_path: Path, payload: dict, behavior: str = "ok") -> tuple[Path, Path]:
    path = tmp_path / "synthetic-codex"
    recording = tmp_path / "recording.json"
    script = f"""#!{sys.executable}
import json, os, pathlib, sys, time
args = sys.argv[1:]
prompt = sys.stdin.read()
pathlib.Path({str(recording)!r}).write_text(json.dumps({{
    "args": args, "prompt": prompt, "api_key_present": "OPENAI_API_KEY" in os.environ,
    "codex_home": os.environ.get("CODEX_HOME"), "cwd": os.getcwd()
}}))
behavior = {behavior!r}
if behavior == "timeout":
    time.sleep(20)
if behavior == "failure":
    print("private-provider-token", file=sys.stderr)
    sys.exit(1)
result = pathlib.Path(args[args.index("--output-last-message") + 1])
result.write_text("bad JSON" if behavior == "bad-json" else {json.dumps(payload)!r})
"""
    path.write_text(script)
    path.chmod(0o700)
    return path, recording


def test_cli_flags_default_model_and_subscription_environment(tmp_path, monkeypatch):
    binary, recording = executable(tmp_path, {"edits": [], "keywords": []})
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "saved-login"))
    result = CodexResumeGenerator(executable=str(binary))._run(
        "Synthetic edit plan", time.monotonic() + 5
    )
    assert result == {"edits": [], "keywords": []}
    record = json.loads(recording.read_text())
    args = record["args"]
    assert "--model" not in args
    assert args[0] == "exec" and args[-1] == "-"
    assert "--ignore-user-config" in args and "--ignore-rules" in args
    assert "--ephemeral" in args and "--skip-git-repo-check" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert 'web_search="disabled"' in args
    assert 'forced_login_method="chatgpt"' in args
    assert 'model_reasoning_effort="low"' in args
    for feature in DISABLED_FEATURES:
        assert args[args.index(feature) - 1] == "--disable"
    assert record["api_key_present"] is False
    assert record["codex_home"] == str(tmp_path / "saved-login")
    assert record["prompt"] == "Synthetic edit plan"
    assert not Path(record["cwd"]).exists()


def test_explicit_tested_model_is_passed(tmp_path):
    binary, recording = executable(tmp_path, {"edits": [], "keywords": []})
    CodexResumeGenerator(executable=str(binary), model="account-tested-model")._run(
        "Synthetic", time.monotonic() + 5
    )
    args = json.loads(recording.read_text())["args"]
    assert args[args.index("--model") + 1] == "account-tested-model"


def test_high_effort_is_explicit_and_part_of_generation_identity(tmp_path):
    binary, recording = executable(tmp_path, {"edits": [], "keywords": []})
    generator = CodexResumeGenerator(executable=str(binary), reasoning_effort="high")
    generator._run("Synthetic", time.monotonic() + 5)
    args = json.loads(recording.read_text())["args"]
    assert 'model_reasoning_effort="high"' in args
    assert generator.identity["reasoning_effort"] == "high"
    assert CodexResumeGenerator().identity["reasoning_effort"] == "low"


@pytest.mark.parametrize(
    "behavior,error",
    [
        ("timeout", ResumeMatcherError),
        ("failure", ResumeMatcherError),
        ("bad-json", ResumeValidationError),
    ],
)
def test_failed_runs_are_bounded_redacted_and_rejected(behavior, error, tmp_path):
    binary, recording = executable(tmp_path, {"edits": [], "keywords": []}, behavior)
    start = time.monotonic()
    with pytest.raises(error) as result:
        CodexResumeGenerator(executable=str(binary))._run(
            "Synthetic", start + (0.2 if behavior == "timeout" else 5)
        )
    assert time.monotonic() - start < 3
    assert "private-provider-token" not in str(result.value)
    if recording.exists():
        assert not Path(json.loads(recording.read_text())["cwd"]).exists()


def test_missing_cli_and_invalid_schema_are_rejected(tmp_path):
    with pytest.raises(ResumeMatcherError, match="cannot start"):
        CodexResumeGenerator(executable=str(tmp_path / "missing"))._run(
            "Synthetic", time.monotonic() + 5
        )
    binary, _ = executable(tmp_path, {"invented_schema": True})
    with pytest.raises(ResumeValidationError, match="invalid structured"):
        CodexResumeGenerator(executable=str(binary))._run("Synthetic", time.monotonic() + 5)


@pytest.fixture
def tailoring_input(job, match, profile):
    from internship_pipeline.resumes.latex import editable_spans

    source = (Path(__file__).parent / "fixtures/resume_original.tex").read_text()
    return source, [span.prompt_record() for span in editable_spans(source)], job, match, profile


@pytest.fixture
def valid_plan():
    return {
        "edits": [
            {
                "span_id": 0,
                "old": "serving",
                "new": "helping",
                "fact_ids": ["python"],
                "reason": "Existing API users",
            }
        ],
        "keywords": [{"phrase": "Python", "fact_ids": ["python"], "reason": "Requirement"}],
    }


def test_invalid_plan_is_corrected_with_feedback_and_same_deadline(
    tailoring_input, valid_plan, monkeypatch
):
    invalid = copy.deepcopy(valid_plan)
    invalid["keywords"][0]["phrase"] = "not verbatim JD"
    outputs = iter([invalid, valid_plan])
    prompts = []
    deadlines = []
    generator = CodexResumeGenerator()

    def run(prompt, deadline):
        prompts.append(prompt)
        deadlines.append(deadline)
        return next(outputs)

    monkeypatch.setattr(generator, "_run", run)
    deadline = time.monotonic() + 5
    assert generator.tailor(*tailoring_input, deadline) == valid_plan
    assert deadlines == [deadline, deadline]
    feedback = json.loads(prompts[1].split("CORRECTION DATA:\n")[1])
    assert feedback["prior_plan"] == invalid
    assert feedback["validation_error"] == "Ranked keyword is not verbatim job-description data"
    assert "untrusted DATA" in prompts[1]
    assert "allowed_prose_vocabulary" in prompts[0]
    assert "EXACT case-sensitive contiguous phrases" in prompts[0]


@pytest.mark.parametrize("failure", ["keyword", "length", "skill", "provenance", "syntax"])
def test_three_invalid_plans_exhaust_without_weakening_checks(
    failure, tailoring_input, valid_plan, monkeypatch
):
    invalid = copy.deepcopy(valid_plan)
    edit = invalid["edits"][0]
    if failure == "keyword":
        invalid["keywords"][0]["phrase"] = "not verbatim JD"
    elif failure == "length":
        edit["new"] = "supporting"
    elif failure == "skill":
        edit.update(old="Python", new="Cobolx")
    elif failure == "provenance":
        edit["fact_ids"] = ["invented"]
    else:
        edit["new"] = r"\inputx"
    calls = []
    generator = CodexResumeGenerator()

    def run(prompt, deadline):
        calls.append(prompt)
        return invalid

    monkeypatch.setattr(generator, "_run", run)
    with pytest.raises(ResumeValidationError):
        generator.tailor(*tailoring_input, time.monotonic() + 5)
    assert len(calls) == 3


def test_correction_attempts_stop_at_original_deadline(tailoring_input, monkeypatch):
    import internship_pipeline.resumes.codex as module

    clock = [10.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    generator = CodexResumeGenerator()
    calls = []

    def run(prompt, deadline):
        calls.append(deadline)
        clock[0] = deadline
        return {"edits": [], "keywords": [{"phrase": "absent", "fact_ids": [], "reason": ""}]}

    monkeypatch.setattr(generator, "_run", run)
    with pytest.raises(ResumeMatcherError, match="deadline exceeded"):
        generator.tailor(*tailoring_input, 11.0)
    assert calls == [11.0]


def test_invalid_structured_output_can_be_corrected(tailoring_input, monkeypatch):
    generator = CodexResumeGenerator()
    prompts = []

    def run(prompt, deadline):
        prompts.append(prompt)
        if len(prompts) == 1:
            raise ResumeValidationError("Codex returned invalid structured resume data")
        return {"edits": [], "keywords": []}

    monkeypatch.setattr(generator, "_run", run)
    assert generator.tailor(*tailoring_input, time.monotonic() + 5) == {"edits": [], "keywords": []}
    assert len(prompts) == 2
    feedback = json.loads(prompts[1].split("CORRECTION DATA:\n")[1])
    assert feedback["prior_plan"] is None


def test_provider_failure_is_not_retried_as_plan_correction(tailoring_input, monkeypatch):
    generator = CodexResumeGenerator()
    calls = []

    def run(prompt, deadline):
        calls.append(prompt)
        raise ResumeMatcherError("Provider unavailable", retryable=True)

    monkeypatch.setattr(generator, "_run", run)
    with pytest.raises(ResumeMatcherError, match="Provider unavailable"):
        generator.tailor(*tailoring_input, time.monotonic() + 5)
    assert len(calls) == 1
