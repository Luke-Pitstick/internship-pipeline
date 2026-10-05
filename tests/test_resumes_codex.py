from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

import pytest
from test_resumes import master as master_fixture
from test_resumes import profile as profile_fixture

from internship_pipeline.models import CandidateProfile
from internship_pipeline.resumes.client import ResumeMatcherError
from internship_pipeline.resumes.codex import DISABLED_FEATURES, CodexResumeGenerator
from internship_pipeline.resumes.validation import ResumeValidationError

master = master_fixture
profile = profile_fixture


def structured(master: dict) -> dict:
    result = copy.deepcopy(master)
    result.pop("sectionMeta")
    result.pop("customSections")
    result["personalInfo"]["title"] = ""
    for row in result["workExperience"]:
        row["location"] = None
    for row in result["education"]:
        row["description"] = None
    for row in result["personalProjects"]:
        row["github"] = row["website"] = None
    return result


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


def test_cli_flags_default_model_and_subscription_environment(tmp_path, master, monkeypatch):
    binary, recording = executable(tmp_path, structured(master))
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "saved-login"))
    generator = CodexResumeGenerator(executable=str(binary))
    result = generator._run("Synthetic transformation, source text only.", time.monotonic() + 5)
    assert result["personalInfo"]["name"] == "Alex Example"
    record = json.loads(recording.read_text())
    args = record["args"]
    assert "--model" not in args
    assert args[0] == "exec" and args[-1] == "-"
    assert "--ignore-user-config" in args and "--ignore-rules" in args
    assert "--ephemeral" in args and "--skip-git-repo-check" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert 'web_search="disabled"' in args
    assert 'forced_login_method="chatgpt"' in args
    for feature in DISABLED_FEATURES:
        index = args.index(feature)
        assert args[index - 1] == "--disable"
    assert record["api_key_present"] is False
    assert record["codex_home"] == str(tmp_path / "saved-login")
    assert record["prompt"] == "Synthetic transformation, source text only."
    assert not Path(record["cwd"]).exists()  # Ephemeral schema/output directory was removed.


def test_explicit_tested_model_is_passed(tmp_path, master):
    binary, recording = executable(tmp_path, structured(master))
    generator = CodexResumeGenerator(executable=str(binary), model="account-tested-model")
    generator._run("Synthetic", time.monotonic() + 5)
    args = json.loads(recording.read_text())["args"]
    assert args[args.index("--model") + 1] == "account-tested-model"


@pytest.mark.parametrize(
    "behavior,error",
    [
        ("timeout", ResumeMatcherError),
        ("failure", ResumeMatcherError),
        ("bad-json", ResumeValidationError),
    ],
)
def test_failed_runs_are_bounded_redacted_and_rejected(behavior, error, tmp_path, master):
    binary, recording = executable(tmp_path, structured(master), behavior)
    generator = CodexResumeGenerator(executable=str(binary))
    start = time.monotonic()
    with pytest.raises(error) as result:
        generator._run("Synthetic", start + (0.2 if behavior == "timeout" else 5))
    assert time.monotonic() - start < 3
    assert "private-provider-token" not in str(result.value)
    if recording.exists():
        assert not Path(json.loads(recording.read_text())["cwd"]).exists()


def test_missing_cli_and_invalid_schema_are_rejected(tmp_path, master):
    with pytest.raises(ResumeMatcherError, match="cannot start"):
        CodexResumeGenerator(executable=str(tmp_path / "missing"))._run(
            "Synthetic", time.monotonic() + 5
        )
    binary, _ = executable(tmp_path, {"invented_schema": True})
    with pytest.raises(ResumeValidationError, match="invalid structured"):
        CodexResumeGenerator(executable=str(binary))._run("Synthetic", time.monotonic() + 5)


def test_master_pdf_parsing_uses_extracted_data_and_rejects_added_numbers(
    tmp_path, master, profile
):
    binary, recording = executable(tmp_path, structured(master))
    generator = CodexResumeGenerator(executable=str(binary))
    result = generator.parse_master(profile.master_resume_path, profile, time.monotonic() + 5)
    assert result["workExperience"][0]["company"] == "Example Labs"
    prompt = json.loads(recording.read_text())["prompt"]
    assert "resume_text" in prompt and "Built a Python API serving 12" in prompt
    bad = structured(master)
    bad["summary"] += " Increased revenue by 900%."
    binary, _ = executable(tmp_path, bad)
    with pytest.raises(ResumeValidationError, match="unsupported numerical"):
        CodexResumeGenerator(executable=str(binary)).parse_master(
            profile.master_resume_path, profile, time.monotonic() + 5
        )


def test_pdf_source_requires_extractable_text(tmp_path):
    source = tmp_path / "bad.pdf"
    source.write_bytes(b"not a PDF")
    with pytest.raises(ResumeValidationError, match="extract"):
        CodexResumeGenerator().parse_master(source, CandidateProfile(), time.monotonic() + 5)
