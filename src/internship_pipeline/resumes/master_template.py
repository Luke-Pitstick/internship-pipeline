"""One owned master template: literal confirmed facts, without model rewriting."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from internship_pipeline.profile_settings import Snapshot
from internship_pipeline.resumes.validation import ResumeValidationError

TEMPLATE_VERSION = "master-v1"
MAX_PAGES = 2
TEMPLATE = r"""\documentclass[11pt,letterpaper]{article}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage{textcomp}
\usepackage[margin=0.72in]{geometry}
\usepackage{enumitem}
\usepackage{needspace}
\input{glyphtounicode}
\pdfgentounicode=1
\pagestyle{plain}
\setlength{\parindent}{0pt}
\setlength{\parskip}{5pt}
\setlength{\emergencystretch}{1em}
\hyphenpenalty=10000
\exhyphenpenalty=10000
\newcommand{\resumesection}[1]{\Needspace{4\baselineskip}\vspace{9pt}
{\large\bfseries #1}\par\vspace{2pt}\hrule\vspace{5pt}}
\begin{document}
__BODY__
\end{document}
"""
TEMPLATE_REVISION = TEMPLATE_VERSION + ":" + hashlib.sha256(TEMPLATE.encode()).hexdigest()[:16]
ESCAPES = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "%": r"\%",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "<": r"\textless{}",
    ">": r"\textgreater{}",
    "'": r"\textquotesingle{}",
    '"': r"\textquotedbl{}",
    "`": r"\textasciigrave{}",
    "-": "{-}",
    "–": r"\textendash{}",
    "—": r"\textemdash{}",
    "‘": r"\textquoteleft{}",
    "’": r"\textquoteright{}",
    "“": r"\textquotedblleft{}",
    "”": r"\textquotedblright{}",
    "•": r"\textbullet{}",
    "…": r"\textellipsis{}",
}


def plain(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def escape(value: str) -> str:
    """Escape once, per character; user strings can never introduce TeX tokens."""
    value = plain(value)
    if any(
        not (32 <= ord(c) <= 126 or c in ESCAPES or (0xC0 <= ord(c) <= 0xFF and c.isalpha()))
        for c in value
    ):
        raise ResumeValidationError(
            "This template supports Latin letters and common punctuation. "
            "A saved field contains an unsupported character; revise it before rendering."
        )
    return "".join(ESCAPES.get(char, char) for char in value)


@dataclass(frozen=True)
class MasterDocument:
    source: str
    manifest: dict[str, Any]
    required_text: list[str]
    omitted_unknown: int


def render_master(snapshot: Snapshot) -> MasterDocument:
    profile = snapshot.profile
    if snapshot.revision <= 0:
        raise ResumeValidationError("Save your profile before generating a master résumé.")
    if not plain(profile.name):
        raise ResumeValidationError("Add your name in Profile and save before generating.")
    facts = [fact for fact in profile.facts if fact.status == "confirmed"]
    education = [row for row in profile.education if row.status == "confirmed"]
    if not facts and not education:
        raise ResumeValidationError("Confirm at least one fact or education entry, then save.")
    required = [plain(profile.name)]
    body = [r"{\LARGE\bfseries " + escape(profile.name) + r"}\par"]
    if profile.email:
        required.append(plain(profile.email))
        body.append(escape(profile.email) + r"\par")
    if education:
        body.append(r"\resumesection{Education}")
        for entry in education:
            values = [entry.institution, entry.degree, entry.field]
            if entry.graduation_date:
                values.append(entry.graduation_date.isoformat())
            values = [plain(value) for value in values if value]
            required.extend(values)
            body.append(r"\Needspace{3\baselineskip}{\bfseries " + escape(values[0]) + r"}\par")
            body.append(" | ".join(escape(value) for value in values[1:]) + r"\par")
    for kind, heading in (
        ("experience", "Experience"),
        ("project", "Projects"),
        ("skill", "Skills and qualifications"),
    ):
        selected = [fact for fact in facts if fact.kind == kind]
        if not selected:
            continue
        body.extend(
            [
                r"\resumesection{" + heading + "}",
                r"\begin{itemize}[leftmargin=1.25em,itemsep=4pt,topsep=2pt,parsep=0pt]",
            ]
        )
        for fact in selected:
            required.append(plain(fact.text))
            body.append(r"\item " + escape(fact.text))
        body.append(r"\end{itemize}")
    skills: dict[str, list[str]] = {}
    for fact in facts:
        for skill in fact.skills:
            skills.setdefault(plain(skill), []).append(fact.id)
    if skills:
        required.extend(skills)
        body.extend(
            [
                r"\resumesection{Technical skills}",
                ", ".join(escape(skill) for skill in skills) + r"\par",
            ]
        )
    omitted = [f.id for f in profile.facts if f.status != "confirmed"]
    omitted += [e.id for e in profile.education if e.status != "confirmed"]
    manifest: dict[str, Any] = {
        "profile_revision": snapshot.revision,
        "profile_saved_at": snapshot.saved_at,
        "template_revision": TEMPLATE_REVISION,
        "max_pages": MAX_PAGES,
        "contact": {"name": profile.name, "email": profile.email},
        "facts": [fact.model_dump(mode="json") for fact in facts],
        "education": [entry.model_dump(mode="json") for entry in education],
        "skills_provenance": skills,
        "omitted_unknown_ids": omitted,
    }
    return MasterDocument(
        TEMPLATE.replace("__BODY__", "\n".join(body)), manifest, required, len(omitted)
    )


def comparable(value: str) -> str:
    """Ignore layout whitespace and font ligatures, retaining every factual character."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))
