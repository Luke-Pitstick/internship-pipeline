"""Readable, bounded PDF validation shared by application-owned templates."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

from pypdf import PdfReader

from internship_pipeline.models import CandidateProfile


class ResumeValidationError(ValueError):
    """The artifact is unsafe to deliver as a usable tailored resume."""


@dataclass
class ValidationReport:
    warnings: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)


def normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def contains_value(text: str, value: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(normalized(value)) + r"(?!\w)", text))


def validate_pdf(content: bytes, profile: CandidateProfile) -> ValidationReport:
    if not content.startswith(b"%PDF-"):
        raise ResumeValidationError("Download is not a PDF")
    report = ValidationReport()
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise ResumeValidationError("Encrypted resume PDF")
        if not 1 <= len(reader.pages) <= profile.max_resume_pages:
            raise ResumeValidationError("Resume PDF exceeds the allowed page count")
        texts: list[str] = []
        for page in reader.pages:
            bounds = page.mediabox

            def visit(
                text: str,
                cm: list[float],
                tm: list[float],
                font: Any,
                size: float,
                rectangle: Any = bounds,
            ) -> None:
                x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                if text.strip() and not (
                    float(rectangle.left) - 2 <= x <= float(rectangle.right) + 2
                    and float(rectangle.bottom) - 2 <= y <= float(rectangle.top) + 2
                ):
                    report.warnings.append("Text origin outside the page requires visual review")

            text = page.extract_text(visitor_text=visit) or ""
            if len(text.strip()) < 20:
                raise ResumeValidationError("Blank or unreadable resume PDF page")
            texts.append(text)
    except ResumeValidationError:
        raise
    except Exception as exc:
        raise ResumeValidationError("Malformed or unreadable resume PDF") from exc
    text = normalized("\n".join(texts))
    if len(text) < 80:
        raise ResumeValidationError("Insufficient readable resume PDF text")
    for value in (profile.name, profile.email, *profile.protected_values):
        if value and not contains_value(text, value):
            raise ResumeValidationError("PDF is missing contact or protected factual text")
    report.warnings = list(dict.fromkeys(report.warnings))
    return report
