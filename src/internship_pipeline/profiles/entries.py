"""Conservative, source-preserving entry grouping and field extraction."""

from __future__ import annotations

import re
from typing import Any

BULLET = re.compile(r"^[•●▪◦‣*\-–]\s+")
ROLE = re.compile(
    r"\b(?:intern|engineer|developer|analyst|assistant|manager|researcher|"
    r"consultant|designer|coordinator|director|founder|associate|specialist|"
    r"technician|fellow|volunteer|president|lead|tutor|instructor)\b",
    re.I,
)
MONTHS = (
    "January February March April May June July August September October November December"
).split()
MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
DATE = (
    rf"(?:{MONTH}\.?\s+(?:19|20)\d{{2}}|(?:19|20)\d{{2}}[-/](?:0?[1-9]|1[0-2])|"
    r"(?:0?[1-9]|1[0-2])/(?:19|20)\d{2}|(?:19|20)\d{2})"
)
DATE_RANGE = re.compile(rf"({DATE})\s*(?:--?|[–—]|to)\s*({DATE}|Present|Current|Now)\b", re.I)
URL = re.compile(r"https?://[^\s|<>]+", re.I)
DATE_ONLY = re.compile(rf"(?:Expected\s+)?{DATE}", re.I)


def month_date(value: str) -> str | None:
    """Do not invent January when a source supplies only a year."""
    if re.fullmatch(r"(?:19|20)\d{2}[-/]\d{1,2}", value):
        year, month = re.split(r"[-/]", value)
        return f"{year}-{int(month):02}"
    if re.fullmatch(r"\d{1,2}/(?:19|20)\d{2}", value):
        month, year = value.split("/")
        return f"{year}-{int(month):02}"
    match = re.fullmatch(rf"({MONTH})\.?\s+((?:19|20)\d{{2}})", value, re.I)
    if match:
        month = next(
            i for i, name in enumerate(MONTHS, 1) if name[:3].lower() == match[1][:3].lower()
        )
        return f"{match[2]}-{month:02}"
    return None


def entry_start(rows: list[dict[str, str]], index: int, kind: str) -> bool:
    text = rows[index]["text"]
    if BULLET.match(text) or len(text) > 700 or text.endswith((".", "!", "?", ",")):
        return False
    following = [row["text"] for row in rows[index + 1 : index + 4]]
    if kind == "project":
        return bool(following and BULLET.match(following[0]))
    return bool(
        (
            ROLE.search(text)
            or DATE_RANGE.search(text)
            or ("|" in text and following and BULLET.match(following[0]))
            or (following and ROLE.search(following[0]) and not BULLET.match(following[0]))
        )
        and any(BULLET.match(row) for row in following)
    )


def entry_fields(text: str, kind: str) -> dict[str, Any]:
    """Extract fields only from entry headers; bullet dates never become job dates."""
    rows = text.splitlines()
    first_bullet = next((i for i, row in enumerate(rows) if BULLET.match(row)), len(rows))
    headers = rows[:first_bullet]
    if not headers or first_bullet == len(rows):
        return {}
    parts = [part.strip() for row in headers for part in row.split("|") if part.strip()]
    result: dict[str, Any] = {}
    date_match = DATE_RANGE.search(" | ".join(headers))
    if date_match:
        result["start_date"] = month_date(date_match[1])
        result["end_date"] = month_date(date_match[2])
        result["current"] = date_match[2].lower() in {"present", "current", "now"}
        if (
            result["start_date"]
            and result["end_date"]
            and result["start_date"] > result["end_date"]
        ):
            result.pop("start_date")
            result.pop("end_date")
    clean = []
    for part in parts:
        part = DATE_RANGE.sub("", part).strip(" ,;–—-")
        if DATE_ONLY.fullmatch(part):
            if kind == "project" and not date_match:
                result["start_date"] = month_date(part)
            continue
        if part and not URL.fullmatch(part):
            clean.append(part)
    if kind == "experience":
        title = next((part for part in clean if ROLE.search(part)), "")
        # Header position is evidence too: don't require every profession to be
        # in a vocabulary. Only use this for a structured header above bullets.
        if not title and len(clean) >= 2 and date_match:
            title = clean[0]
        if title and len(title) <= 200:
            result["title"] = title
            remaining = [part for part in clean if part != title]
            if remaining and len(remaining[0]) <= 200:
                result["company"] = remaining[0]
            if len(remaining) > 1 and len(remaining[-1]) <= 200:
                result["location"] = remaining[-1]
    elif clean and len(clean[0]) <= 200:
        result["title"] = clean[0]
    if kind == "project":
        skills = [
            skill.strip()
            for part in clean[1:]
            if "," in part or ";" in part
            for skill in re.split(r"[,;]", part)
            if skill.strip()
        ]
        if skills and len(skills) <= 30 and all(len(skill) <= 200 for skill in skills):
            result["skills"] = skills
    links = list(dict.fromkeys(match.rstrip(".,;)") for match in URL.findall(text)))
    if links:
        result["links"] = links[:10]
    # Keep source precision when the form's month fields cannot represent it.
    partial_dates = date_match and (
        not month_date(date_match[1])
        or (not month_date(date_match[2]) and not result.get("current"))
    )
    preserve_headers = (
        partial_dates
        or not result.get("title")
        or (
            kind == "project"
            and any(
                "," not in part
                and ";" not in part
                and part.lower() not in {"github", "demo", "website", "code", "live", "link"}
                for part in clean[1:]
            )
        )
        or (kind == "experience" and len(clean) > 3)
        or (date_match and "start_date" not in result)
    )
    # Rejoin physical wrapping while keeping distinct bullets distinct.
    bullets: list[str] = []
    for row in rows[first_bullet:]:
        if BULLET.match(row) or not bullets:
            bullets.append(row)
        else:
            bullets[-1] += " " + row
    result["text"] = text if preserve_headers else "\n".join(bullets)
    return result


def education_field(degree: str) -> str:
    """Preserve dual fields of study without inventing a degree or a day."""
    from internship_pipeline.profiles.draft import DEGREE

    fields = []
    for part in degree.split(","):
        match = DEGREE.match(part.strip())
        if match:
            value = part.strip()[match.end() :].lstrip(". ").removeprefix("in ").strip()
            if value:
                fields.append(value)
    return ", ".join(fields)[:200]
