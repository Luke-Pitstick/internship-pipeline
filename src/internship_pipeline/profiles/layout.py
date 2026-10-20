"""Recover independent PDF columns only when section headings establish a gutter."""

import re
from collections import Counter

from internship_pipeline.profiles.draft import heading
from internship_pipeline.profiles.extract import LIGATURES, DocumentError


def reading_order(lines: list[dict[str, str]]) -> list[dict[str, str]]:
    pages: dict[str, list[dict[str, str]]] = {}
    for line in lines:
        pages.setdefault(line["location"], []).append(line)
    result: list[dict[str, str]] = []
    for rows in pages.values():
        starts: Counter[int] = Counter()
        section_rows = []
        left_heading = False
        for index, row in enumerate(rows):
            raw = row.get("layout", "")
            for match in re.finditer(r"\S.*?(?= {3,}|$)", raw):
                if heading(match.group()) is not None:
                    section_rows.append(index)
                    if match.start() == 0:
                        left_heading = True
                    else:
                        starts[match.start()] += 1
        if not starts or not left_heading:
            result.extend(rows)
            continue
        cut = starts.most_common(1)[0][0]
        first = min(section_rows)
        region = rows[first:]
        # Never split a continuous sentence, a full-width block or a table whose
        # cells do not line up with the section-defined column boundary.
        if any(
            len(row.get("layout", "").rstrip()) > cut
            and row["layout"][max(0, cut - 2) : cut].strip()
            for row in region
        ):
            result.extend(rows)
            continue
        result.extend(rows[:first])
        for column in (0, 1):
            for row in region:
                raw = row.get("layout", "")
                text = raw[:cut] if column == 0 else raw[cut:]
                text = re.sub(r" {3,}", " | ", text.strip())
                text = " ".join(text.replace("\u00ad", "").split()).translate(LIGATURES)
                if text:
                    result.append({"location": row["location"], "text": text})
    if len(result) > 500:
        raise DocumentError("Use a resume with at most 500 text lines.")
    return [
        {"id": str(i), "location": row["location"], "text": row["text"]}
        for i, row in enumerate(result)
    ]
