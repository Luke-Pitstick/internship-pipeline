from __future__ import annotations

import copy
import gzip
import io
import json
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
    SourceJob,
    utcnow,
)
from internship_pipeline.resumes.client import (
    ResumeMatcherClient,
    ResumeMatcherError,
)
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
