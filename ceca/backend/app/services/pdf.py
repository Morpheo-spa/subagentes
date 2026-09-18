"""PDF inspection and native DeCA rendering.

A DeCA must be born digital: generated from structured data into real, readable
text. A photo or a scan cannot be one, whatever metadata we attach to it, which
is why :func:`has_text_layer` decides how an upload is classified.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas as pdfcanvas

from app.services.qr import qr_png

PDF_MAGIC = b"%PDF-"

#: Pages sampled when deciding whether a PDF carries real text.
TEXT_PROBE_PAGES = 5
#: Below this many printable characters the file is treated as an image scan.
TEXT_LAYER_MIN_CHARS = 24

_FIELDS_PATH = Path(__file__).resolve().parent.parent / "i18n" / "deca_fields.json"

_TEXT: dict[str, dict[str, str]] = {
    "title": {
        "es": "Documento electronico de Control Administrativo (DeCA)",
        "en": "Electronic Administrative Control Document (DeCA)",
    },
    "site": {"es": "Centro emisor", "en": "Issuing site"},
    "document_id": {"es": "Identificador", "en": "Identifier"},
    "revision": {"es": "Revision", "en": "Revision"},
    "issued_at": {"es": "Emitido el", "en": "Issued on"},
    "verify": {
        "es": "Verifique este documento escaneando el codigo QR.",
        "en": "Verify this document by scanning the QR code.",
    },
    "superseded_title": {
        "es": "Datos sustituidos",
        "en": "Superseded data",
    },
    "not_valid": {"es": "NO VALIDO", "en": "NOT VALID"},
    "change_reason": {"es": "Motivo del cambio", "en": "Reason for the change"},
    "legal_note": {
        "es": (
            "Documento de control del transporte publico de mercancias por carretera, "
            "art. 6 Orden FOM/2861/2012 y Resolucion de 5 de junio de 2026."
        ),
        "en": (
            "Control document for the public road carriage of goods, art. 6 Order "
            "FOM/2861/2012 and the Resolution of 5 June 2026."
        ),
    },
}

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 18 * mm
QR_SIZE = 34 * mm
LABEL_WIDTH = 62 * mm
BODY_FONT = "Helvetica"
BOLD_FONT = "Helvetica-Bold"


def is_pdf(data: bytes) -> bool:
    """Trust the magic header, never the browser's content type."""
    return data[: len(PDF_MAGIC)] == PDF_MAGIC


def page_count(data: bytes) -> int:
    try:
        return len(PdfReader(BytesIO(data)).pages)
    except Exception:
        return 0


def has_text_layer(data: bytes) -> bool:
    """False means the file is a scan or a photo, i.e. not a valid DeCA."""
    try:
        reader = PdfReader(BytesIO(data))
        characters = 0
        for page in reader.pages[:TEXT_PROBE_PAGES]:
            characters += len("".join((page.extract_text() or "").split()))
            if characters >= TEXT_LAYER_MIN_CHARS:
                return True
    except Exception:
        return False
    return False


def render_deca_pdf(
    deca: dict,
    *,
    qr_url: str,
    document_id: UUID,
    site_name: str,
    superseded: dict | None = None,
    change_reason: str | None = None,
    language: str = "es",
) -> bytes:
    """Render a native DeCA: selectable text drawn from the data, QR embedded.

    ``superseded`` holds the previous values of the fields this revision
    changes. They are printed struck through and marked NOT VALID next to the
    reason for the change, as the fifth section of the Resolution requires.
    """
    buffer = BytesIO()
    pdf = pdfcanvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(f"DeCA {document_id}")
    pdf.setAuthor(site_name)

    cursor = _draw_header(pdf, qr_url, document_id, site_name, language)
    cursor = _draw_fields(pdf, deca, cursor, language)
    if superseded:
        cursor = _draw_superseded(pdf, superseded, change_reason, cursor, language)
    _draw_footer(pdf, language)

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def embed_qr(pdf_bytes: bytes, qr_url: str) -> bytes:
    """Stamp the QR onto the first page of an existing native PDF."""
    reader = PdfReader(BytesIO(pdf_bytes))
    first = reader.pages[0]
    width = float(first.mediabox.width)
    height = float(first.mediabox.height)

    overlay = BytesIO()
    stamp = pdfcanvas.Canvas(overlay, pagesize=(width, height))
    size = min(QR_SIZE, width / 4, height / 4)
    stamp.drawImage(
        ImageReader(BytesIO(qr_png(qr_url))),
        width - size - 10 * mm,
        height - size - 10 * mm,
        size,
        size,
    )
    stamp.showPage()
    stamp.save()
    overlay.seek(0)

    first.merge_page(PdfReader(overlay).pages[0])
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


@lru_cache
def _catalogue() -> list[dict[str, Any]]:
    """Field labels for the PDF chrome, from the same seed the catalogue uses."""
    with _FIELDS_PATH.open(encoding="utf-8") as handle:
        fields: list[dict[str, Any]] = json.load(handle)["fields"]
    return sorted(fields, key=lambda field: field.get("sort_order", 0))


def _label_for(code: str, language: str) -> str:
    for field in _catalogue():
        if field["code"] == code:
            return field["label_en" if language == "en" else "label_es"]
    return code


def _say(key: str, language: str) -> str:
    entry = _TEXT[key]
    return entry.get(language) or entry["es"]


def _ordered_items(values: dict, language: str) -> list[tuple[str, str]]:
    known = [field["code"] for field in _catalogue()]
    codes = [code for code in known if values.get(code) not in (None, "")]
    codes += [code for code in values if code not in known and values[code] not in (None, "")]
    return [(_label_for(code, language), _format_value(values[code])) for code in codes]


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "si" if value else "no"
    return str(value)


def _draw_header(
    pdf: pdfcanvas.Canvas,
    qr_url: str,
    document_id: UUID,
    site_name: str,
    language: str,
) -> float:
    top = PAGE_HEIGHT - MARGIN
    pdf.drawImage(
        ImageReader(BytesIO(qr_png(qr_url))),
        PAGE_WIDTH - MARGIN - QR_SIZE,
        top - QR_SIZE,
        QR_SIZE,
        QR_SIZE,
    )

    text_width = PAGE_WIDTH - 2 * MARGIN - QR_SIZE - 6 * mm
    cursor = _wrapped(
        pdf, _say("title", language), MARGIN, top - 5 * mm, text_width, BOLD_FONT, 14, 17
    )
    cursor -= 3 * mm

    header_rows = (
        (_say("site", language), site_name),
        (_say("document_id", language), str(document_id)),
        (_say("issued_at", language), datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")),
    )
    for label, value in header_rows:
        cursor = _row(pdf, label, value, cursor, width=text_width)

    cursor = min(cursor, top - QR_SIZE) - 6 * mm
    pdf.setFont(BODY_FONT, 7.5)
    pdf.drawRightString(PAGE_WIDTH - MARGIN, cursor + 2 * mm, _say("verify", language))
    pdf.setLineWidth(0.6)
    pdf.line(MARGIN, cursor, PAGE_WIDTH - MARGIN, cursor)
    return cursor - 8 * mm


def _draw_fields(pdf: pdfcanvas.Canvas, values: dict, cursor: float, language: str) -> float:
    for label, value in _ordered_items(values, language):
        cursor = _row(pdf, label, value, cursor)
        cursor = _page_break(pdf, cursor, language)
    return cursor


def _draw_superseded(
    pdf: pdfcanvas.Canvas,
    superseded: dict,
    change_reason: str | None,
    cursor: float,
    language: str,
) -> float:
    cursor -= 6 * mm
    pdf.setLineWidth(0.6)
    pdf.line(MARGIN, cursor, PAGE_WIDTH - MARGIN, cursor)
    cursor -= 8 * mm

    pdf.setFont(BOLD_FONT, 11)
    pdf.drawString(MARGIN, cursor, _say("superseded_title", language))
    cursor -= 7 * mm

    for label, value in _ordered_items(superseded, language):
        cursor = _struck_row(pdf, label, value, cursor, language)
        cursor = _page_break(pdf, cursor, language)

    if change_reason:
        cursor -= 3 * mm
        cursor = _row(pdf, _say("change_reason", language), change_reason, cursor)
    return cursor


def _draw_footer(pdf: pdfcanvas.Canvas, language: str) -> None:
    pdf.setFont(BODY_FONT, 7)
    lines = simpleSplit(_say("legal_note", language), BODY_FONT, 7, PAGE_WIDTH - 2 * MARGIN)
    baseline = MARGIN
    for line in reversed(lines):
        pdf.drawString(MARGIN, baseline, line)
        baseline += 9


def _row(
    pdf: pdfcanvas.Canvas,
    label: str,
    value: str,
    cursor: float,
    *,
    width: float | None = None,
) -> float:
    value_width = (width or PAGE_WIDTH - 2 * MARGIN) - LABEL_WIDTH
    pdf.setFont(BOLD_FONT, 9)
    pdf.drawString(MARGIN, cursor, label)
    bottom = _wrapped(pdf, value, MARGIN + LABEL_WIDTH, cursor, value_width, BODY_FONT, 9.5, 12)
    return bottom - 3 * mm


def _struck_row(
    pdf: pdfcanvas.Canvas, label: str, value: str, cursor: float, language: str
) -> float:
    pdf.setFont(BOLD_FONT, 9)
    pdf.drawString(MARGIN, cursor, label)
    pdf.setFont(BODY_FONT, 9.5)
    text = f"{value}  -  {_say('not_valid', language)}"
    pdf.drawString(MARGIN + LABEL_WIDTH, cursor, text)
    text_width = pdf.stringWidth(text, BODY_FONT, 9.5)
    pdf.setLineWidth(0.7)
    pdf.line(
        MARGIN + LABEL_WIDTH,
        cursor + 3,
        MARGIN + LABEL_WIDTH + text_width,
        cursor + 3,
    )
    return cursor - 8 * mm


def _wrapped(
    pdf: pdfcanvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    font: str,
    size: float,
    leading: float,
) -> float:
    pdf.setFont(font, size)
    cursor = y
    for line in simpleSplit(text, font, size, width):
        pdf.drawString(x, cursor, line)
        cursor -= leading
    return cursor


def _page_break(pdf: pdfcanvas.Canvas, cursor: float, language: str) -> float:
    if cursor > MARGIN + 24 * mm:
        return cursor
    _draw_footer(pdf, language)
    pdf.showPage()
    return PAGE_HEIGHT - MARGIN
