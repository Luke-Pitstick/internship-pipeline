from __future__ import annotations

import copy
import gzip
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
from internship_pipeline.resumes.codex import CodexResumeGenerator
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
        self.creations: Counter[str] = Counter()
        self.generation_calls: Counter[str] = Counter()
        self.publications: dict[str, dict[str, Any]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1/")
        signature = f"{request.method} {path}"
        self.calls[signature] += 1
        if self.bad_status and self.bad_status[0] == signature:
            return httpx.Response(self.bad_status[1], json={"detail": "private-token-never-log"})
        if signature == "POST resume-wizard/finalize":
            body = json.loads(request.content)
            assert set(body) == {"state"} and set(body["state"]) == {"resume_data"}
            assert body["state"]["resume_data"] == self.master
            if "master" not in self.resumes:
                self.creations[signature] += 1
            self.resumes["master"] = {
                "resume_id": "master",
                "is_master": True,
                "filename": "AI Resume Wizard - Alex Example.json",
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
        elif signature == "POST resumes/import-tailored":
            body = json.loads(request.content)
            assert set(body) == {"generation_key", "master_id", "job_id", "resume_data", "title"}
            assert len(body["generation_key"]) == 64
            assert body["master_id"] == "master" and body["job_id"] == "remote-job"
            assert body["resume_data"] == self.tailored
            key = body["generation_key"]
            if key not in self.publications:
                self.publications[key] = body
                self.creations[signature] += 1
            else:
                assert self.publications[key] == body
            self.resumes["tailored"] = {
                "resume_id": "tailored",
                "is_master": False,
                "parent_id": "master",
                "processed_resume": self.tailored,
                "raw_resume": {"processing_status": "ready"},
            }
            result = {
                "resume_id": "tailored",
                "job_id": "remote-job",
                "processing_status": "ready",
            }
        elif signature == "GET resumes":
            result = {"data": self.resumes[request.url.params["resume_id"]]}
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


class Generator(CodexResumeGenerator):
    def __init__(self, backend: Backend):
        super().__init__()
        self.backend = backend

    def parse_master(self, path, profile, deadline):
        self.backend.generation_calls["parse"] += 1
        return copy.deepcopy(self.backend.master)

    def tailor(self, master, job, match, profile, deadline):
        self.backend.generation_calls["tailor"] += 1
        return copy.deepcopy(self.backend.tailored)


def service(tmp_path: Path, backend: Backend, timeout: float = 180) -> ResumeService:
    settings = Settings(artifact_dir=tmp_path / "artifacts", generation_timeout_seconds=timeout)
    return ResumeService(
        settings,
        client=ResumeMatcherClient(
            settings.resume_matcher_url, transport=httpx.MockTransport(backend)
        ),
        generator=Generator(backend),
    )


def test_http_sequence_manifest_cache_and_application_state(tmp_path, master, profile, job, match):
    backend = Backend(master)
    worker = service(tmp_path, backend)
    checkpoint: dict[str, object] = {}
    artifact = worker.generate(job, match, profile, checkpoint)
    assert artifact.pdf_path.read_bytes().startswith(b"%PDF-")
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


@pytest.mark.parametrize("stage", ["POST resume-wizard/finalize", "POST resumes/import-tailored"])
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
    assert backend.calls[stage] == 2
    assert backend.creations[stage] == 1
    assert backend.generation_calls["parse"] == 1 and backend.generation_calls["tailor"] == 1
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
    assert backend.calls["POST resume-wizard/finalize"] == 1
    assert backend.calls["POST jobs/upload"] == 1
    assert backend.calls["POST resumes/import-tailored"] == 1
    assert backend.calls["GET resumes/tailored/pdf"] == 3


def test_master_cached_across_jobs(tmp_path, master, profile, job, match):
    backend = Backend(master)
    worker = service(tmp_path, backend)
    worker.generate(job, match, profile)
    worker.generate(job.model_copy(update={"id": "another"}), match, profile)
    assert backend.calls["POST resume-wizard/finalize"] == 1
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


@pytest.mark.parametrize("addition", ["skill", "number", "certification", "language", "award"])
def test_unsupported_explicit_claims_rejected(addition, master, profile):
    tailored = copy.deepcopy(master)
    if addition == "skill":
        tailored["additional"]["technicalSkills"].append("Kubernetes")
    elif addition == "number":
        tailored["workExperience"][0]["description"].append("Increased revenue by 900%.")
    else:
        field = {
            "certification": "certificationsTraining",
            "language": "languages",
            "award": "awards",
        }[addition]
        tailored["additional"][field].append("Unsupported candidate qualification")
    with pytest.raises(ResumeValidationError, match="unsupported"):
        validate_facts(master, tailored, profile)


def test_semantic_rewrite_still_requires_review(master, profile):
    tailored = copy.deepcopy(master)
    tailored["workExperience"][0]["description"] = [
        "Created a Python API used by 12 synthetic users."
    ]
    report = validate_facts(master, tailored, profile)
    assert any("Semantic grounding" in warning for warning in report.warnings)


@pytest.mark.parametrize("addition", ["skill", "number", "certification"])
def test_explicit_unsupported_claim_never_produces_deliverable_artifact(
    addition, tmp_path, master, profile, job, match
):
    backend = Backend(master)
    if addition == "skill":
        backend.tailored["additional"]["technicalSkills"].append("Invented Skill")
    elif addition == "number":
        backend.tailored["summary"] += " Increased revenue by 900%."
    else:
        backend.tailored["additional"]["certificationsTraining"].append("Invented Certification")
    with pytest.raises(ResumeValidationError, match="unsupported"):
        service(tmp_path, backend).generate(job, match, profile)
    assert backend.calls["GET resumes/tailored/pdf"] == 0
    assert not list((tmp_path / "artifacts").glob("*/manifest.json"))


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


@pytest.mark.parametrize(
    "section,stored,printed",
    [
        ("workExperience", "Oct. 2025 – Present", "O ct. 2025 - Present"),
        ("workExperience", "Jun. 2026 – Aug. 2026", "Jun. 2026 - Aug. 2026"),
        ("education", "2024—2028", "2024 - 2028"),
        ("personalProjects", "Apr. 2026 Present", "Apr. 2026 - Present"),
        ("personalProjects", "Jun 2025 Aug 2025", "Jun 2025 - Aug 2025"),
        ("personalProjects", "2023 2025", "2023 - 2025"),
    ],
)
def test_pdf_accepts_exact_renderer_date_format_and_split_month(
    section, stored, printed, master, profile
):
    rendered_data = copy.deepcopy(master)
    rendered_data[section][0]["years"] = printed
    rendered = pdf_text(rendered_data)
    master[section][0]["years"] = stored
    validate_pdf(textual_pdf(rendered), profile, master)


@pytest.mark.parametrize(
    "printed",
    [
        "Nov. 2025 - Present",
        "Oct. 2024 - Present",
        "Oct. 2025 - Current",
        "Oct. 2025",
        "Oct. 2025 - Presently",
        "Oct. 12025 - Present",
    ],
)
def test_pdf_date_format_tolerance_rejects_changed_or_missing_dates(printed, master, profile):
    old = master["workExperience"][0]["years"]
    rendered = pdf_text(master).replace(old, printed)
    master["workExperience"][0]["years"] = "Oct. 2025 – Present"
    with pytest.raises(ResumeValidationError, match="structured factual"):
        validate_pdf(textual_pdf(rendered), profile, master)


def test_pdf_split_month_tolerance_does_not_relax_other_identity_checks(master, profile):
    rendered = pdf_text(master).replace("Example Labs", "E xample Labs")
    with pytest.raises(ResumeValidationError, match="structured factual"):
        validate_pdf(textual_pdf(rendered), profile, master)


def test_processing_timeout_reuses_uploaded_master(tmp_path, master, profile, job, match):
    backend = Backend(master)
    backend.processing_status = "processing"
    worker = service(tmp_path, backend, timeout=0.05)
    with pytest.raises(ResumeMatcherError, match="deadline"):
        worker.generate(job, match, profile)
    backend.resumes["master"]["raw_resume"]["processing_status"] = "ready"
    service(tmp_path, backend).generate(job, match, profile)
    assert backend.calls["POST resume-wizard/finalize"] == 1


def test_http_errors_redacted_and_idempotent_publish_retried(tmp_path, master, profile, job, match):
    backend = Backend(master)
    backend.bad_status = ("POST resumes/import-tailored", 503)
    worker = service(tmp_path, backend)
    with pytest.raises(ResumeMatcherError, match="HTTP 503") as error:
        worker.generate(job, match, profile)
    assert "private-token" not in str(error.value)
    backend.bad_status = None
    worker.generate(job, match, profile)
    assert backend.calls["POST resumes/import-tailored"] == 2
    assert backend.creations["POST resumes/import-tailored"] == 1
    assert backend.generation_calls["tailor"] == 1


def test_nonaccepted_match_never_calls_upstream(tmp_path, master, profile, job):
    backend = Backend(master)
    with pytest.raises(ResumeValidationError):
        service(tmp_path, backend).generate(job, MatchResult(fit="weak"), profile)
    assert not backend.calls


def test_codex_model_identity_changes_invalidate_key(tmp_path, master, profile, job, match):
    backend = Backend(master)
    worker = service(tmp_path, backend)
    first = worker.generation_key(job, match, profile)
    worker.generator.model = "tested-account-model"
    assert worker.generation_key(job, match, profile) != first


def test_subscription_path_does_not_require_upstream_provider_config(
    tmp_path, master, profile, job, match
):
    backend = Backend(master)
    service(tmp_path, backend).generate(job, match, profile)
    assert not any("config/" in key or key.endswith("resumes/improve") for key in backend.calls)


def test_corrupt_manifest_can_be_rebuilt_without_remote_mutations(
    tmp_path, master, profile, job, match
):
    backend = Backend(master)
    worker = service(tmp_path, backend)
    artifact = worker.generate(job, match, profile)
    artifact.pdf_path.with_name("manifest.json").write_text("broken JSON")
    worker.generate(job, match, profile)
    assert backend.calls["POST resumes/import-tailored"] == 1
    assert backend.calls["GET resumes/tailored/pdf"] == 2


def test_ready_remote_master_content_changes_invalidate_key(tmp_path, master, profile, job, match):
    backend = Backend(master)
    worker = service(tmp_path, backend)
    worker.generate(job, match, profile)
    profile.master_resume_id = "master"
    first = worker.generation_key(job, match, profile)
    backend.master["summary"] = "A changed factual master"
    assert worker.generation_key(job, match, profile) != first


def test_protected_number_cannot_match_substring(master, profile):
    tailored = copy.deepcopy(master)
    tailored["workExperience"][0]["description"] = ["Built a Python API serving 120 users."]
    with pytest.raises(ResumeValidationError, match="protected factual"):
        validate_facts(master, tailored, profile)


def test_pdf_uses_upstream_custom_section_headings(master, profile):
    master["sectionMeta"] = [{"key": "education", "displayName": "Academic Background"}]
    text = pdf_text(master).replace("Education", "Academic Background")
    validate_pdf(textual_pdf(text), profile, master)


@pytest.mark.parametrize("invalid", ["name", "skills", "description", "metadata"])
def test_invalid_structured_schema_rejected(invalid, master, profile):
    if invalid == "name":
        master["personalInfo"]["name"] = []
    elif invalid == "skills":
        master["additional"]["technicalSkills"] = "Python"
    elif invalid == "description":
        master["workExperience"][0]["description"] = "a bullet"
    else:
        master["sectionMeta"] = ["not metadata"]
    with pytest.raises(ResumeValidationError):
        validate_master(master, profile)


def test_corrupt_checkpoint_stops_before_creation(tmp_path, master, profile, job, match):
    backend = Backend(master)
    worker = service(tmp_path, backend)
    key = worker.generation_key(job, match, profile)
    path = worker.checkpoints / f"{key}.json"
    path.parent.mkdir(parents=True)
    path.write_text("broken JSON")
    with pytest.raises(ResumeReconciliationRequired):
        worker.generate(job, match, profile)
    assert not any(key.startswith("POST") for key in backend.calls)


def test_unsupported_match_fact_never_calls_upstream(tmp_path, master, profile, job, match):
    backend = Backend(master)
    match.fact_ids = ["invented-fact-id"]
    with pytest.raises(ResumeValidationError, match="unsupported factual"):
        service(tmp_path, backend).generate(job, match, profile)
    assert not backend.calls


def test_client_malformed_write_and_content_type_are_rejected():
    client = ResumeMatcherClient(
        "http://example.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=b"not JSON", headers={"content-type": "text/html"}
            )
        ),
    )
    with pytest.raises(ResumeMatcherError) as error:
        client.upload_job("synthetic job", "master")
    assert error.value.ambiguous is True
    with pytest.raises(ResumeMatcherError, match="non-PDF"):
        client.download_pdf("tailored", "swiss-single")


@pytest.mark.parametrize("content_type", ["application/json", "application/pdf"])
def test_streamed_gzip_response_is_decoded_once_and_has_decoded_length(content_type):
    data = {"data": {"resume_id": "master", "content": "Synthetic resume content " * 500}}
    decoded = (
        json.dumps(data).encode()
        if content_type == "application/json"
        else textual_pdf("Synthetic PDF content")
    )
    compressed = gzip.compress(decoded)

    class CompressedStream(httpx.SyncByteStream):
        def __iter__(self):
            # The transport delivers compressed bytes in chunks, as the Next proxy does.
            for start in range(0, len(compressed), 11):
                yield compressed[start : start + 11]

    client = ResumeMatcherClient(
        "http://example.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                stream=CompressedStream(),
                headers={
                    "Content-Type": content_type,
                    "Content-Encoding": "gzip",
                    "Content-Length": str(len(compressed)),
                    "X-Synthetic": "preserved",
                },
            )
        ),
    )
    try:
        response = client._request("GET", "resumes")
        assert response.content == decoded
        assert "content-encoding" not in response.headers
        assert response.headers["content-length"] == str(len(decoded))
        assert response.headers["x-synthetic"] == "preserved"
        if content_type == "application/json":
            assert client.get_resume("master") == data["data"]
        else:
            assert client.download_pdf("tailored", "swiss-single") == decoded
    finally:
        client.close()
