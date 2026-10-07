"""Synthetic readable PDF fixtures shared by owned-template tests."""

import io

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def textual_pdf(text: str, pages: int = 1, x: int = 40) -> bytes:
    """Synthetic, text-bearing PDF fixture without an authoring dependency."""
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        lines = [f"BT /F1 10 Tf {x} 750 Td 14 TL"]
        for line in text.splitlines():
            safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            lines.append(f"({safe}) Tj T*")
        lines.append("ET")
        stream.set_data("\n".join(lines).encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
