from __future__ import annotations

import copy
import io
import json
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from internship_pipeline.models import (
    CandidateProfile,
    ExperienceFact,
    Job,
    MatchResult,
    RoleFamily,
    Settings,
    SourceJob,
    utcnow,
)
from internship_pipeline.resumes.client import (
    ResumeMatcherClient,
    ResumeMatcherError,
    ResumeReconciliationRequired,
)
from internship_pipeline.resumes.service import ResumeService
from internship_pipeline.resumes.validation import (
    ResumeValidationError,
    validate_facts,
    validate_master,
    validate_pdf,
)


def textual_pdf(text: str, pages: int = 1, x: int = 40) -> bytes:
    """Synthetic, text-bearing PDF fixture without an authoring dependency."""
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        lines = [f"BT /F1 10 Tf {x} 750 Td 14 TL"]
        for line in text.splitlines():
            safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            lines.append(f"({safe}) Tj T*")
        lines.append("ET")
        stream.set_data("\n".join(lines).encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def master() -> dict[str, Any]:
    return json.loads((Path(__file__).parent / "fixtures/resume_master.json").read_text())


def pdf_text(data: dict[str, Any]) -> str:
    lines = [
        data["personalInfo"]["name"],
        data["personalInfo"]["email"],
        "Summary",
        data["summary"],
    ]
    for section, heading in (
        ("workExperience", "Experience"),
        ("education", "Education"),
        ("personalProjects", "Projects"),
    ):
        lines.append(heading)
        for row in data[section]:
            lines.extend(
                str(value) for key, value in row.items() if key not in {"id", "description"}
            )
            if isinstance(row.get("description"), list):
                lines.extend(row["description"])
    lines.extend(["Skills", ", ".join(data["additional"]["technicalSkills"])])
    return "\n".join(lines)


@pytest.fixture
def profile(tmp_path: Path, master: dict[str, Any]) -> CandidateProfile:
    path = tmp_path / "master.pdf"
    path.write_bytes(textual_pdf(pdf_text(master)))
    return CandidateProfile(
        name="Alex Example",
        email="alex@example.test",
        master_resume_path=path,
        protected_values=["Example University", "2024 - 2028", "12"],
        facts=[
            ExperienceFact(
                id="python",
                text="Built a Python API serving 12 synthetic users.",
                skills=["Python"],
                role_families=[RoleFamily.SWE],
            ),
            ExperienceFact(id="sql", text="Analyzed weather records using SQL.", skills=["SQL"]),
        ],
    )


@pytest.fixture
def job() -> Job:
    now = utcnow()
    return Job(
        id="job-1",
        posting=SourceJob(
            source="greenhouse",
            source_id="1",
            board_id="example",
            company="Example Co",
            title="SWE Intern",
            apply_url="https://example.test/apply/1",
            description="Python software engineering internship.",
        ),
        content_hash="description-hash",
        first_seen_at=now,
        last_seen_at=now,
        last_verified_at=now,
    )


@pytest.fixture
def match() -> MatchResult:
    return MatchResult(fit="strong", role_family=RoleFamily.SWE, fact_ids=["python"])


class Backend:
    def __init__(self, master: dict[str, Any]):
        self.master = master
        self.tailored = copy.deepcopy(master)
        self.calls: Counter[str] = Counter()
        self.resumes: dict[str, dict[str, Any]] = {}
        self.jobs: dict[str, str] = {}
        self.fail_after: str | None = None
        self.pdf = textual_pdf(pdf_text(self.tailored))
        self.processing_status = "ready"
        self.bad_status: tuple[str, int] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1/")
        signature = f"{request.method} {path}"
        self.calls[signature] += 1
        if self.bad_status and self.bad_status[0] == signature:
            return httpx.Response(self.bad_status[1], json={"detail": "private-token-never-log"})
        if signature == "POST resumes/upload":
            assert b'name="file"' in request.content
            assert b'filename="pipeline-master-' in request.content
            filename = request.content.split(b'filename="')[1].split(b'"')[0].decode()
            self.resumes["master"] = {
                "resume_id": "master",
                "is_master": True,
                "filename": filename,
                "parent_id": None,
                "processed_resume": self.master,
                "raw_resume": {"processing_status": self.processing_status},
            }
            result: dict[str, Any] = {"resume_id": "master", "processing_status": "ready"}
        elif signature == "POST jobs/upload":
            body = json.loads(request.content)
            assert set(body) == {"resume_id", "job_descriptions"}
            assert body["resume_id"] == "master"
            self.jobs["remote-job"] = body["job_descriptions"][0]
            result = {"job_id": ["remote-job"]}
        elif signature == "POST resumes/improve":
            body = json.loads(request.content)
            assert body == {
                "resume_id": "master",
                "job_id": "remote-job",
                "prompt_id": "keywords",
                "max_bullets_per_entry": 4,
                "page_fit": {"template": "swiss-single", "pageSize": "A4"},
            }
            self.resumes["tailored"] = {
                "resume_id": "tailored",
                "is_master": False,
                "parent_id": "master",
                "processed_resume": self.tailored,
                "raw_resume": {"processing_status": "ready"},
            }
            result = {
                "data": {
                    "resume_id": "tailored",
                    "job_id": "remote-job",
                    "resume_preview": self.tailored,
                    "warnings": ["upstream warning"],
                }
            }
        elif signature == "GET resumes":
            result = {"data": self.resumes[request.url.params["resume_id"]]}
        elif signature == "GET resumes/list":
            assert request.url.params["include_master"] == "true"
            result = {"data": list(self.resumes.values())}
        elif signature == "GET resumes/tailored/job-description":
            result = {"job_id": "remote-job", "content": self.jobs["remote-job"]}
        elif signature == "GET resumes/tailored/pdf":
            assert request.url.params["template"] == "swiss-single"
            if self.fail_after == signature:
                self.fail_after = None
                raise httpx.ReadTimeout("Download interrupted")
            return httpx.Response(
                200, content=self.pdf, headers={"content-type": "application/pdf"}
            )
        else:
            raise AssertionError(f"Unexpected endpoint {signature}")
        if self.fail_after == signature:
            self.fail_after = None
            raise httpx.ReadTimeout("Response lost after remote commit")
        return httpx.Response(200, json=result)


def service(tmp_path: Path, backend: Backend, timeout: float = 180) -> ResumeService:
    settings = Settings(artifact_dir=tmp_path / "artifacts", generation_timeout_seconds=timeout)
    return ResumeService(
        settings,
        client=ResumeMatcherClient(
            settings.resume_matcher_url, transport=httpx.MockTransport(backend)
        ),
    )


def test_http_sequence_manifest_cache_and_application_state(tmp_path, master, profile, job, match):
    backend = Backend(master)
    worker = service(tmp_path, backend)
    checkpoint: dict[str, object] = {}
    artifact = worker.generate(job, match, profile, checkpoint)
    assert artifact.pdf_path.read_bytes().startswith(b"%PDF-")
    assert "upstream warning" in artifact.review_warnings
    assert any("Semantic grounding" in warning for warning in artifact.review_warnings)
    assert checkpoint["complete"] is True
    assert checkpoint["master_id"] == "master"
    assert checkpoint["job_id"] == "remote-job"
    manifest = json.loads(artifact.pdf_path.with_name("manifest.json").read_text())
    assert manifest["status"] == "review_needed"
    assert manifest["fact_ids"] == ["python"]
    calls = backend.calls.copy()
    assert service(tmp_path, backend).generate(job, match, profile) == artifact
    assert backend.calls == calls
    assert job.applied_at is None
    assert artifact.pdf_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("stage", ["POST resumes/upload", "POST resumes/improve"])
def test_lost_write_response_reconciles_without_repeated_creation(
    stage, tmp_path, master, profile, job, match
):
    backend = Backend(master)
    backend.fail_after = stage
    worker = service(tmp_path, backend)
    with pytest.raises(ResumeMatcherError):
        worker.generate(job, match, profile)
    artifact = service(tmp_path, backend).generate(job, match, profile)
    assert artifact.resume_id == "tailored"
    assert backend.calls[stage] == 1
    assert backend.calls["POST jobs/upload"] == 1


def test_ambiguous_job_upload_requires_attention(tmp_path, master, profile, job, match):
    backend = Backend(master)
    backend.fail_after = "POST jobs/upload"
    worker = service(tmp_path, backend)
    with pytest.raises(ResumeMatcherError):
        worker.generate(job, match, profile)
    with pytest.raises(ResumeReconciliationRequired, match="Job upload outcome"):
        worker.generate(job, match, profile)
    assert backend.calls["POST jobs/upload"] == 1


def test_download_retry_and_corrupt_artifact_reuse_remote_resume(
    tmp_path, master, profile, job, match
):
    backend = Backend(master)
    backend.fail_after = "GET resumes/tailored/pdf"
    worker = service(tmp_path, backend)
    with pytest.raises(ResumeMatcherError):
        worker.generate(job, match, profile)
    artifact = worker.generate(job, match, profile)
    artifact.pdf_path.write_bytes(b"corrupt")
    worker.generate(job, match, profile)
    assert backend.calls["POST resumes/upload"] == 1
    assert backend.calls["POST jobs/upload"] == 1
    assert backend.calls["POST resumes/improve"] == 1
    assert backend.calls["GET resumes/tailored/pdf"] == 3


def test_master_cached_across_jobs(tmp_path, master, profile, job, match):
    backend = Backend(master)
    worker = service(tmp_path, backend)
    worker.generate(job, match, profile)
    worker.generate(job.model_copy(update={"id": "another"}), match, profile)
    assert backend.calls["POST resumes/upload"] == 1
    assert backend.calls["POST jobs/upload"] == 2


@pytest.mark.parametrize("change", ["description", "profile", "master_bytes", "facts"])
def test_generation_key_covers_inputs(change, tmp_path, master, profile, job, match):
    worker = service(tmp_path, Backend(master))
    key = worker.generation_key(job, match, profile)
    if change == "description":
        job.posting.description += " SQL"
    elif change == "profile":
        profile.protected_values.append("extra")
    elif change == "master_bytes":
        profile.master_resume_path.write_bytes(b"different source file")
    else:
        match.fact_ids.append("sql")
    assert worker.generation_key(job, match, profile) != key


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("personalInfo", "email", "fake@example.test"),
        ("workExperience", "company", "Invented Employer"),
        ("workExperience", "years", "2020 - 2025"),
        ("education", "degree", "PhD Computer Science"),
        ("personalProjects", "name", "Invented Project"),
    ],
)
def test_factual_identity_mutations_rejected(section, field, value, master, profile):
    tailored = copy.deepcopy(master)
    target = tailored[section] if section == "personalInfo" else tailored[section][0]
    target[field] = value
    with pytest.raises(ResumeValidationError):
        validate_facts(master, tailored, profile)


def test_unsupported_skills_numeric_claims_and_semantic_review(master, profile):
    tailored = copy.deepcopy(master)
    tailored["additional"]["technicalSkills"].append("Kubernetes")
    tailored["workExperience"][0]["description"].append("Increased revenue by 900%.")
    report = validate_facts(master, tailored, profile)
    assert any("Kubernetes" in warning for warning in report.warnings)
    assert any("900%" in warning for warning in report.warnings)
    assert any("Semantic grounding" in warning for warning in report.warnings)


def test_master_must_agree_with_profile(master, profile):
    master["additional"]["technicalSkills"].append("Invented Skill")
    with pytest.raises(ResumeValidationError, match="Master skills"):
        validate_master(master, profile)


@pytest.mark.parametrize("bad", ["not_pdf", "blank", "too_many", "contact", "section", "bullet"])
def test_pdf_gate_rejects_unusable_artifact(bad, master, profile):
    text = pdf_text(master)
    if bad == "not_pdf":
        content = b"<html>error</html>"
    elif bad == "blank":
        content = textual_pdf("")
    elif bad == "too_many":
        content = textual_pdf(text, pages=2)
    elif bad == "contact":
        content = textual_pdf(text.replace("alex@example.test", ""))
    elif bad == "section":
        content = textual_pdf(text.replace("Education", ""))
    else:
        content = textual_pdf(text.replace("Analyzed weather records using SQL.", ""))
    with pytest.raises(ResumeValidationError):
        validate_pdf(content, profile, master)


def test_pdf_readability_and_overflow_warning(master, profile):
    assert not validate_pdf(textual_pdf(pdf_text(master)), profile, master).warnings
    assert validate_pdf(textual_pdf(pdf_text(master), x=700), profile, master).warnings


def test_processing_timeout_reuses_uploaded_master(tmp_path, master, profile, job, match):
    backend = Backend(master)
    backend.processing_status = "processing"
    worker = service(tmp_path, backend, timeout=0.05)
    with pytest.raises(ResumeMatcherError, match="deadline"):
        worker.generate(job, match, profile)
    backend.resumes["master"]["raw_resume"]["processing_status"] = "ready"
    service(tmp_path, backend).generate(job, match, profile)
    assert backend.calls["POST resumes/upload"] == 1


def test_http_errors_redacted_and_ambiguous_tailor_not_retried(
    tmp_path, master, profile, job, match
):
    backend = Backend(master)
    backend.bad_status = ("POST resumes/improve", 503)
    worker = service(tmp_path, backend)
    with pytest.raises(ResumeMatcherError, match="HTTP 503") as error:
        worker.generate(job, match, profile)
    assert "private-token" not in str(error.value)
    backend.bad_status = None
    with pytest.raises(ResumeReconciliationRequired):
        worker.generate(job, match, profile)
    assert backend.calls["POST resumes/improve"] == 1


def test_nonaccepted_match_never_calls_upstream(tmp_path, master, profile, job):
    backend = Backend(master)
    with pytest.raises(ResumeValidationError):
        service(tmp_path, backend).generate(job, MatchResult(fit="weak"), profile)
    assert not backend.calls
