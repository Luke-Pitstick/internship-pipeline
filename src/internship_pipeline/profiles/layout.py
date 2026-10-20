"""Recover PDF columns from physical cell positions, preserving table rows."""

import json

from internship_pipeline.profiles.draft import heading
from internship_pipeline.profiles.extract import LIGATURES, DocumentError


def reading_order(lines: list[dict[str, str]]) -> list[dict[str, str]]:
    pages: dict[str, list[dict[str, str]]] = {}
    for line in lines:
        pages.setdefault(line["location"], []).append(line)
    result: list[dict[str, str]] = []
    for rows in pages.values():
        cells = [json.loads(row["layout"]) for row in rows]
        headings = [
            (i, cell)
            for i, group in enumerate(cells)
            for cell in group
            if heading(cell["text"]) is not None
        ]
        # Dates on the right of job headers do not establish an independent column.
        left = min((cell["x0"] for _, cell in headings), default=0)
        right = [cell["x0"] for _, cell in headings if cell["x0"] - left > 100]
        cut = min(right) - 3 if right else None
        first = min((i for i, _ in headings), default=0)
        if cut is None or any(
            cell["x0"] < cut < cell["x1"] for group in cells[first:] for cell in group
        ):
            result.extend(rows)
            continue
        result.extend(rows[:first])
        for side in (True, False):
            for row, group in zip(rows[first:], cells[first:], strict=True):
                text = " | ".join(cell["text"] for cell in group if (cell["x0"] < cut) == side)
                if text:
                    result.append({"location": row["location"], "text": text})
    if len(result) > 500:
        raise DocumentError("Use a resume with at most 500 text lines.")
    return [
        {
            "id": str(i),
            "location": row["location"],
            "text": " ".join(row["text"].replace("\u00ad", "").split()).translate(LIGATURES),
        }
        for i, row in enumerate(result)
    ]
