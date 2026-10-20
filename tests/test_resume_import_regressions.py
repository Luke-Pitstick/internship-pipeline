"""Field-level regressions for real-world template shapes, using synthetic facts."""

import asyncio
import io
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.annotations import Link
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from test_resume_document_model import DOCUMENT, KEY, Connections, config, response
from test_resume_import import docx_bytes, reviewed

from internship_pipeline.profiles import document_model, model_document
from internship_pipeline.profiles.extract import DocumentError
from internship_pipeline.profiles.imports import ResumeImports, build_resume_import_router
from internship_pipeline.storage import Store

TEX = r"""
\documentclass{article}
\newcommand{\resumeSubheading}[4]{#1 #2 #3 #4}
\newcommand{\resumeItem}[1]{\item #1}
\newcommand{\resumeProjectHeading}[2]{#1 #2}
\begin{document}
Synthetic Candidate\\
synthetic@example.test
\section{Education}
\resumeSubheading{Example University}{Expected May 2028}
{B.A. Computer Science, B.A. Political Science}{Example City}
\section{Technical Experience}
\resumeSubheading{Junior Data Manager}{Oct. 2025 -- Present}{Coastal Laboratory}{Remote}
\resumeItem{Processed \textbf{10+ TB/week} of data with Python and SQL.}
\resumeItem{Resolved metadata issues.}
\resumeSubheading{AI/ML Engineer Intern}{Jun. 2026 -- Aug. 2026}{Grid Research}{Remote}
\resumeItem{Built simulations with Redis.}
\resumeSubheading{Data Science Intern}{Aug. 2025 -- Dec. 2025}{Civic Research}{Remote}
\resumeItem{Built demographic maps with R.}
\section{Projects}
\resumeProjectHeading{\textbf{Road Survey} $|$ \emph{Python, PyTorch} $|$
\href{https://example.test/road}{GitHub}}{Apr. 2026 -- Present}
\resumeItem{Trained models with \textbf{80\% precision}.}
\resumeProjectHeading{\textbf{Wind Siting} $|$ \emph{Python, React} $|$
\href{https://example.test/wind}{Demo}}{Apr. 2026}
\resumeItem{Built a renewable energy dashboard.}
\section{Leadership Experience}
\resumeSubheading{Representative-at-Large \& Press Secretary}{May 2025 -- May 2026}
{Example Student Government}{Example City}
\resumeItem{Reviewed a \textbf{\$36M} budget.}
\resumeItem{Led a 6-person team.}
\section{Technical Skills}
\begin{itemize}\item
Languages: Python, SQL, R\\
Libraries: PyTorch, React\\
Tools: Redis
\end{itemize}
\end{document}
"""


def test_custom_tex_template_keeps_all_roles_projects_skills_and_evidence(tmp_path):
    service = ResumeImports(Store(tmp_path / "state.db"))
    draft = service.upload(TEX.encode(), "tex", 0)
    filled, _ = service.prepare(draft["id"], reviewed(draft))
    jobs = [f for f in filled.profile.facts if f.kind == "experience"]
    projects = [f for f in filled.profile.facts if f.kind == "project"]
    assert [f.title for f in jobs] == [
        "Junior Data Manager",
        "AI/ML Engineer Intern",
        "Data Science Intern",
        "Representative-at-Large & Press Secretary",
    ]
    assert jobs[0].company == "Coastal Laboratory"
    assert jobs[0].skills == ["Python", "SQL"]
    assert jobs[0].start_date == "2025-10" and jobs[0].current
    assert jobs[1].end_date == "2026-08"
    assert jobs[-1].company == "Example Student Government"
    assert jobs[-1].text == "• Reviewed a $36M budget.\n• Led a 6-person team."
    assert [f.title for f in projects] == ["Road Survey", "Wind Siting"]
    assert projects[0].links == ["https://example.test/road"]
    assert projects[0].skills == ["Python", "PyTorch"]
    assert projects[1].links == ["https://example.test/wind"]
    assert projects[1].start_date == "2026-04" and not projects[1].current
    assert projects[0].text == "• Trained models with 80% precision."
    assert {s for f in filled.profile.facts for s in f.skills} == {
        "Python",
        "SQL",
        "R",
        "PyTorch",
        "React",
        "Redis",
    }
    assert filled.profile.education[0].field == "Computer Science, Political Science"
    assert filled.profile.education[0].graduation_date is None  # No invented day.
    service.confirm(draft["id"], reviewed(draft))
    assert service.settings.read().profile == filled.profile
    assert service.template() == TEX


def styled_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    fonts = {
        NameObject(name): DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject(font),
            }
        )
        for name, font in [("/F1", "/Helvetica"), ("/F2", "/Helvetica-Bold")]
    }
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject(fonts)}
    )
    rows = [
        (50, 750, "Synthetic Candidate"),
        (50, 730, "Technical Experience"),
        (50, 710, "Press Secretary"),
        (400, 710, "May 2025 - Present"),
        (50, 690, "Example Government"),
        (400, 690, "Remote"),
        (50, 650, "Projects"),
        (50, 630, "Road Survey | Python, SQL | GitHub"),
        (400, 630, "Apr. 2026"),
        (50, 610, "* Built a survey service."),
    ]
    operations = [f"BT /F1 10 Tf 1 0 0 1 {x} {y} Tm ({text}) Tj ET" for x, y, text in rows]
    # Change fonts within a single physical line; spaces are PDF positioning.
    operations.append(
        "BT /F1 10 Tf 1 0 0 1 50 670 Tm (* Processed ) Tj "
        "/F2 10 Tf (10+ TB/week) Tj /F1 10 Tf ( of data.) Tj ET"
    )
    stream = DecodedStreamObject()
    stream.set_data("\n".join(reversed(operations)).encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_annotation(0, Link(rect=(180, 627, 215, 642), url="https://example.test/road"))
    data = io.BytesIO()
    writer.write(data)
    return data.getvalue()


def test_pdf_style_changes_geometry_and_annotation_links(tmp_path):
    service = ResumeImports(Store(tmp_path / "state.db"))
    draft = service.upload(styled_pdf(), "pdf", 0)
    filled, _ = service.prepare(draft["id"], reviewed(draft))
    job, project = filled.profile.facts
    assert job.title == "Press Secretary" and job.company == "Example Government"
    assert job.location == "Remote" and job.current
    assert job.text == "* Processed 10+ TB/week of data."
    assert project.links == ["https://example.test/road"]
    assert project.skills == ["Python", "SQL"]
    assert project.start_date == "2026-04"


@pytest.mark.parametrize(
    ("degree", "field", "expected_field"),
    [
        ("B.A.", "Public Policy", "Public Policy"),
        (
            "B.A. Computer Science, B.A. Political Science",
            "",
            "Computer Science, Political Science",
        ),
    ],
)
def test_ai_keeps_unfamiliar_title_without_heuristic_reclassification(
    tmp_path, degree, field, expected_field
):
    document = json.loads(json.dumps(DOCUMENT))
    document["entries"][0].update(title="Ombudsperson", start="", end="", bullets=[])
    document["education"] = [
        {
            "page": 1,
            "institution": "Example University",
            "degree": degree,
            "field": field,
            "graduation": "May 2028",
        }
    ]
    lines = model_document.source_lines(document, 1, KEY)
    service = ResumeImports(Store(tmp_path / "state.db"))
    draft = service.upload(b"%PDF-test", "pdf", 0, extracted=lines)
    filled, _ = service.prepare(draft["id"], reviewed(draft))
    assert filled.profile.facts[0].title == "Ombudsperson"
    assert filled.profile.facts[0].company == "Example Labs"
    assert filled.profile.education[0].field == expected_field
    tampered = reviewed(draft)
    tampered.selections[2].kind = "project"
    with pytest.raises(DocumentError):
        service.prepare(draft["id"], tampered)
    service.confirm(draft["id"], reviewed(draft))


def test_text_ai_transmits_only_extracted_text_and_rejects_invented_facts(tmp_path, monkeypatch):
    document = json.loads(json.dumps(DOCUMENT))
    source = [
        "Synthetic Candidate",
        "synthetic@example.test",
        "Technical Experience",
        "Software Engineer | Example Labs | Remote | June 2024 - Present",
        "* Built a reporting service.",
        "Skills",
        "Python, SQL",
    ]
    original = document_model.read_document
    calls = []

    async def read(*args):
        def respond(request):
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "id": "text-model",
                                "supported_parameters": ["temperature"],
                                "reasoning": {
                                    "mandatory": False,
                                    "supported_efforts": ["none", "high"],
                                },
                            }
                        ]
                    },
                )
            body = json.loads(request.content)
            calls.append(body)
            assert body["max_tokens"] == 8192
            assert body["reasoning"] == {"effort": "none"}
            assert body["temperature"] == 0
            assert "file-parser" not in json.dumps(body)
            assert "Built a reporting service." in body["messages"][1]["content"]
            return httpx.Response(200, json=response("openrouter", document))

        return await original(*args, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(document_model, "read_document", read)
    store = Store(tmp_path / "state.db")
    app = FastAPI()
    app.include_router(
        build_resume_import_router(
            store, lambda: None, Connections(config("openrouter", "text-model"))
        )
    )
    with TestClient(app) as client:
        url = "/api/resume-imports/upload?format=docx&expected_revision=0&use_model=true"
        result = client.post(url, content=docx_bytes(source))
        assert result.status_code == 200, result.text
        assert result.json()["method"] == "ai_text"
        document["entries"][0]["bullets"] = ["Invented a billion dollars in revenue."]
        rejected = client.post(url, content=docx_bytes(source))
        assert rejected.status_code == 200
        assert rejected.json()["method"] == "local" and rejected.json()["warnings"]
        document["entries"] = []
        omitted = client.post(url, content=docx_bytes(source))
        assert omitted.status_code == 200
        assert omitted.json()["method"] == "local"
        assert "omitted an entry" in " ".join(omitted.json()["warnings"])
        assert len(calls) == 3


def test_grounding_accepts_explicit_dual_degrees_but_rejects_an_invented_field():
    document = json.loads(json.dumps(DOCUMENT))
    document.update(name="", email="", entries=[], skills=[])
    document["education"] = [
        {
            "page": 1,
            "institution": "Example University",
            "degree": "B.A. Computer Science, B.A. Political Science",
            "field": "Computer Science, Political Science",
            "graduation": "May 2028",
        }
    ]
    original = json.dumps(
        [{"text": "Example University | B.A. Computer Science, B.A. Political Science | May 2028"}]
    )
    assert model_document.source_lines(document, 1, KEY, original=original)
    document["education"][0]["field"] = "Medicine"
    with pytest.raises(ValueError, match="not in the source"):
        model_document.source_lines(document, 1, KEY, original=original)


def test_portable_model_schema_has_typed_fields_and_runtime_bounds():
    schema = model_document.schema()
    assert "title" in schema["$defs"]["ModelEntry"]["properties"]
    assert schema["$defs"]["ModelEntry"]["additionalProperties"] is False
    assert "maxLength" not in json.dumps(schema)
    bad = {**DOCUMENT, "name": "x" * 201}
    with pytest.raises(ValueError):
        model_document.source_lines(bad, 1, KEY)


@pytest.mark.parametrize("model", ["gpt-5.4", "gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna"])
def test_documented_current_openai_models_can_read_documents(model):
    assert asyncio.run(document_model.connection(Connections(config(model=model))))
