"""Resource-limited, text-only child process for untrusted résumé documents."""

from __future__ import annotations

import io
import json
import logging
import re
import resource
import sys
import zipfile
from typing import Any, cast

MAX_UPLOAD = 5 * 1024 * 1024
MAX_TEXT = 100_000
MAX_PDF_CONTENT = 2 * 1024 * 1024
LIGATURES = {ord("ﬀ"): "ff", ord("ﬁ"): "fi", ord("ﬂ"): "fl", ord("ﬃ"): "ffi", ord("ﬄ"): "ffl"}


class DocumentError(ValueError):
    pass


def tex_text(source: str) -> str:
    """Read syntax and declared argument counts, never expand or execute user macros."""
    from pylatexenc import latex2text, latexwalker, macrospec

    parser = latexwalker.get_default_latex_context_db()
    context = latex2text.get_default_latex_context_db()
    visible = re.sub(r"(?<!\\)%[^\n]*", "", source)
    preamble, _, body = visible.partition(r"\begin{document}")
    body = body.rpartition(r"\end{document}")[0]
    custom = {}
    single_name = bool(re.search(r"\\documentclass(?:\[[^\]]*\])?\s*\{altacv\}", preamble))
    # Public signatures of common resume classes whose definitions live in .cls files.
    known = {
        "cvsection": "{",
        "cventry": "{{{{{{",
        "cvevent": "{{{{",
        "cvitem": "[{{",
        "cvskill": "{{",
        "name": "{" if single_name else "{{",
        "firstname": "{",
        "familyname": "{",
        "email": "{",
        "phone": "[{",
        "homepage": "{",
        "social": "[{",
    }
    # Read signatures only: definition bodies can deliberately contain unbalanced
    # environments (list-start/list-end commands), and must never be expanded.
    declarations = re.finditer(
        r"\\(?:newcommand|renewcommand|providecommand)\*?\s*"
        r"(?:\{\s*\\([A-Za-z]+)\s*\}|\\([A-Za-z]+))\s*"
        r"(?:\[([0-9])\])?\s*(?:\[([^\]\n]*)\])?",
        preamble,
    )
    for declaration in declarations:
        name = declaration[1] or declaration[2]
        count = int(declaration[3] or "0")
        if parser.get_macro_spec(name) is None:
            custom[name] = "[" + "{" * (count - 1) if declaration[4] is not None else "{" * count

    def arguments(node: Any, l2tobj: Any) -> str:
        values = [
            " ".join(l2tobj.nodelist_to_text([arg]).split())
            for arg in node.nodeargd.argnlist
            if arg is not None
        ]
        text = " | ".join(value for value in values if value)
        if node.macroname == "cvitem" and len(values) >= 2:
            text = values[-2] + ": " + values[-1]
        if node.macroname == "cventry" and len(values) == 6 and values[-1]:
            text = " | ".join(value for value in values[:-1] if value)
            text += "\n* " + values[-1]
        # Most resume templates hide item and row boundaries in these commands.
        bullet = "• " if node.macroname.lower().endswith("item") else ""
        return "\n" + bullet + text + "\n"

    def link(node: Any, l2tobj: Any) -> str:
        target, label = [
            l2tobj.nodelist_to_text([arg]) if arg is not None else ""
            for arg in node.nodeargd.argnlist
        ]
        target = target.removeprefix("mailto:")
        if target == label or not target.startswith(("https://", "http://")) and "@" not in target:
            return label
        return target if "@" in target else f"{label} | {target}"

    signatures = {**known, **custom}
    parser.add_context_category(
        "resume-commands",
        prepend=True,
        macros=[macrospec.MacroSpec(name, spec) for name, spec in signatures.items()]
        + [
            macrospec.MacroSpec("href", "{{"),
            macrospec.MacroSpec("url", "{"),
            macrospec.MacroSpec("textcolor", "[{{"),
            macrospec.MacroSpec("fontsize", "{{"),
            macrospec.MacroSpec("color", "[{"),
            macrospec.MacroSpec("fontfamily", "{"),
        ],
    )
    context.add_context_category(
        "resume-text",
        prepend=True,
        macros=[
            latex2text.MacroTextSpec(name, simplify_repl=arguments)
            for name in signatures
            if name not in {"name", "firstname", "familyname", "email", "cvsection"}
        ]
        + [
            latex2text.MacroTextSpec(name, simplify_repl="\n%(3)s\n")
            for name in ("section", "subsection", "subsubsection")
        ]
        + [
            latex2text.MacroTextSpec("par", simplify_repl="\n"),
            latex2text.MacroTextSpec("href", simplify_repl=link),
            latex2text.MacroTextSpec("url", simplify_repl="%(1)s"),
            latex2text.MacroTextSpec("textcolor", simplify_repl="%(3)s"),
            latex2text.MacroTextSpec(
                "name", simplify_repl="\n%(1)s\n" if single_name else "\n%(1)s %(2)s\n"
            ),
            latex2text.MacroTextSpec("firstname", simplify_repl="%(1)s "),
            latex2text.MacroTextSpec("familyname", simplify_repl="%(1)s\n"),
            latex2text.MacroTextSpec("email", simplify_repl="\n%(1)s\n"),
            latex2text.MacroTextSpec("cvsection", simplify_repl="\n%(1)s\n"),
        ]
        + [
            latex2text.MacroTextSpec(name, discard=True)
            for name in ("fontsize", "color", "fontfamily")
        ],
        specials=[latex2text.SpecialsTextSpec("&", " | ")],
    )
    # moderncv stores contact values before the document. Read only known literal
    # declarations, never definitions, class files, includes, or arbitrary expansion.
    contact = re.findall(
        r"(?m)^\s*(\\(?:name\s*\{[^{}\n]*\}(?:\s*\{[^{}\n]*\})?|"
        r"(?:firstname|familyname|email)\s*\{[^{}\n]*\}))",
        preamble,
    )
    parsed, _, _ = latexwalker.LatexWalker(
        "\n".join(contact) + "\n" + body, latex_context=parser
    ).get_latex_nodes()
    # No input directory is configured: input/include never read external files.
    return cast(str, latex2text.LatexNodes2Text(latex_context=context).nodelist_to_text(parsed))


def tex_source(data: bytes) -> str:
    try:
        source = data.decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeDecodeError:
        raise DocumentError("Save the .tex file as UTF-8 and upload it again.") from None
    if len(source) > MAX_TEXT or "\x00" in source:
        raise DocumentError("Use a UTF-8 .tex document of at most 100,000 characters.")
    # Comments cannot supply the required document delimiters.
    visible = re.sub(r"(?<!\\)%[^\n]*", "", source)
    if r"\begin{document}" not in visible or r"\end{document}" not in visible:
        raise DocumentError("Upload a complete .tex document with begin/end document.")
    return source


def pdf_rows(data: bytes) -> list[dict[str, str]]:
    """Keep word geometry and link targets until columns have been resolved."""
    import pdfplumber
    from pdfplumber.utils.clustering import cluster_objects

    rows: list[dict[str, str]] = []
    with pdfplumber.open(io.BytesIO(data)) as document:
        for index, page in enumerate(document.pages):
            if len(page.chars) > MAX_TEXT:
                raise DocumentError(
                    "Extracted text exceeds 100,000 characters. Use a shorter resume."
                )
            page = page.dedupe_chars()
            words = page.extract_words(x_tolerance_ratio=0.15, y_tolerance=3)
            for group in cluster_objects(words, "top", 3):
                cells: list[dict[str, Any]] = []
                for word in sorted(group, key=lambda word: word["x0"]):
                    # A large physical gap is a table cell, not a word space.
                    if not cells or word["x0"] - cells[-1]["x1"] > max(
                        12, (word["bottom"] - word["top"]) * 1.5
                    ):
                        cells.append(dict(word))
                    else:
                        cells[-1]["text"] += " " + word["text"]
                        cells[-1]["x1"] = word["x1"]
                        cells[-1]["bottom"] = max(cells[-1]["bottom"], word["bottom"])
                for cell in cells:
                    links = []
                    for link in page.hyperlinks:
                        uri = link.get("uri") or ""
                        if (
                            uri.startswith(("https://", "http://"))
                            and len(uri) <= 2048
                            and not re.search(r"\s|[<>|]", uri)
                            and link["x0"] < cell["x1"]
                            and link["x1"] > cell["x0"]
                            and link["top"] < cell["bottom"]
                            and link["bottom"] > cell["top"]
                            and uri not in cell["text"]
                        ):
                            links.append(uri)
                    if links:
                        cell["text"] += " | " + " | ".join(dict.fromkeys(links))
                if cells and any(re.search(r"\w", cell["text"]) for cell in cells):
                    rows.append(
                        {
                            "id": str(len(rows)),
                            "location": f"Page {index + 1}",
                            "text": " | ".join(cell["text"] for cell in cells),
                            "layout": json.dumps(
                                [{key: cell[key] for key in ("x0", "x1", "text")} for cell in cells]
                            ),
                        }
                    )
                    if len(rows) > 500:
                        raise DocumentError("Use a resume with at most 500 text lines.")
            page.close()
    return rows


def extract(data: bytes, kind: str) -> list[dict[str, str]]:
    if not data or len(data) > MAX_UPLOAD:
        raise DocumentError("Upload a nonempty document of at most 5 MiB.")
    chunks: list[tuple[str, str]] = []
    if kind == "tex":
        chunks.append(("TeX document body", tex_text(tex_source(data))))
    elif kind in {"pdf", "pdf-native"}:
        from pypdf import PdfReader

        if not data.startswith(b"%PDF-"):
            raise DocumentError("The file is not a PDF. Export a new PDF or DOCX.")
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise DocumentError("Encrypted PDFs are unsupported. Export an unencrypted copy.")
        if len(reader.pages) > 30:
            raise DocumentError("Use a resume with at most 30 pages.")
        for page in reader.pages:
            contents = page.get_contents()
            if contents is None:
                continue
            if len(contents.get_data()) > MAX_PDF_CONTENT:
                raise DocumentError("PDF page content exceeds 2 MiB. Export a simpler PDF.")
            if kind == "pdf-native":
                continue
        if kind == "pdf-native":
            return [
                {"id": str(i + 1), "location": f"Page {i + 1}", "text": ""}
                for i in range(len(reader.pages))
            ]
        rows = pdf_rows(data)
        chunks = [(row["location"], row["text"]) for row in rows]
    elif kind == "docx":
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        if data.startswith(bytes.fromhex("d0cf11e0")):
            raise DocumentError("Encrypted or older Word files are unsupported. Export DOCX.")
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise DocumentError("The file is not a DOCX. Export a new DOCX or PDF.")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 512 or sum(m.file_size for m in members) > 20 * 1024 * 1024:
                raise DocumentError("DOCX expanded content exceeds the 20 MiB / 512-part limit.")
            if len({m.filename for m in members}) != len(members):
                raise DocumentError("DOCX contains duplicate parts. Export a clean document.")
            for member in members:
                name = member.filename.lower()
                if member.flag_bits & 1:
                    raise DocumentError("Encrypted DOCX files are unsupported.")
                if member.file_size > max(member.compress_size, 1) * 100:
                    raise DocumentError("DOCX compression exceeds the safe expansion limit.")
                if "vbaproject" in name or "/embeddings/" in name:
                    raise DocumentError(
                        "Macros and embedded objects are unsupported. Export a PDF."
                    )
                if name.endswith((".xml", ".rels")):
                    xml = archive.read(member).upper()
                    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                        raise DocumentError(
                            "DOCX XML entities are unsupported. Export a clean file."
                        )
        document = Document(io.BytesIO(data))
        for index, item in enumerate(document.iter_inner_content()):
            if isinstance(item, Paragraph):
                chunks.append((f"Paragraph {index + 1}", item.text))
            elif isinstance(item, Table):
                for row_index, row in enumerate(item.rows):
                    chunks.append(
                        (
                            f"Table {index + 1}, row {row_index + 1}",
                            " | ".join(cell.text for cell in row.cells),
                        )
                    )
        for index, section in enumerate(document.sections):
            for label, part in (("header", section.header), ("footer", section.footer)):
                for paragraph in part.paragraphs:
                    chunks.append((f"Section {index + 1} {label}", paragraph.text))
    else:
        raise DocumentError("Only PDF, DOCX and TEX are supported.")
    if sum(len(text) for _, text in chunks) > MAX_TEXT:
        raise DocumentError("Extracted text exceeds 100,000 characters. Use a shorter resume.")
    lines: list[dict[str, str]] = []
    for location, text in chunks:
        for raw in text.splitlines():
            clean = " ".join(raw.replace("\u00ad", "").split())
            clean = clean.translate(LIGATURES)
            if not clean or re.fullmatch(r"[•●▪◦‣*\-–|]+", clean):
                continue
            if len(clean) > 2000:
                raise DocumentError(
                    "A text block exceeds 2,000 characters. Re-export with paragraphs."
                )
            lines.append({"id": str(len(lines)), "location": location, "text": clean})
    if kind == "pdf":
        for line, row in zip(lines, rows, strict=True):
            line["layout"] = row["layout"]
    if len(lines) > 500:
        raise DocumentError("Use a resume with at most 500 text lines.")
    if not lines:
        raise DocumentError("No readable text found. Image-only files need OCR before importing.")
    return lines


def main() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    logging.disable(logging.CRITICAL)
    result: dict[str, list[dict[str, str]] | str]
    try:
        result = {"lines": extract(sys.stdin.buffer.read(MAX_UPLOAD + 1), sys.argv[1])}
    except DocumentError as exc:
        result = {"error": str(exc)}
    except Exception:
        result = {
            "error": "Document could not be read safely. Export a fresh PDF/DOCX "
            "or upload a complete UTF-8 .tex document."
        }
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
