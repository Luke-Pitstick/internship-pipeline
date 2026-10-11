"""Internship discovery scope, independent of candidate eligibility and model scoring."""

import html
import re

_ROLE = re.compile(r"\b(?:intern(?:ship)?s?|co[\s\-‐‑–]?ops?)\b", re.I)
_NON_ROLE = re.compile(
    r"\bnon[\s-]?intern(?:ship)?\b|"
    r"\b(?:intern(?:ship)?s?|co[\s-]?op)\s+(?:program(?:me)?\s+)?"
    r"(?:coordinator|recruiter|director|supervisor|mentor|manager)\b",
    re.I,
)
_DENIAL = re.compile(
    r"\bthis\s+(?:(?:role|position|job|opportunity)\s+)?is\s+not\s+an?\s+"
    r"(?:internship|co[\s-]?op)\b",
    re.I,
)
_OWN_ROLE = re.compile(
    r"\bthis\s+(?:(?:role|position|job|opportunity)\s+)?is\s+an?\s+"
    r"(?:(?:paid|unpaid|summer|seasonal|full[\s-]time|part[\s-]time)\s+)*"
    r"(?:internship|co[\s-]?op)\b|"
    r"\b(?:job|position|employment)\s+(?:type|level)\s*:?\s*"
    r"(?:internship|co[\s-]?op)\b|"
    r"\bwe\s+(?:are\s+)?(?:seek(?:ing)?|(?:are\s+)?looking\s+for|(?:are\s+)?hiring)\s+"
    r"(?:(?:an?|a|paid|unpaid|summer|software|engineering|data|science|product|management)\s+)*"
    r"interns?\b",
    re.I,
)


def is_internship(title: str, description: str | None = None) -> bool:
    """Require evidence about this opening, not previous experience or a search label."""
    text = " ".join(re.sub(r"<[^>]*>", " ", html.unescape(description or "")).split())
    text = text.replace("**", "")
    if _NON_ROLE.search(title) or _DENIAL.search(text):
        return False
    if _ROLE.search(title) or _OWN_ROLE.search(text):
        return True
    # Finance/research summer placements often use analyst/associate titles.
    return bool(
        re.search(r"\bsummer\s+(?:analyst|associate)\b", title, re.I)
        and re.search(r"\binternship\s+program(?:me)?\b", text, re.I)
    )
