"""PDF inspection and native DeCA rendering.

A DeCA must be born digital: generated from structured data into real, readable
text. A photo or a scan cannot be one, whatever metadata we attach to it, which
is why :func:`inspect` decides how an upload is classified.

Everything in here chews on bytes somebody else chose, so nothing in here runs
on the event loop and nothing in here runs unbounded. The synchronous functions
carry their own ceilings - pages, objects, wall clock, output pages - and the
``*_offloaded`` wrappers are what the services actually call: they hand the work
to a worker thread so one hostile file can stall its own request and no other.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm as _mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas as pdfcanvas

from app.errors import DomainError
from app.services.qr import qr_png

PDF_MAGIC = b"%PDF-"

#: Pages sampled when deciding whether a PDF carries real text.
TEXT_PROBE_PAGES = 5
#: Below this many printable characters the file is treated as an image scan.
TEXT_LAYER_MIN_CHARS = 24

#: A delivery note is a page or two. Anything claiming this many is not one, and
#: walking its page tree is exactly the work an attacker wants us to do.
MAX_PDF_PAGES = 200
#: Ceiling on the cross-reference table we are willing to resolve.
MAX_PDF_OBJECTS = 50_000
#: Inflated bytes of content stream on one probed page. pypdf tokenises a
#: content stream in pure Python at roughly 6 µs per operator before any hook
#: runs, so this is the only thing that bounds that phase. A dense page of
#: text is tens of KB; 3 MB is a page nobody typed.
MAX_PAGE_CONTENT_BYTES = 3 * 1024 * 1024
#: Wall clock one file gets inside the worker thread.
PDF_WORK_SECONDS = 10.0
#: Extra slack before the caller stops waiting for that thread.
OFFLOAD_GRACE_SECONDS = 2.0

#: Ceiling on the PDF we generate ourselves, so DECA data cannot turn into a
#: book. Reached only by data that got past the schema and the catalogue.
MAX_RENDER_PAGES = 20
#: Fields drawn on a generated DeCA, and characters drawn per value.
MAX_RENDERED_FIELDS = 64
MAX_RENDERED_VALUE_CHARS = 1000

#: What we write into the metadata of the PDFs we generate. No version string,
#: no user name, no site name: the face of the document says all of that, the
#: metadata does not need to repeat it to whoever scans the QR.
PRODUCER = "Estampa"

#: Metadata keys worth telling the tenant about before their file goes public.
METADATA_KEYS = ("/Author", "/Creator", "/Producer", "/Subject", "/Keywords", "/Title")


@dataclass(frozen=True, slots=True)
class PdfFacts:
    """What one bounded pass over an uploaded PDF can say about it.

    ``page_count`` is 0 and ``has_text_layer`` False for a file pypdf cannot
    make sense of. That is deliberate: unreadable is treated as a scan, which
    ends up ``NOT_A_DECA``, not as an error. Only a file that is actively
    hostile - too many pages, too many objects, too slow - is refused outright.
    """

    page_count: int
    has_text_layer: bool
    metadata_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RenderedPdf:
    """A DeCA we generated, and how many pages it took.

    The renderer knows the count for free; asking pypdf to read our own output
    back just to learn it would be more parsing on the event loop, which is the
    thing this module is trying to stop doing.
    """

    data: bytes
    page_count: int


_FIELDS_PATH = Path(__file__).resolve().parent.parent / "i18n" / "deca_fields.json"

#: Spanish carries its accents. The base fonts are the standard Helvetica
#: family, whose WinAnsi encoding covers Latin-1, so "electrónico" needs no
#: font registration - the stripped spellings were a habit, not a constraint.
_TEXT: dict[str, dict[str, str]] = {
    "title": {
        "es": "Documento electrónico de Control Administrativo (DeCA)",
        "en": "Electronic Administrative Control Document (DeCA)",
    },
    "site": {"es": "Centro emisor", "en": "Issuing site"},
    "document_id": {"es": "Identificador", "en": "Identifier"},
    "revision": {"es": "Revisión", "en": "Revision"},
    "issued_at": {"es": "Emitido el", "en": "Issued on"},
    "verify": {
        "es": "Verifique este documento escaneando el código QR.",
        "en": "Verify this document by scanning the QR code.",
    },
    "superseded_title": {
        "es": "Datos sustituidos",
        "en": "Superseded data",
    },
    "not_valid": {"es": "NO VÁLIDO", "en": "NOT VALID"},
    "change_reason": {"es": "Motivo del cambio", "en": "Reason for the change"},
    "legal_note": {
        "es": (
            "Documento de control del transporte público de mercancías por carretera, "
            "art. 6 Orden FOM/2861/2012 y Resolución de 5 de junio de 2026."
        ),
        "en": (
            "Control document for the public road carriage of goods, art. 6 Order "
            "FOM/2861/2012 and the Resolution of 5 June 2026."
        ),
    },
}

#: reportlab carries no type information, so its unit and page-size constants
#: arrive untyped. Pinning them once keeps every measurement below a real float.
mm: float = _mm
PAGE_WIDTH: float = A4[0]
PAGE_HEIGHT: float = A4[1]
MARGIN = 18 * mm
QR_SIZE = 34 * mm
BODY_FONT = "Helvetica"
BOLD_FONT = "Helvetica-Bold"

#: A field is drawn as its label on one line and its value wrapped underneath,
#: never side by side: a two-column layout put a 62 mm ceiling on the label,
#: and "Cargador contractual — nombre o razón social" did not fit, so it ran
#: straight into the value. Stacking makes the layout independent of how long
#: the catalogue decides a label is.
LABEL_SIZE = 8.0
LABEL_LEADING = 10.0
VALUE_SIZE = 9.5
VALUE_LEADING = 12.0
STRUCK_SIZE = 8.5
STRUCK_LEADING = 10.0
ROW_GAP = 3.0 * mm
#: The body never goes below this: the two-line legal note sits under it.
BODY_FLOOR = MARGIN + 10 * mm


def is_pdf(data: bytes) -> bool:
    """Trust the magic header, never the browser's content type."""
    return data[: len(PDF_MAGIC)] == PDF_MAGIC


def inspect(data: bytes, *, filename: str) -> PdfFacts:
    """Read an uploaded PDF once, under a hard budget. Never on the event loop.

    The order matters. What the file *claims* about itself is read first,
    because both claims are one dictionary lookup away and refusing an absurd
    one costs nothing; only then do we let pypdf flatten the page tree and pull
    text, which is the part an attacker would like to make expensive.
    """
    deadline = time.monotonic() + PDF_WORK_SECONDS
    reader = _open(data)
    if reader is None:
        return PdfFacts(page_count=0, has_text_layer=False)

    _reject_declared_excess(reader, filename)
    pages = _real_page_count(reader)
    if pages > MAX_PDF_PAGES:
        raise DomainError(
            "PDF_TOO_MANY_PAGES",
            status_code=422,
            filename=filename,
            pages=pages,
            max_pages=MAX_PDF_PAGES,
        )
    return PdfFacts(
        page_count=pages,
        has_text_layer=_probe_text(reader, pages, deadline, filename),
        metadata_fields=_metadata_fields(reader),
    )


async def inspect_offloaded(data: bytes, *, filename: str) -> PdfFacts:
    """:func:`inspect` in a worker thread, with the caller's patience capped."""
    return await _offloaded(lambda: inspect(data, filename=filename), filename=filename)


def _open(data: bytes) -> PdfReader | None:
    try:
        return PdfReader(BytesIO(data), strict=False)
    except Exception:
        return None


def _reject_declared_excess(reader: PdfReader, filename: str) -> None:
    """Refuse a file on its own numbers, before anything walks its structures."""
    declared = _declared_pages(reader)
    if declared > MAX_PDF_PAGES:
        raise DomainError(
            "PDF_TOO_MANY_PAGES",
            status_code=422,
            filename=filename,
            pages=declared,
            max_pages=MAX_PDF_PAGES,
        )
    objects = _declared_objects(reader)
    if objects > MAX_PDF_OBJECTS:
        raise DomainError(
            "PDF_TOO_COMPLEX",
            status_code=422,
            filename=filename,
            objects=objects,
            max_objects=MAX_PDF_OBJECTS,
        )


def _declared_pages(reader: PdfReader) -> int:
    """``/Root /Pages /Count``: what the file says, not what it contains."""
    try:
        return int(reader.root_object["/Pages"]["/Count"])  # type: ignore[index]
    except Exception:
        return 0


def _declared_objects(reader: PdfReader) -> int:
    try:
        return int(reader.trailer.get("/Size", 0))
    except Exception:
        return 0


def _real_page_count(reader: PdfReader) -> int:
    """Flattens the page tree, so it runs only once the claims look sane."""
    try:
        return len(reader.pages)
    except Exception:
        return 0


class _EnoughTextError(Exception):
    """Raised from inside pypdf to stop extracting once the answer is known."""


def _timeout(filename: str) -> DomainError:
    return DomainError(
        "PDF_ANALYSIS_TIMEOUT",
        status_code=422,
        filename=filename,
        seconds=int(PDF_WORK_SECONDS),
    )


def _probe_text(reader: PdfReader, pages: int, deadline: float, filename: str) -> bool:
    """False means the file is a scan or a photo, i.e. not a valid DeCA.

    The deadline is checked between pages *and* between operators of a content
    stream. A single page can hold hundreds of thousands of ``Tj`` operators
    in a 70 KB file, and pypdf walks them in pure Python without ever giving
    the GIL back; a check only between pages left that thread at 100 % CPU for
    minutes after the request had already been answered (audit N-02). The same
    hook stops early once enough text has been seen, so a legitimate file with
    a lot of text costs less, not more.
    """
    characters = 0
    for index in range(min(TEXT_PROBE_PAGES, pages)):
        if time.monotonic() > deadline:
            raise _timeout(filename)
        seen = _text_on_page(reader, index, deadline, filename, TEXT_LAYER_MIN_CHARS - characters)
        if seen is None:
            return True
        characters += seen
        if characters >= TEXT_LAYER_MIN_CHARS:
            return True
    return False


def _text_on_page(
    reader: PdfReader, index: int, deadline: float, filename: str, needed: int
) -> int | None:
    """Characters of text on one page, or None once ``needed`` have been seen."""
    seen = 0

    def before_operand(*_: Any) -> None:
        if time.monotonic() > deadline:
            raise _timeout(filename)

    def on_text(text: str, *_: Any) -> None:
        nonlocal seen
        seen += len("".join(text.split()))
        if seen >= needed:
            raise _EnoughTextError

    try:
        page = reader.pages[index]
        _reject_oversized_content(page, filename)
        page.extract_text(visitor_operand_before=before_operand, visitor_text=on_text)
    except _EnoughTextError:
        return None
    except DomainError:
        raise
    except Exception:
        return 0
    return seen


def _reject_oversized_content(page: Any, filename: str) -> None:
    """Refuse a page whose content stream, inflated, is beyond anything real.

    Decompression is C and fast; tokenising the result is Python and is not,
    and it happens before the operator hook gets a say (audit N-02).
    """
    try:
        contents = page.get_contents()
        size = 0 if contents is None else len(contents.get_data())
    except Exception:
        return
    if size > MAX_PAGE_CONTENT_BYTES:
        raise DomainError(
            "PDF_PAGE_TOO_COMPLEX",
            status_code=422,
            filename=filename,
            kilobytes=size // 1024,
            max_kilobytes=MAX_PAGE_CONTENT_BYTES // 1024,
        )


def _metadata_fields(reader: PdfReader) -> tuple[str, ...]:
    """Which identifying metadata an uploaded file carries into the open.

    We do not strip it - an uploaded DeCA is the tenant's own evidence and we
    return the bytes they gave us - so the least we can do is name what is in
    there, and let the UI say it out loud before the label is printed.
    """
    present: list[str] = []
    try:
        info = reader.metadata
    except Exception:
        info = None
    if info is not None:
        present.extend(key.lstrip("/") for key in METADATA_KEYS if info.get(key))
    try:
        if "/Metadata" in reader.root_object:
            present.append("XMP")
    except Exception:
        return tuple(present)
    return tuple(present)


async def _offloaded[ResultT](work: Callable[[], ResultT], *, filename: str) -> ResultT:
    """Run PDF work off the loop, and stop waiting for it if it misbehaves.

    The thread cannot be killed - Python has no such button - so the timeout
    frees the request and the loop, not the CPU. What stops the thread itself
    is the deadline the synchronous functions check between pages and between
    content-stream operators (:func:`_probe_text`); this outer timeout is only
    the grace the request gives that check to fire.
    """
    try:
        async with asyncio.timeout(PDF_WORK_SECONDS + OFFLOAD_GRACE_SECONDS):
            return await asyncio.to_thread(work)
    except TimeoutError as exc:
        raise DomainError(
            "PDF_ANALYSIS_TIMEOUT",
            status_code=422,
            filename=filename,
            seconds=int(PDF_WORK_SECONDS),
        ) from exc


def render_deca_pdf(
    deca: dict[str, Any],
    *,
    qr_url: str,
    document_id: UUID,
    site_name: str,
    superseded: dict[str, Any] | None = None,
    change_reason: str | None = None,
    language: str = "es",
) -> RenderedPdf:
    """Render a native DeCA: selectable text drawn from the data, QR embedded.

    ``superseded`` holds the previous values of the fields this revision
    changes. They are printed struck through and marked NOT VALID next to the
    reason for the change, as the fifth section of the Resolution requires.
    """
    buffer = BytesIO()
    pdf = pdfcanvas.Canvas(buffer, pagesize=A4)
    _write_clean_metadata(pdf, document_id)

    cursor = _draw_header(pdf, qr_url, document_id, site_name, language)
    cursor = _draw_fields(pdf, deca, cursor, language)
    if superseded:
        cursor = _draw_superseded(pdf, superseded, change_reason, cursor, language)
    _draw_footer(pdf, language)

    pages = pdf.getPageNumber()
    pdf.showPage()
    pdf.save()
    return RenderedPdf(data=buffer.getvalue(), page_count=pages)


async def render_deca_pdf_offloaded(
    deca: dict[str, Any],
    *,
    qr_url: str,
    document_id: UUID,
    site_name: str,
    superseded: dict[str, Any] | None = None,
    change_reason: str | None = None,
    language: str = "es",
) -> RenderedPdf:
    """:func:`render_deca_pdf` in a worker thread. reportlab is not cheap."""

    def work() -> RenderedPdf:
        return render_deca_pdf(
            deca,
            qr_url=qr_url,
            document_id=document_id,
            site_name=site_name,
            superseded=superseded,
            change_reason=change_reason,
            language=language,
        )

    return await _offloaded(work, filename=f"{document_id}.pdf")


def _write_clean_metadata(pdf: pdfcanvas.Canvas, document_id: UUID) -> None:
    """Our own PDF ships with nothing in its metadata we did not choose.

    The generated file is the one place we can decide this, and the identifier
    is already printed on its face, so nothing is lost by refusing to also
    publish the site name, the toolchain and its version to every scanner.
    """
    pdf.setTitle(f"DeCA {document_id}")
    pdf.setAuthor("")
    pdf.setSubject("")
    pdf.setKeywords("")
    pdf.setCreator(PRODUCER)
    pdf.setProducer(PRODUCER)


def embed_qr(pdf_bytes: bytes, qr_url: str, *, filename: str = "documento.pdf") -> bytes:
    """Stamp the QR onto the first page of an existing native PDF.

    Every page gets rewritten, so the same ceilings that guard inspection guard
    this: the file being stamped is one somebody uploaded.
    """
    reader = PdfReader(BytesIO(pdf_bytes), strict=False)
    _reject_declared_excess(reader, filename)
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


async def embed_qr_offloaded(pdf_bytes: bytes, qr_url: str, *, filename: str) -> bytes:
    """:func:`embed_qr` in a worker thread: it rewrites every page of the file."""
    return await _offloaded(
        lambda: embed_qr(pdf_bytes, qr_url, filename=filename), filename=filename
    )


@lru_cache
def _catalogue() -> list[dict[str, Any]]:
    """Field labels for the PDF chrome, from the same seed the catalogue uses."""
    with _FIELDS_PATH.open(encoding="utf-8") as handle:
        fields: list[dict[str, Any]] = json.load(handle)["fields"]
    return sorted(fields, key=lambda field: field.get("sort_order", 0))


def _label_for(code: str, language: str) -> str:
    for field in _catalogue():
        if field["code"] == code:
            return str(field["label_en" if language == "en" else "label_es"])
    return code


def _say(key: str, language: str) -> str:
    entry = _TEXT[key]
    return entry.get(language) or entry["es"]


def _ordered_items(values: dict[str, Any], language: str) -> list[tuple[str, str]]:
    """Catalogue fields first, in catalogue order, and nothing unbounded.

    A code this build has no label for still gets drawn: the authority on what
    a DeCA must carry is the catalogue table, which can legitimately be ahead of
    the seed file bundled here, and silently dropping a field the law asks for
    would be worse than printing it under its raw code. What it does not get is
    room to grow: the list is capped and every value is cut to length, so the
    page budget below is a backstop and not the only defence.
    """
    known = [field["code"] for field in _catalogue()]
    codes = [code for code in known if values.get(code) not in (None, "")]
    codes += [code for code in values if code not in known and values[code] not in (None, "")]
    return [
        (_label_for(code, language), _format_value(values[code]))
        for code in codes[:MAX_RENDERED_FIELDS]
    ]


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "sí" if value else "no"
    text = str(value)
    if len(text) > MAX_RENDERED_VALUE_CHARS:
        return text[:MAX_RENDERED_VALUE_CHARS] + "..."
    return text


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


def _draw_fields(
    pdf: pdfcanvas.Canvas, values: dict[str, Any], cursor: float, language: str
) -> float:
    for label, value in _ordered_items(values, language):
        cursor = _row(pdf, label, value, cursor, language=language)
    return cursor


def _draw_superseded(
    pdf: pdfcanvas.Canvas,
    superseded: dict[str, Any],
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

    if change_reason:
        cursor -= 3 * mm
        cursor = _row(
            pdf, _say("change_reason", language), change_reason, cursor, language=language
        )
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
    language: str | None = None,
) -> float:
    """One field: the label on its own line(s), the value wrapped below it.

    Nothing shares a baseline with anything else, so no label can overlap a
    value whatever the catalogue calls the field. With ``language`` the row
    flows across pages - the label stays with the first value line, the rest
    breaks wherever it must; without it (the header, drawn next to the QR) it
    is laid out on the current page only.
    """
    row_width = width or PAGE_WIDTH - 2 * MARGIN
    label_lines = simpleSplit(label, BOLD_FONT, LABEL_SIZE, row_width)
    value_lines = simpleSplit(value, BODY_FONT, VALUE_SIZE, row_width)
    if language is not None:
        needed = len(label_lines) * LABEL_LEADING + VALUE_LEADING
        cursor = _ensure_room(pdf, cursor, needed, language)
    cursor = _lines(pdf, label_lines, cursor, BOLD_FONT, LABEL_SIZE, LABEL_LEADING, language)
    cursor = _lines(pdf, value_lines, cursor, BODY_FONT, VALUE_SIZE, VALUE_LEADING, language)
    return cursor - ROW_GAP


def _struck_row(
    pdf: pdfcanvas.Canvas, label: str, value: str, cursor: float, language: str
) -> float:
    """A superseded field: NOT VALID next to its label, every value line struck."""
    row_width = PAGE_WIDTH - 2 * MARGIN
    label_lines = simpleSplit(
        f"{label} — {_say('not_valid', language)}", BOLD_FONT, LABEL_SIZE, row_width
    )
    value_lines = simpleSplit(value, BODY_FONT, STRUCK_SIZE, row_width)
    cursor = _ensure_room(pdf, cursor, len(label_lines) * LABEL_LEADING + STRUCK_LEADING, language)
    cursor = _lines(pdf, label_lines, cursor, BOLD_FONT, LABEL_SIZE, LABEL_LEADING, language)
    pdf.setLineWidth(0.7)
    for line in value_lines:
        cursor = _ensure_room(pdf, cursor, STRUCK_LEADING, language)
        pdf.setFont(BODY_FONT, STRUCK_SIZE)
        pdf.drawString(MARGIN, cursor, line)
        pdf.line(
            MARGIN, cursor + 3, MARGIN + pdf.stringWidth(line, BODY_FONT, STRUCK_SIZE), cursor + 3
        )
        cursor -= STRUCK_LEADING
    return cursor - ROW_GAP


def _lines(
    pdf: pdfcanvas.Canvas,
    lines: list[str],
    cursor: float,
    font: str,
    size: float,
    leading: float,
    language: str | None,
) -> float:
    """Draw pre-split lines downwards, breaking the page between them if allowed."""
    for line in lines:
        if language is not None:
            cursor = _ensure_room(pdf, cursor, leading, language)
        pdf.setFont(font, size)
        pdf.drawString(MARGIN, cursor, line)
        cursor -= leading
    return cursor


def _ensure_room(pdf: pdfcanvas.Canvas, cursor: float, needed: float, language: str) -> float:
    """The cursor, on this page or the next, with ``needed`` points above the floor."""
    if cursor - needed >= BODY_FLOOR:
        return cursor
    return _page_break(pdf, language)


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


def _page_break(pdf: pdfcanvas.Canvas, language: str) -> float:
    """Start a new page, unless that would turn a delivery note into a book."""
    if pdf.getPageNumber() >= MAX_RENDER_PAGES:
        raise DomainError("DECA_RENDER_PAGE_LIMIT", status_code=422, max_pages=MAX_RENDER_PAGES)
    _draw_footer(pdf, language)
    pdf.showPage()
    return PAGE_HEIGHT - MARGIN
