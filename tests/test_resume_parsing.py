"""Realistic synthetic layouts through extraction, field filling and saved evidence."""

import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from test_resume_import import docx_bytes, reviewed

from internship_pipeline.profiles.extract import extract
from internship_pipeline.profiles.imports import ResumeImports
from internship_pipeline.storage import Store

TEX = r"""\documentclass{article}
\newcommand{\resumeSubheading}[4]{\textbf{#1} #2 #3 #4}
\newcommand{\resumeItem}[1]{\item #1}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}}
% \begin{document} is a comment, not the start of the resume.
\begin{document}
{\fontsize{20}{24}\selectfont Synthetic Candidate}\\
\href{mailto:synthetic@example.test}{synthetic@example.test}
\section*{EDUCATION}
\resumeSubheading{Example University}{Aug 2023 -- May 2027}
 {B.S. in Computer Science}{Boulder, CO}
\section{TECHNICAL SKILLS}
\textbf{Languages:} Python, SQL,\\
 C++, TypeScript\\
\textbf{Tools:} Git, Docker
\section{PROFESSIONAL EXPERIENCE}
\resumeSubheading{Example Labs}{June 2025 -- August 2025}
 {Software Engineering Intern}{Remote}
\resumeItemListStart
\resumeItem{Built an API using Python and PostgreSQL,
 reducing request latency by 35\%.}
\resumeItem{Shipped a dashboard with React.}
\resumeItemListEnd
\section{SELECTED PROJECTS}
\textbf{Weather Dashboard}\\
\resumeItem{Created a public forecast dashboard.}
\section{Interests}
Hiking, pottery
\end{document}
"""

ROWS = [
    "Synthetic Candidate",
    "synthetic@example.test",
    "EDUCATION",
    "Example University | Aug 2023 - May 2027",
    "B.S. in Computer Science | Boulder, CO",
    "TECHNICAL SKILLS",
    "Languages: Python, SQL,",
    "C++, TypeScript",
    "Tools: Git, Docker",
    "PROFESSIONAL EXPERIENCE",
    "Example Labs | June 2025 - August 2025",
    "Software Engineering Intern | Remote",
    "* Built an API using Python and PostgreSQL,",
    "reducing request latency by 35%.",
    "* Shipped a dashboard with React.",
    "SELECTED PROJECTS",
    "Weather Dashboard",
    "* Created a public forecast dashboard.",
    "Interests",
    "Hiking, pottery",
]


def layout_pdf() -> bytes:
    """Paint rows in reverse order, with independently positioned date/location columns."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    operations = []
    for index, row in reversed(list(enumerate(ROWS))):
        for column, text in reversed(list(enumerate(row.split(" | ")))):
            operations.append(
                f"BT /F1 10 Tf 1 0 0 1 {50 if column == 0 else 400} "
                f"{750 - index * 18} Tm ({text}) Tj ET"
            )
    stream = DecodedStreamObject()
    stream.set_data("\n".join(operations).encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize("kind", ["pdf", "docx", "tex"])
def test_realistic_resume_fills_all_sections_and_saves_literal_evidence(tmp_path, kind):
    data = {"pdf": layout_pdf, "docx": lambda: docx_bytes(ROWS), "tex": lambda: TEX.encode()}[
        kind
    ]()
    imports = ResumeImports(Store(tmp_path / "state.sqlite3"))
    draft = imports.upload(data, kind, 0)
    filled, evidence = imports.prepare(draft["id"], reviewed(draft))
    assert imports.settings.read().revision == 0
    profile = filled.profile
    assert profile.name == "Synthetic Candidate"
    assert profile.email == "synthetic@example.test"
    assert len(profile.education) == 1
    assert profile.education[0].institution == "Example University"
    assert profile.education[0].degree == "B.S. in Computer Science"
    assert profile.education[0].graduation_date is None
    assert {skill for fact in profile.facts for skill in fact.skills} == {
        "Python",
        "SQL",
        "C++",
        "TypeScript",
        "Git",
        "Docker",
    }
    experience = [fact.text for fact in profile.facts if fact.kind == "experience"]
    api = next(text for text in experience if "Built an API" in text)
    assert "reducing request latency by 35%." in api
    assert len([text for text in experience if "Shipped a dashboard" in text]) == 1
    assert any(
        "Created a public forecast dashboard." in fact.text
        for fact in profile.facts
        if fact.kind == "project"
    )
    assert not any("Hiking" in fact.text or "pottery" in fact.text for fact in profile.facts)
    for item in evidence:
        if isinstance(item["value"], dict) and "text" in item["value"]:
            assert item["value"]["text"] in item["source_text"]
    imports.confirm(draft["id"], reviewed(draft))
    assert imports.settings.read().profile == profile
    assert imports.current()["import"]["evidence"] == evidence
    assert imports.template() == (TEX if kind == "tex" else None)


@pytest.mark.parametrize(
    "rows",
    [
        ["Education", "Example University | Bachelor of Arts in Economics"],
        ["Education", "Bachelor of Arts in Economics", "Example University"],
        ["Education", "Example University Bachelor of Arts in Economics"],
        ["Academic Background:", "Example University", "B.A. in Economics"],
    ],
)
def test_education_row_orders_and_inline_degrees(tmp_path, rows):
    imports = ResumeImports(Store(tmp_path / "state.sqlite3"))
    draft = imports.upload(docx_bytes(["Synthetic Candidate", *rows]), "docx", 0)
    filled, _ = imports.prepare(draft["id"], reviewed(draft))
    assert len(filled.profile.education) == 1
    assert filled.profile.education[0].institution == "Example University"
    assert "Economics" in filled.profile.education[0].degree


def test_tex_macro_definitions_cannot_read_files_or_execute(tmp_path):
    private = tmp_path / "secret.tex"
    private.write_text("private-candidate-marker")
    marker = tmp_path / "executed"
    source = TEX.replace(
        r"\begin{document}",
        rf"\newcommand{{\steal}}[1]{{\input{{{private}}}\write18{{touch {marker}}}}}"
        + "\n"
        + r"\begin{document}",
    ).replace(
        r"\section{Interests}",
        rf"\steal{{visible argument}}\input{{{private}}}" + "\n" + r"\section{Interests}",
    )
    text = "\n".join(line["text"] for line in extract(source.encode(), "tex"))
    assert "private-candidate-marker" not in text
    assert "visible argument" in text
    assert not marker.exists()


def test_contact_row_inline_skills_and_multiple_education_entries(tmp_path):
    rows = [
        "Synthetic Candidate | synthetic@example.test",
        "Education",
        "Example University",
        "M.S. in Computing",
        "Another College | B.A. in Economics",
        "Technical Skills: Python; SQL; C++",
        "Additional Information",
        "Hiking, pottery",
    ]
    imports = ResumeImports(Store(tmp_path / "state.sqlite3"))
    draft = imports.upload(docx_bytes(rows), "docx", 0)
    profile, _ = imports.prepare(draft["id"], reviewed(draft))
    assert profile.profile.name == "Synthetic Candidate"
    assert profile.profile.email == "synthetic@example.test"
    assert [entry.institution for entry in profile.profile.education] == [
        "Example University",
        "Another College",
    ]
    assert len(profile.profile.facts) == 1
    assert profile.profile.facts[0].skills == ["Python", "SQL", "C++"]


def test_tex_optional_macro_arguments_and_multiline_heading():
    source = r"""\documentclass{article}
\newcommand{\skillrow}[2][]{#2}
\begin{document}
Synthetic Candidate
\section*{
Programming Languages}
\skillrow{Python, SQL}
\end{document}
"""
    lines = extract(source.encode(), "tex")
    assert [line["text"] for line in lines] == [
        "Synthetic Candidate",
        "Programming Languages",
        "Python, SQL",
    ]
