"""A PDF is bytes an attacker chose. Reading one must cost what we decide.

Two different things are pinned down here. One: a file that is hostile about
its own structure - a page tree claiming thousands of pages, an absurd object
table - is refused up front, cheaply, instead of being handed to pypdf to walk.
Two: none of this work happens on the event loop, because the 5 MB limit is on
*compressed* bytes and a decompression bomb inside that budget would otherwise
stall every tenant's request at once, not just its own.

A file that is merely broken is not hostile: it stays a scan, which is what
``NOT_A_DECA`` means, and that semantics is pinned here too.
"""

from __future__ import annotations

import asyncio
import time
from io import BytesIO
from typing import Any
from uuid import uuid4

import pytest
from pypdf import PdfReader

from app.errors import DomainError
from app.schemas.documents import MAX_DECA_FIELDS, MAX_DECA_VALUE_CHARS
from app.services import pdf


def craft_pdf(*, declared_pages: int = 1, declared_objects: int | None = None) -> bytes:
    """A structurally valid PDF that says whatever we want about its size.

    The claim and the content are deliberately allowed to disagree: that gap is
    the cheap signal, available before anything walks the file.
    """
    bodies = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count %d>>" % declared_pages,
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(bodies, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % index + body + b"\nendobj\n"

    size = declared_objects if declared_objects is not None else len(bodies) + 1
    start_xref = len(out)
    out += b"xref\n0 %d\n" % (len(bodies) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (size, start_xref)
    return bytes(out)


def _deca(fields: int, chars: int) -> dict[str, Any]:
    """Wrappable prose, not one long token: text that really does fill pages."""
    value = ("palabra " * (chars // 8 + 1))[:chars]
    return {f"campo_{index}": value for index in range(fields)}


async def test_a_pdf_that_claims_thousands_of_pages_is_refused() -> None:
    """The claim alone is grounds for refusal: verifying it is the expensive part."""
    data = craft_pdf(declared_pages=100_000)

    with pytest.raises(DomainError) as raised:
        await pdf.inspect_offloaded(data, filename="bomba.pdf")

    assert raised.value.code == "PDF_TOO_MANY_PAGES"
    assert raised.value.status_code == 422
    assert raised.value.params["pages"] == 100_000
    assert raised.value.params["max_pages"] == pdf.MAX_PDF_PAGES


async def test_a_pdf_with_an_absurd_object_table_is_refused() -> None:
    data = craft_pdf(declared_objects=pdf.MAX_PDF_OBJECTS + 1)

    with pytest.raises(DomainError) as raised:
        await pdf.inspect_offloaded(data, filename="bomba.pdf")

    assert raised.value.code == "PDF_TOO_COMPLEX"


async def test_a_normal_pdf_is_read_without_complaint() -> None:
    """The guard has to let a real delivery note through, or it guards nothing."""
    rendered = pdf.render_deca_pdf(
        {"origen": "Madrid", "destino": "Zaragoza"},
        qr_url="http://testserver/v/token",
        document_id=uuid4(),
        site_name="Centro Demo",
    )

    facts = await pdf.inspect_offloaded(rendered.data, filename="albaran.pdf")

    assert facts.page_count == 1
    assert facts.has_text_layer is True


async def test_bytes_pypdf_cannot_read_are_a_scan_not_an_error() -> None:
    """Unreadable is not hostile. A scan is archived and flagged NOT_A_DECA."""
    facts = await pdf.inspect_offloaded(b"%PDF-1.4 y nada mas", filename="foto.pdf")

    assert facts.page_count == 0
    assert facts.has_text_layer is False


async def test_parsing_a_pdf_does_not_block_the_event_loop() -> None:
    """The loop keeps turning while a file is being chewed on.

    Before, ``has_text_layer`` and ``page_count`` ran pypdf inside the endpoint
    coroutine: one slow file and no other tenant got an answer until it
    finished. The ticker below is what every other request is.
    """
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.005)
            ticks += 1

    def slow_inspect(data: bytes, *, filename: str) -> pdf.PdfFacts:
        time.sleep(0.2)
        return pdf.PdfFacts(page_count=1, has_text_layer=True)

    original = pdf.inspect
    pdf.inspect = slow_inspect  # type: ignore[assignment]
    beat = asyncio.create_task(ticker())
    try:
        await pdf.inspect_offloaded(b"%PDF-1.4", filename="lento.pdf")
    finally:
        pdf.inspect = original  # type: ignore[assignment]
        beat.cancel()

    assert ticks > 0, "the event loop was blocked while the PDF was parsed"


async def test_work_that_overruns_its_budget_fails_with_a_domain_error() -> None:
    """A hostile file loses its own request. It does not take the process."""

    def never_returns(data: bytes, *, filename: str) -> pdf.PdfFacts:
        time.sleep(30)
        raise AssertionError("unreachable")

    original_inspect = pdf.inspect
    original_seconds = pdf.PDF_WORK_SECONDS
    original_grace = pdf.OFFLOAD_GRACE_SECONDS
    pdf.inspect = never_returns  # type: ignore[assignment]
    pdf.PDF_WORK_SECONDS = 0.05
    pdf.OFFLOAD_GRACE_SECONDS = 0.05
    try:
        with pytest.raises(DomainError) as raised:
            await pdf.inspect_offloaded(b"%PDF-1.4", filename="eterno.pdf")
    finally:
        pdf.inspect = original_inspect  # type: ignore[assignment]
        pdf.PDF_WORK_SECONDS = original_seconds
        pdf.OFFLOAD_GRACE_SECONDS = original_grace

    assert raised.value.code == "PDF_ANALYSIS_TIMEOUT"


def test_the_pdf_we_generate_carries_no_metadata_of_its_own() -> None:
    """What a scanner gets is the face of the document, not our toolchain.

    The site name is on the page because it belongs there; it has no business
    also sitting in ``/Author`` next to a reportlab version string.
    """
    rendered = pdf.render_deca_pdf(
        {"origen": "Madrid"},
        qr_url="http://testserver/v/token",
        document_id=uuid4(),
        site_name="Centro Logistico Norte SL",
    )

    facts = pdf.inspect(rendered.data, filename="deca.pdf")
    info = PdfReader(BytesIO(rendered.data)).metadata or {}
    ours = ("Title", "Producer", "Creator")
    leaked = [field for field in facts.metadata_fields if field not in ours]

    assert leaked == [], f"generated PDF leaks metadata: {leaked}"
    assert "XMP" not in facts.metadata_fields
    assert info.get("/Author") == "", "the site name must not sit in /Author"
    assert info.get("/Producer") == pdf.PRODUCER
    assert info.get("/Creator") == pdf.PRODUCER
    assert "Centro Logistico Norte SL" not in str(dict(info))


def test_the_renderer_stops_at_its_page_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_page_break`` used to make a new page for as long as there was content.

    The budget is patched down rather than fed enough data to reach the real
    one, so the test pins the mechanism and not the font metrics.
    """
    monkeypatch.setattr(pdf, "MAX_RENDER_PAGES", 3)

    with pytest.raises(DomainError) as raised:
        pdf.render_deca_pdf(
            _deca(pdf.MAX_RENDERED_FIELDS, pdf.MAX_RENDERED_VALUE_CHARS),
            qr_url="http://testserver/v/token",
            document_id=uuid4(),
            site_name="Centro Demo",
            superseded=_deca(pdf.MAX_RENDERED_FIELDS, pdf.MAX_RENDERED_VALUE_CHARS),
        )

    assert raised.value.code == "DECA_RENDER_PAGE_LIMIT"
    assert raised.value.params["max_pages"] == 3


def test_the_biggest_payload_the_api_accepts_still_fits_in_the_budget() -> None:
    """The backstop must sit above what a legitimate caller can send.

    A budget a real delivery note could trip would be a bug, not a guard, so the
    two limits are checked against each other here rather than assumed.
    """
    rendered = pdf.render_deca_pdf(
        _deca(MAX_DECA_FIELDS, MAX_DECA_VALUE_CHARS),
        qr_url="http://testserver/v/token",
        document_id=uuid4(),
        site_name="Centro Demo",
        superseded=_deca(MAX_DECA_FIELDS, MAX_DECA_VALUE_CHARS),
    )

    assert rendered.page_count < pdf.MAX_RENDER_PAGES


def test_a_single_huge_value_is_cut_before_it_reaches_the_canvas() -> None:
    drawn = pdf._ordered_items({"observaciones": "palabra " * 10_000}, "es")

    assert len(drawn) == 1
    assert len(drawn[0][1]) <= pdf.MAX_RENDERED_VALUE_CHARS + 3


def test_only_a_bounded_number_of_fields_is_ever_drawn() -> None:
    drawn = pdf._ordered_items(_deca(pdf.MAX_RENDERED_FIELDS * 4, 10), "es")

    assert len(drawn) == pdf.MAX_RENDERED_FIELDS


def _one_page_with(operators: int, text: bytes = b"") -> bytes:
    """A syntactically clean single page whose content stream is mostly noise.

    ``() Tj`` draws nothing, so no amount of it ever satisfies the text probe:
    the parser has to walk every operator. Compressed, a few hundred thousand
    of them fit in well under the upload limit.
    """
    import zlib

    content = zlib.compress(b"BT /F1 12 Tf " + (b"(" + text + b") Tj ") * operators + b"ET")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(content)
        + content
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def test_a_content_stream_that_never_ends_stops_at_the_deadline() -> None:
    """N-02: the deadline has to reach inside a page, not only between pages.

    Before the fix the request timed out cleanly while the worker thread went
    on at 100 % CPU for minutes. Now the thread itself gives up.
    """
    data = _one_page_with(150_000)
    assert len(data) < 64 * 1024

    original_seconds = pdf.PDF_WORK_SECONDS
    pdf.PDF_WORK_SECONDS = 0.2
    started = time.monotonic()
    try:
        with pytest.raises(DomainError) as raised:
            pdf.inspect(data, filename="lento.pdf")
    finally:
        pdf.PDF_WORK_SECONDS = original_seconds
    elapsed = time.monotonic() - started

    assert raised.value.code == "PDF_ANALYSIS_TIMEOUT"
    assert elapsed < 3.0, f"the parser kept going for {elapsed:.1f}s past a 0.2s deadline"


def test_a_page_with_megabytes_of_operators_is_refused_before_parsing() -> None:
    """Tokenising runs before any hook can interrupt it, so size is the guard."""
    data = _one_page_with(600_000, text=b"albaran")
    assert len(data) < 64 * 1024

    started = time.monotonic()
    with pytest.raises(DomainError) as raised:
        pdf.inspect(data, filename="denso.pdf")
    elapsed = time.monotonic() - started

    assert raised.value.code == "PDF_PAGE_TOO_COMPLEX"
    assert raised.value.params["max_kilobytes"] == pdf.MAX_PAGE_CONTENT_BYTES // 1024
    assert elapsed < 3.0, f"refusing took {elapsed:.1f}s"


def test_a_dense_but_honest_page_still_counts_as_text() -> None:
    data = _one_page_with(2_000, text=b"albaran")
    facts = pdf.inspect(data, filename="texto.pdf")
    assert facts.page_count == 1
    assert facts.has_text_layer is True
