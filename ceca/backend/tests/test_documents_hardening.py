"""Availability and evidence: the parts of the archive an attacker can bend.

Four different failures live here, and what they have in common is that none of
them is a data leak. They are the ways this service can be made to do unbounded
work, to destroy a document's usefulness, or to stop recording something it
promises to record.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from starlette.datastructures import UploadFile
from starlette.requests import Request

from app.config import Settings, get_settings
from app.deps import TenantContext
from app.errors import DomainError
from app.models.deca import DecaFieldDefinition
from app.models.documents import DocumentAccess, DocumentOrigin
from app.routers import content_disposition
from app.routers import documents as documents_router
from app.schemas.documents import (
    MAX_DECA_FIELDS,
    MAX_DECA_VALUE_CHARS,
    DecaSidecar,
    DocumentGenerateRequest,
)
from app.services import documents as documents_service

CATALOGUE_PATH = Path(__file__).resolve().parents[1] / "app" / "i18n" / "deca_fields.json"

#: What uvicorn refuses to put in a header value (``httptools_impl.py``). A
#: ``Content-Disposition`` that matches this is a guaranteed 500 in production,
#: however cleanly it comes out of the test client.
UVICORN_FORBIDDEN_IN_HEADER = re.compile(rb"[\x00-\x08\x0a-\x1f\x7f]")

CRLF_FILENAME = "albaran\r\nX-Injected: yes\r\n\r\n<script>alert(1)</script>.pdf"
ACCENTED_FILENAME = "albarán ñandú octubre.pdf"


@pytest.fixture
async def catalogue(db) -> Any:  # noqa: ANN001
    """The DECA catalogue in force, seeded exactly as the migration does."""
    payload = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
    for field in payload["fields"]:
        choices = field.get("choices")
        db.add(
            DecaFieldDefinition(
                code=field["code"],
                label_es=field["label_es"],
                label_en=field["label_en"],
                data_type=field.get("data_type", "string"),
                is_required=field.get("is_required", True),
                max_length=field.get("max_length"),
                pattern=field.get("pattern"),
                choices=json.dumps(choices, ensure_ascii=False) if choices else None,
                sort_order=field.get("sort_order", 0),
                is_active=True,
                catalog_version=payload["catalog_version"],
            )
        )
    await db.flush()
    return payload


def _context(mm: Any, site: Any, user_id: uuid.UUID | None = None) -> TenantContext:
    """A tenant context built the way the JWT builds one: never from a body.

    Pass a real user's id whenever the call under test writes an audit row:
    the audit trail keeps a foreign key to ``users``, and both databases now
    refuse an actor that does not exist.
    """
    return TenantContext(
        user_id=user_id or uuid.uuid4(),
        mm_id=mm.id,
        site_id=site.id,
        site_prefix=site.site_prefix,
        permissions=frozenset({"documents:update", "documents:export"}),
    )


# --- E-04: the DECA payload is not a free-form dictionary --------------------


async def test_a_deca_key_outside_the_catalogue_is_refused(
    db, catalogue, make_tenant, make_document
) -> None:
    """``validate()`` only ever walked the catalogue, so extras sailed through.

    They were not merely stored: ``pdf._ordered_items`` drew them, which is how
    a fixed set of legal fields became an attacker-chosen amount of rendering.
    """
    mm, site = await make_tenant()
    document = await make_document(mm, site, origin=DocumentOrigin.UPLOADED_NATIVE)

    with pytest.raises(DomainError) as raised:
        await documents_service.update_deca(
            db,
            _context(mm, site),
            document.id,
            deca={"origen": "Madrid", "relleno_0": "x", "relleno_1": "y"},
        )

    assert raised.value.code == "DECA_FIELD_UNKNOWN"
    assert raised.value.status_code == 422
    assert raised.value.params["count"] == 2
    assert "relleno_0" in raised.value.params["fields"]


async def test_catalogue_codes_are_still_accepted(
    db, catalogue, make_tenant, make_user, make_document
) -> None:
    """The guard must not refuse the fields the law actually asks for."""
    mm, site = await make_tenant()
    actor = await make_user(mm, site, email="editor@estampa-demo.com", role="operator")
    document = await make_document(mm, site, origin=DocumentOrigin.UPLOADED_NATIVE)

    updated = await documents_service.update_deca(
        db, _context(mm, site, actor.id), document.id, deca={"origen": "Madrid"}
    )

    assert updated.deca["origen"] == "Madrid"


def test_the_schema_caps_how_many_fields_a_payload_may_carry() -> None:
    payload = {f"campo_{index}": "x" for index in range(MAX_DECA_FIELDS + 1)}

    with pytest.raises(ValidationError):
        DocumentGenerateRequest(deca=payload)


def test_the_schema_caps_how_long_one_value_may_be() -> None:
    with pytest.raises(ValidationError):
        DocumentGenerateRequest(deca={"observaciones": "x" * (MAX_DECA_VALUE_CHARS + 1)})


def test_a_deca_value_may_not_be_a_nested_structure() -> None:
    """A list is a way to smuggle bulk past a per-value limit."""
    with pytest.raises(ValidationError):
        DocumentGenerateRequest(deca={"observaciones": ["x"] * 100_000})


def test_the_multipart_sidecar_is_bounded_like_the_json_body() -> None:
    """The ``deca`` form field used to skip every schema constraint."""
    payload = {f"campo_{index}": "x" for index in range(MAX_DECA_FIELDS + 1)}

    with pytest.raises(ValidationError):
        DecaSidecar(deca=payload)

    with pytest.raises(DomainError) as raised:
        documents_router._parse_deca(json.dumps(payload))
    assert raised.value.code == "VALIDATION_ERROR"


async def test_generating_a_deca_never_renders_an_unknown_field(
    db, catalogue, make_tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal has to happen before reportlab is handed anything.

    ``POST /documents/generate`` was the cheapest way to buy an unbounded amount
    of CPU with one authenticated request, and the size check that existed ran
    on the finished PDF - the one moment when refusing costs as much as
    accepting.
    """
    mm, site = await make_tenant()

    async def must_not_render(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the renderer was reached with unvalidated data")

    monkeypatch.setattr(documents_service.pdf, "render_deca_pdf_offloaded", must_not_render)

    with pytest.raises(DomainError) as raised:
        await documents_service.create_from_deca(
            db,
            _context(mm, site),
            deca={"origen": "Madrid", "relleno": "x" * 500},
        )

    assert raised.value.code == "DECA_FIELD_UNKNOWN"


def test_the_cost_of_a_render_is_priced_before_it_is_paid() -> None:
    """``_reject_oversized`` ran on the finished PDF, when refusing saves nothing."""
    huge = {f"campo_{index}": "x" * 1000 for index in range(200)}

    with pytest.raises(DomainError) as raised:
        documents_service._reject_expensive_render(huge, None)

    assert raised.value.code == "DECA_TOO_LARGE_TO_RENDER"
    assert raised.value.params["max_chars"] == documents_service.MAX_RENDER_CHARS


# --- E-09: a name must never be able to sink the document -------------------


def test_a_filename_with_crlf_cannot_reach_a_header() -> None:
    """``encode("ascii", "replace")`` left ``\\r`` and ``\\n`` alone: both are ASCII.

    The document was archived, listed, and then failed with a 500 on every
    download - for its owner and for the inspector scanning its QR.
    """
    value = content_disposition("inline", documents_service.header_filename(CRLF_FILENAME))

    assert not UVICORN_FORBIDDEN_IN_HEADER.search(value.encode("latin-1"))
    assert value.splitlines() == [value], "the header value must stay one line"


def test_a_filename_with_accents_still_downloads_intact() -> None:
    """RFC 5987 is why the guard replaces control characters instead of stripping."""
    value = content_disposition("inline", documents_service.header_filename(ACCENTED_FILENAME))
    encoded = value.split("filename*=UTF-8''")[1]

    assert unquote(encoded) == ACCENTED_FILENAME
    assert not UVICORN_FORBIDDEN_IN_HEADER.search(value.encode("latin-1"))


def test_an_empty_name_still_yields_a_usable_header() -> None:
    assert documents_service.header_filename("\r\n") == documents_service.FALLBACK_FILENAME
    assert documents_service.header_filename(None) == documents_service.FALLBACK_FILENAME


def test_the_schema_refuses_a_filename_with_control_characters() -> None:
    """Fix both ends: no new document gets a name that needs repairing."""
    with pytest.raises(ValidationError):
        DocumentGenerateRequest(deca={}, filename=CRLF_FILENAME)

    assert DocumentGenerateRequest(deca={}, filename=ACCENTED_FILENAME).filename


@pytest.fixture
def served_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve the archived file from memory: storage is not what is under test."""

    async def fake_open_stream(db: Any, document: Any) -> AsyncIterator[bytes]:
        async def chunks() -> AsyncIterator[bytes]:
            yield b"%PDF-1.4 contenido"

        return chunks()

    monkeypatch.setattr(documents_service, "open_stream", fake_open_stream)


@pytest.mark.parametrize("filename", [CRLF_FILENAME, ACCENTED_FILENAME])
async def test_the_public_viewer_serves_any_archived_name(
    client, db, make_tenant, make_document, make_share_token, served_bytes, filename: str
) -> None:
    """Documents archived before the fix have to become downloadable again."""
    mm, site = await make_tenant()
    document = await make_document(mm, site, filename=filename)
    share = await make_share_token(document)
    await db.flush()

    response = await client.get(f"/v/{share.token}/file")
    disposition = response.headers["Content-Disposition"]

    assert response.status_code == 200
    assert not UVICORN_FORBIDDEN_IN_HEADER.search(disposition.encode("latin-1"))


# --- E-07: the public PDF is served with the application's own headers ------


async def test_the_public_pdf_is_served_with_nosniff_and_a_policy(
    client, db, make_tenant, make_document, make_share_token, served_bytes
) -> None:
    """Neither header may depend on Traefik being in front of us.

    This is an attacker-supplied file served ``inline`` on the API's own origin.
    """
    mm, site = await make_tenant()
    document = await make_document(mm, site, filename="albaran.pdf")
    share = await make_share_token(document)
    await db.flush()

    response = await client.get(f"/v/{share.token}/file")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    policy = response.headers["Content-Security-Policy"]
    assert "default-src 'none'" in policy
    assert "sandbox" in policy


# --- E-11: HEAD is a consultation, and consultations are recorded -----------


async def _accesses(db: Any, document: Any) -> int:
    total = await db.scalar(
        select(func.count(DocumentAccess.id)).where(DocumentAccess.document_id == document.id)
    )
    return int(total or 0)


async def test_a_head_request_is_recorded_like_any_other_scan(
    client, db, make_tenant, make_document, make_share_token
) -> None:
    """It used to say 200 or 404 and leave nothing behind.

    That is two problems at once: a hole in the trail the tenant relies on as
    evidence, and an unlimited oracle for telling live tokens from revoked ones.
    """
    mm, site = await make_tenant()
    document = await make_document(mm, site, filename="albaran.pdf")
    share = await make_share_token(document)
    await db.flush()
    assert await _accesses(db, document) == 0

    response = await client.head(f"/v/{share.token}")

    assert response.status_code == 200
    assert await _accesses(db, document) == 1
    assert share.access_count == 1


async def test_head_answers_unknown_and_revoked_tokens_the_same_way(
    client, db, make_tenant, make_document, make_share_token
) -> None:
    """Recording the access must not have taught HEAD to distinguish them."""
    mm, site = await make_tenant()
    document = await make_document(mm, site, filename="albaran.pdf")
    revoked = await make_share_token(document, revoked=True)
    await db.flush()

    unknown_response = await client.head("/v/this-token-does-not-exist-at-all")
    revoked_response = await client.head(f"/v/{revoked.token}")

    assert unknown_response.status_code == revoked_response.status_code == 404
    assert await _accesses(db, document) == 0


# --- E-13: the export is the one door left wide open ------------------------


async def test_the_csv_export_stops_at_its_limit_and_says_so(
    db, make_tenant, make_document, make_storage_backend
) -> None:
    """It streamed the whole archive, holding a cursor and a pooled connection."""
    mm, site = await make_tenant()
    backend = await make_storage_backend(mm, site)
    for index in range(3):
        await make_document(mm, site, filename=f"albaran-{index}.pdf", backend=backend)
    await db.flush()

    ctx = _context(mm, site)
    rows = [line async for line in documents_service.export_csv(db, ctx, filters=None, limit=2)]

    assert len(rows) == 4, "header, two rows, and the truncation marker"
    assert rows[-1].startswith("# EXPORT_TRUNCATED")
    assert await documents_service.count_documents(db, ctx, filters=None) == 3


async def test_an_export_within_the_limit_carries_no_marker(
    db, make_tenant, make_document, make_storage_backend
) -> None:
    mm, site = await make_tenant()
    backend = await make_storage_backend(mm, site)
    await make_document(mm, site, filename="albaran.pdf", backend=backend)
    await db.flush()

    ctx = _context(mm, site)
    rows = [line async for line in documents_service.export_csv(db, ctx, filters=None, limit=5)]

    assert len(rows) == 2
    assert "EXPORT_TRUNCATED" not in rows[-1]


def test_the_export_route_is_bounded_at_all() -> None:
    """A regression guard on the constant itself: unbounded is the bug."""
    assert 0 < documents_service.EXPORT_ROW_LIMIT <= 100_000


# --- E-14: the multipart body is limited while it is being received ---------


def _multipart(parts: list[tuple[str, str | None, bytes]]) -> tuple[bytes, str]:
    boundary = "----estampa-test-boundary"
    chunks: list[bytes] = []
    for field, filename, data in parts:
        head = f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"'
        if filename is not None:
            head += f'; filename="{filename}"\r\nContent-Type: application/pdf'
        head += "\r\n\r\n"
        chunks.append(head.encode() + data + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class _Body:
    """An ASGI receive channel that records whether anyone read the body."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.read = False

    async def __call__(self) -> dict[str, Any]:
        if self.read:
            return {"type": "http.disconnect"}
        self.read = True
        return {"type": "http.request", "body": self.data, "more_body": False}


def _request(body: bytes, content_type: str, *, declare_length: bool) -> tuple[Request, _Body]:
    headers = [(b"content-type", content_type.encode())]
    if declare_length:
        headers.append((b"content-length", str(len(body)).encode()))
    channel = _Body(body)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/documents/",
        "headers": headers,
    }
    return Request(scope, channel), channel


def _tiny_limits() -> Settings:
    """One file of one megabyte, so the limits are reachable in a test."""
    return get_settings().model_copy(update={"max_files_per_upload": 1, "max_upload_mb": 1})


async def test_a_declared_body_over_the_limit_is_refused_without_reading_it() -> None:
    """The cheapest refusal there is: the claim in ``Content-Length``."""
    body, content_type = _multipart([("files", "grande.pdf", b"x" * (3 * 1024 * 1024))])
    request, channel = _request(body, content_type, declare_length=True)

    with pytest.raises(DomainError) as raised:
        await documents_router._parse_upload(request, _tiny_limits())

    assert raised.value.code == "UPLOAD_BODY_TOO_LARGE"
    assert raised.value.status_code == 413
    assert channel.read is False, "the body must not be read, let alone spooled to disk"


async def test_an_undeclared_body_over_the_limit_is_cut_off_as_it_arrives() -> None:
    """``Content-Length`` is a claim. A chunked body has none, and lying is free.

    The body arrives here as a single chunk, so the request-wide counter trips
    before the parser sees the part. The chunked case, where the per-file
    ceiling trips first, is in ``test_security_audit_2.py`` (audit N-07).
    """
    body, content_type = _multipart([("files", "grande.pdf", b"x" * (3 * 1024 * 1024))])
    request, _ = _request(body, content_type, declare_length=False)

    with pytest.raises(DomainError) as raised:
        await documents_router._parse_upload(request, _tiny_limits())

    assert raised.value.code == "UPLOAD_BODY_TOO_LARGE"


async def test_too_many_files_are_refused_while_the_body_is_still_arriving() -> None:
    """The count used to be checked after every part had been spooled to disk."""
    body, content_type = _multipart(
        [("files", "uno.pdf", b"%PDF-1.4 uno"), ("files", "dos.pdf", b"%PDF-1.4 dos")]
    )
    request, _ = _request(body, content_type, declare_length=True)

    with pytest.raises(DomainError) as raised:
        await documents_router._parse_upload(request, _tiny_limits())

    assert raised.value.code == "TOO_MANY_FILES"


async def test_an_oversized_text_part_is_refused_too() -> None:
    """The DECA sidecar is a form field, and form fields are capped by the parser."""
    body, content_type = _multipart(
        [("deca", None, b"x" * (documents_router.MAX_TEXT_PART_BYTES + 1024))]
    )
    request, _ = _request(body, content_type, declare_length=True)

    with pytest.raises(DomainError) as raised:
        await documents_router._parse_upload(request, _tiny_limits())

    assert raised.value.code == "UPLOAD_MALFORMED"


async def test_a_normal_upload_still_parses() -> None:
    """Limits that refuse a legitimate batch would be a worse bug than the one fixed."""
    body, content_type = _multipart(
        [("files", "albaran.pdf", b"%PDF-1.4 contenido"), ("deca", None, b'{"origen": "Madrid"}')]
    )
    request, _ = _request(body, content_type, declare_length=True)

    form = await documents_router._parse_upload(request, _tiny_limits())
    try:
        files = [value for value in form.getlist("files") if isinstance(value, UploadFile)]
        assert len(files) == 1
        assert documents_router._parse_deca(documents_router._form_text(form, "deca")) == {
            "origen": "Madrid"
        }
    finally:
        await form.close()


async def test_a_body_that_is_not_multipart_is_refused() -> None:
    request, _ = _request(b'{"files": []}', "application/json", declare_length=True)

    with pytest.raises(DomainError) as raised:
        await documents_router._parse_upload(request, _tiny_limits())

    assert raised.value.code == "UPLOAD_NOT_MULTIPART"


def test_fastapi_never_parses_the_upload_body_for_us() -> None:
    """The regression guard for E-14, and the reason the body is read by hand.

    A declared ``files: list[UploadFile]`` parameter has FastAPI parse and spool
    the whole multipart body before one line of the endpoint runs, which is the
    window a 50 GB POST filled the container's disk through. If this list ever
    stops being empty, every limit above has been bypassed again.
    """
    route = next(
        route
        for route in documents_router.router.routes
        if getattr(route, "path", None) == "/documents/"
        and "POST" in getattr(route, "methods", set())
    )

    assert route.dependant.body_params == []
    assert route.body_field is None
