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
        # Most resume templates hide item and row boundaries in these commands.
        bullet = "• " if node.macroname.lower().endswith("item") else ""
        return "\n" + bullet + text + "\n"

    parser.add_context_category(
        "resume-commands",
        prepend=True,
        macros=[macrospec.MacroSpec(name, spec) for name, spec in custom.items()]
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
        macros=[latex2text.MacroTextSpec(name, simplify_repl=arguments) for name in custom]
        + [
            latex2text.MacroTextSpec(name, simplify_repl="\n%(3)s\n")
            for name in ("section", "subsection", "subsubsection")
        ]
        + [
            latex2text.MacroTextSpec("href", simplify_repl="%(2)s"),
            latex2text.MacroTextSpec("url", simplify_repl="%(1)s"),
            latex2text.MacroTextSpec("textcolor", simplify_repl="%(3)s"),
        ]
        + [
            latex2text.MacroTextSpec(name, discard=True)
            for name in ("fontsize", "color", "fontfamily")
        ],
        specials=[latex2text.SpecialsTextSpec("&", " | ")],
    )
    parsed, _, _ = latexwalker.LatexWalker(body, latex_context=parser).get_latex_nodes()
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


def extract(data: bytes, kind: str) -> list[dict[str, str]]:
    if not data or len(data) > MAX_UPLOAD:
        raise DocumentError("Upload a nonempty document of at most 5 MiB.")
    chunks: list[tuple[str, str]] = []
    if kind == "tex":
        chunks.append(("TeX document body", tex_text(tex_source(data))))
    elif kind == "pdf":
        from pypdf import PdfReader

        if not data.startswith(b"%PDF-"):
            raise DocumentError("The file is not a PDF. Export a new PDF or DOCX.")
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise DocumentError("Encrypted PDFs are unsupported. Export an unencrypted copy.")
        if len(reader.pages) > 30:
            raise DocumentError("Use a resume with at most 30 pages.")
        for index, page in enumerate(reader.pages):
            contents = page.get_contents()
            if contents is None:
                continue
            if len(contents.get_data()) > MAX_PDF_CONTENT:
                raise DocumentError("PDF page content exceeds 2 MiB. Export a simpler PDF.")
            text = (
                page.extract_text(extraction_mode="layout", layout_mode_space_vertically=False)
                or ""
            )
            # Keep visual columns distinct before the shared whitespace normalization.
            text = "\n".join(re.sub(r" {3,}", " | ", row.strip()) for row in text.splitlines())
            chunks.append((f"Page {index + 1}", text))
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
            if not clean:
                continue
            if len(clean) > 2000:
                raise DocumentError(
                    "A text block exceeds 2,000 characters. Re-export with paragraphs."
                )
            lines.append({"id": str(len(lines)), "location": location, "text": clean})
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
