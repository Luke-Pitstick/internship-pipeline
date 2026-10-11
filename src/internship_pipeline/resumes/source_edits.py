"""Apply grounded model edits to a copy of the owner's original TeX template."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from internship_pipeline.profiles.extract import tex_source
from internship_pipeline.resumes.master_template import escape


class SourceEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    old: str = Field(min_length=1, max_length=100_000)
    new: str = Field(max_length=100_000)


class SourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_ids: list[str] = Field(min_length=1, max_length=100)
    edits: list[SourceEdit] = Field(max_length=100)


def apply_edits(source: str, edits: list[SourceEdit], facts: list[dict[str, str]]) -> str:
    """Only whole body blocks can move; new claims and executable tokens cannot be invented."""
    preamble, marker, remainder = source.partition(r"\begin{document}")
    body, end, trailer = remainder.rpartition(r"\end{document}")
    allowed_facts = {escape(f["text"]) + "\n" for f in facts}
    spans: list[tuple[int, int, str]] = []

    def whole_block(block: str) -> bool:
        index = body.find(block)
        return bool(
            block
            and block.endswith("\n")
            and index >= 0
            and (index == 0 or body[index - 1] == "\n")
        )

    for edit in edits:
        if not whole_block(edit.old) or body.count(edit.old) != 1:
            raise ValueError("Each edit must identify one unique complete source block.")
        if edit.new and edit.new not in allowed_facts and not whole_block(edit.new):
            raise ValueError("Replacement must reuse source blocks or a confirmed fact verbatim.")
        start = body.index(edit.old)
        stop = start + len(edit.old)
        if any(start < other_stop and other_start < stop for other_start, other_stop, _ in spans):
            raise ValueError("Source edits overlap.")
        spans.append((start, stop, edit.new))
    for start, stop, replacement in sorted(spans, reverse=True):
        body = body[:start] + replacement + body[stop:]
    return tex_source((preamble + marker + body + end + trailer).encode())
