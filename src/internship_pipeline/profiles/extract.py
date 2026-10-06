"""Resource-limited, text-only child process for untrusted PDF/DOCX input."""

from __future__ import annotations

import io
import json
import logging
import resource
import sys
import zipfile

MAX_UPLOAD = 5 * 1024 * 1024
MAX_TEXT = 100_000
MAX_PDF_CONTENT = 2 * 1024 * 1024


class DocumentError(ValueError):
    pass


def extract(data: bytes, kind: str) -> list[dict[str, str]]:
    if not data or len(data) > MAX_UPLOAD:
        raise DocumentError("Upload a nonempty document of at most 5 MiB.")
    chunks: list[tuple[str, str]] = []
    if kind == "pdf":
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
            if contents is not None and len(contents.get_data()) > MAX_PDF_CONTENT:
                raise DocumentError("PDF page content exceeds 2 MiB. Export a simpler PDF.")
            chunks.append((f"Page {index + 1}", page.extract_text() or ""))
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
        raise DocumentError("Only PDF and DOCX are supported.")
    if sum(len(text) for _, text in chunks) > MAX_TEXT:
        raise DocumentError("Extracted text exceeds 100,000 characters. Use a shorter resume.")
    lines: list[dict[str, str]] = []
    for location, text in chunks:
        for raw in text.splitlines():
            clean = " ".join(raw.split())
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
        result = {"error": "Document could not be read safely. Export a fresh PDF or DOCX."}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
