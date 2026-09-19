"""The archive: upload, generate, complete, revise, withdraw, share and export."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser, MultipartPart

from app.config import Settings, get_settings
from app.deps import Db, Language, TenantContext, require_permission
from app.errors import DomainError, localised_message
from app.models.documents import (
    ComplianceStatus,
    DecaStatus,
    Document,
    DocumentOrigin,
    DocumentStatus,
)
from app.routers import ClientIpHash, Page, content_disposition
from app.schemas.common import Acknowledgement, ErrorDetail, PageResponse
from app.schemas.documents import (
    DecaPatchRequest,
    DecaSidecar,
    DocumentFilters,
    DocumentGenerateRequest,
    DocumentHistoryResponse,
    DocumentRead,
    DocumentSummary,
    RevisionCreateRequest,
    UploadItemResult,
    UploadResponse,
    UploadWarning,
    WithdrawRequest,
)
from app.services import documents as documents_service
from app.services import qr as qr_service
from app.services import quota as quota_service

router = APIRouter(prefix="/documents", tags=["documents"])

ReadCtx = Annotated[TenantContext, Depends(require_permission("documents:read"))]
CreateCtx = Annotated[TenantContext, Depends(require_permission("documents:create"))]
UpdateCtx = Annotated[TenantContext, Depends(require_permission("documents:update"))]
WithdrawCtx = Annotated[TenantContext, Depends(require_permission("documents:withdraw"))]
ExportCtx = Annotated[TenantContext, Depends(require_permission("documents:export"))]
RevokeCtx = Annotated[TenantContext, Depends(require_permission("share:revoke"))]

#: Non-file parts of an upload: the DECA sidecar and the retention policy.
MAX_FORM_FIELDS = 8
#: Bytes a non-file part may occupy. Enforced by the parser as it reads.
MAX_TEXT_PART_BYTES = 64 * 1024
#: Slack over the legitimate maximum, for boundaries and part headers.
UPLOAD_BODY_MARGIN_BYTES = 1024 * 1024

#: The multipart body is read by hand, so the request shape has to be described
#: by hand too. Declaring ``files: list[UploadFile]`` would have FastAPI parse
#: and spool the whole body before the first line of this module runs, which is
#: precisely the window a 50 GB POST used to fill the container disk through.
UPLOAD_REQUEST_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "files": {
                            "type": "array",
                            "items": {"type": "string", "format": "binary"},
                        },
                        "deca": {
                            "type": "string",
                            "description": "JSON object of DECA codes shared by the batch.",
                        },
                        "retention_policy_id": {"type": "string", "format": "uuid"},
                    },
                    "required": ["files"],
                }
            }
        },
    }
}


def _filters(
    search: Annotated[str | None, Query(max_length=255)] = None,
    status_: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    deca_status: DecaStatus | None = None,
    compliance_status: ComplianceStatus | None = None,
    origin: DocumentOrigin | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    expires_before: date | None = None,
    include_superseded: bool = False,
) -> DocumentFilters:
    return DocumentFilters(
        search=search,
        status=status_,
        deca_status=deca_status,
        compliance_status=compliance_status,
        origin=origin,
        created_from=created_from,
        created_to=created_to,
        expires_before=expires_before,
        include_superseded=include_superseded,
    )


Filters = Annotated[DocumentFilters, Depends(_filters)]


def _parse_deca(raw: str | None) -> dict[str, Any]:
    """The multipart sidecar carrying metadata common to the whole batch.

    It is JSON inside a form field, so it reaches us having skipped every bound
    the JSON endpoints get from their schema. It is put back through the same
    one here.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DomainError("VALIDATION_ERROR", status_code=422) from exc
    if not isinstance(parsed, dict):
        raise DomainError("VALIDATION_ERROR", status_code=422)
    try:
        sidecar = DecaSidecar(deca=parsed)
    except ValidationError as exc:
        raise DomainError("VALIDATION_ERROR", status_code=422) from exc
    return dict(sidecar.deca)


def _max_upload_body_bytes(settings: Settings) -> int:
    """The largest body this endpoint could legitimately need."""
    megabytes = settings.max_files_per_upload * settings.max_upload_mb
    return megabytes * 1024 * 1024 + UPLOAD_BODY_MARGIN_BYTES


def _body_too_large(size: int, maximum: int) -> DomainError:
    return DomainError(
        "UPLOAD_BODY_TOO_LARGE",
        status_code=413,
        size_mb=round(size / (1024 * 1024), 2),
        max_mb=round(maximum / (1024 * 1024)),
    )


async def _capped_stream(request: Request, maximum: int) -> AsyncGenerator[bytes, None]:
    """Feed the parser, and cut the request off the moment it overruns.

    ``Content-Length`` is checked first because it is free, but it is a claim,
    not a fact - a chunked body has none, and a lying one is trivial - so the
    real limit is this counter, applied to bytes as they arrive.
    """
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > maximum:
            raise _body_too_large(received, maximum)
        yield chunk


class _FilePartTooLarge(MultiPartException):
    def __init__(self, filename: str) -> None:
        super().__init__(f"File part {filename!r} exceeded the per-file limit.")
        self.filename = filename


class _BoundedMultiPartParser(MultiPartParser):
    """Starlette's parser, with a ceiling on each *file* part as it arrives.

    ``max_part_size`` only bounds parts without a filename; a part with one is
    spooled to disk without any limit of its own, so a single 500 MB "PDF" was
    written out in full before the service got to refuse it at 5 MB (audit
    N-07). Here the count runs in ``on_part_data``, on the bytes of the part
    seen so far, so the request is cut off at the limit, not after it.
    """

    def __init__(self, *args: Any, max_file_size: int, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.max_file_size = max_file_size
        self._file_bytes: dict[int, int] = {}

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        part: MultipartPart = self._current_part
        if part.file is not None:
            seen = self._file_bytes.get(id(part), 0) + (end - start)
            if seen > self.max_file_size:
                raise _FilePartTooLarge(part.file.filename or "")
            self._file_bytes[id(part)] = seen
        super().on_part_data(data, start, end)


async def _parse_upload(request: Request, settings: Settings) -> FormData:
    """Parse the multipart body under limits that apply while it is read."""
    if "multipart/form-data" not in request.headers.get("Content-Type", ""):
        raise DomainError("UPLOAD_NOT_MULTIPART", status_code=415)

    maximum = _max_upload_body_bytes(settings)
    declared = request.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > maximum:
        raise _body_too_large(int(declared), maximum)

    parser = _BoundedMultiPartParser(
        request.headers,
        _capped_stream(request, maximum),
        max_files=settings.max_files_per_upload,
        max_fields=MAX_FORM_FIELDS,
        max_part_size=MAX_TEXT_PART_BYTES,
        max_file_size=settings.max_upload_mb * 1024 * 1024,
    )
    try:
        return await parser.parse()
    except _FilePartTooLarge as exc:
        raise DomainError(
            "UPLOAD_FILE_TOO_LARGE",
            status_code=413,
            filename=exc.filename,
            max_mb=settings.max_upload_mb,
        ) from exc
    except MultiPartException as exc:
        if "Too many files" in str(exc):
            # The parser stops counting at the limit, so this is a floor.
            raise DomainError(
                "TOO_MANY_FILES",
                status_code=413,
                count=settings.max_files_per_upload + 1,
                max_files=settings.max_files_per_upload,
            ) from exc
        raise DomainError("UPLOAD_MALFORMED", status_code=400) from exc


def _form_text(form: FormData, name: str) -> str | None:
    value = form.get(name)
    return value if isinstance(value, str) and value else None


def _form_uuid(form: FormData, name: str) -> uuid.UUID | None:
    raw = _form_text(form, name)
    if raw is None:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise DomainError("VALIDATION_ERROR", status_code=422) from exc


async def _public_url(db: Db, document: Document) -> tuple[str | None, str | None]:
    share_token = await documents_service.active_share_token(db, document)
    if share_token is None:
        return None, None
    return share_token.token, qr_service.public_url(share_token.token)


async def _read(db: Db, document: Document) -> DocumentRead:
    token, url = await _public_url(db, document)
    return DocumentRead.model_validate(document).model_copy(
        update={"share_token": token, "public_url": url}
    )


def _failure(filename: str, exc: DomainError, language: str) -> UploadItemResult:
    return UploadItemResult(
        filename=filename,
        accepted=False,
        error=ErrorDetail(
            code=exc.code,
            message=localised_message(exc.code, language, exc.params),
            params=exc.params,
        ),
    )


@router.get("/", response_model=PageResponse[DocumentSummary])
async def list_documents(
    ctx: ReadCtx, db: Db, page: Page, filters: Filters
) -> PageResponse[DocumentSummary]:
    rows, total = await documents_service.list_documents(
        db, ctx, filters=filters, offset=page.offset, limit=page.limit
    )
    return PageResponse.of([DocumentSummary.model_validate(row) for row in rows], total, page)


@router.post(
    "/",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    openapi_extra=UPLOAD_REQUEST_BODY,
)
async def upload_documents(
    request: Request,
    ctx: CreateCtx,
    db: Db,
    language: Language,
    ip_hash: ClientIpHash,
) -> UploadResponse:
    """Multi-file upload. One bad file is one bad row, not a failed batch.

    The body is parsed here rather than declared as parameters so that the size
    and file-count limits apply *while* it is being received. Declared, FastAPI
    would have spooled every part to disk before this function existed.
    """
    settings = get_settings()
    form = await _parse_upload(request, settings)
    try:
        files = [value for value in form.getlist("files") if isinstance(value, UploadFile)]
        if not files:
            raise DomainError("VALIDATION_ERROR", status_code=422)
        metadata = _parse_deca(_form_text(form, "deca"))
        retention_policy_id = _form_uuid(form, "retention_policy_id")
        await quota_service.check_can_upload(db, ctx, count=len(files))

        items: list[UploadItemResult] = []
        for upload in files:
            filename = upload.filename or "sin-nombre.pdf"
            try:
                outcome = await documents_service.ingest_upload(
                    db,
                    ctx,
                    upload=upload,
                    filename=filename,
                    deca=metadata,
                    retention_policy_id=retention_policy_id,
                    actor_user_id=ctx.user_id,
                    ip_hash=ip_hash,
                )
            except DomainError as exc:
                items.append(_failure(filename, exc, language))
                continue
            items.append(
                UploadItemResult(
                    filename=filename,
                    accepted=True,
                    document=DocumentSummary.model_validate(outcome.document),
                    warnings=[
                        UploadWarning(code=warning.code, params=warning.params)
                        for warning in outcome.warnings
                    ],
                )
            )
    finally:
        await form.close()

    accepted = sum(1 for item in items if item.accepted)
    return UploadResponse(items=items, accepted=accepted, rejected=len(items) - accepted)


@router.post("/generate", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def generate_document(
    payload: DocumentGenerateRequest,
    ctx: CreateCtx,
    db: Db,
    ip_hash: ClientIpHash,
) -> DocumentRead:
    """The compliant path: a native PDF rendered from structured DECA data."""
    await quota_service.check_can_upload(db, ctx, count=1)
    document = await documents_service.create_from_deca(
        db,
        ctx,
        deca=payload.deca,
        filename=payload.filename,
        retention_policy_id=payload.retention_policy_id,
        actor_user_id=ctx.user_id,
        ip_hash=ip_hash,
    )
    return await _read(db, document)


@router.get("/export.csv")
async def export_documents(ctx: ExportCtx, db: Db, filters: Filters) -> StreamingResponse:
    """The archive as CSV, capped, with the cap stated in the response.

    Every other collection endpoint is bounded by ``MAX_PAGE_SIZE``; this one
    used to stream the whole archive, holding a cursor and one of twenty pooled
    connections for as long as that took. It is now bounded too, and the caller
    is told the total it matched so it can narrow ``created_from`` /
    ``created_to`` and walk the rest in slices.
    """
    limit = documents_service.EXPORT_ROW_LIMIT
    total = await documents_service.count_documents(db, ctx, filters=filters)
    rows = documents_service.export_csv(db, ctx, filters=filters, limit=limit)
    return StreamingResponse(
        rows,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": content_disposition("attachment", "albaranes.csv"),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Export-Total": str(total),
            "X-Export-Row-Limit": str(limit),
            "X-Export-Truncated": "true" if total > limit else "false",
        },
    )


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(document_id: uuid.UUID, ctx: ReadCtx, db: Db) -> DocumentRead:
    document = await documents_service.get_document(db, ctx, document_id)
    return await _read(db, document)


@router.patch("/{document_id}/deca", response_model=DocumentRead)
async def patch_deca(
    document_id: uuid.UUID,
    payload: DecaPatchRequest,
    ctx: UpdateCtx,
    db: Db,
    ip_hash: ClientIpHash,
) -> DocumentRead:
    document = await documents_service.update_deca(
        db,
        ctx,
        document_id,
        deca=payload.deca,
        expected_version=payload.version,
        actor_user_id=ctx.user_id,
        ip_hash=ip_hash,
    )
    return await _read(db, document)


@router.post(
    "/{document_id}/revisions",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_revision(
    document_id: uuid.UUID,
    payload: RevisionCreateRequest,
    ctx: UpdateCtx,
    db: Db,
    ip_hash: ClientIpHash,
) -> DocumentRead:
    """Apartado quinto: the old revision survives, marked superseded."""
    document = await documents_service.create_revision(
        db,
        ctx,
        document_id,
        change_reason=payload.change_reason,
        deca=payload.deca,
        actor_user_id=ctx.user_id,
        ip_hash=ip_hash,
    )
    return await _read(db, document)


@router.post("/{document_id}/withdraw", response_model=DocumentRead)
async def withdraw_document(
    document_id: uuid.UUID,
    payload: WithdrawRequest,
    ctx: WithdrawCtx,
    db: Db,
    ip_hash: ClientIpHash,
) -> DocumentRead:
    """The file leaves storage; the legal record stays."""
    document = await documents_service.withdraw(
        db,
        ctx,
        document_id,
        reason=payload.reason,
        actor_user_id=ctx.user_id,
        ip_hash=ip_hash,
    )
    return await _read(db, document)


@router.post("/{document_id}/share/revoke", response_model=Acknowledgement)
async def revoke_share(
    document_id: uuid.UUID, ctx: RevokeCtx, db: Db, ip_hash: ClientIpHash
) -> Acknowledgement:
    await documents_service.revoke_share(
        db, ctx, document_id, actor_user_id=ctx.user_id, ip_hash=ip_hash
    )
    return Acknowledgement()


@router.get("/{document_id}/qr.png")
async def document_qr_png(document_id: uuid.UUID, ctx: ReadCtx, db: Db) -> Response:
    document = await documents_service.get_document(db, ctx, document_id)
    _, url = await _public_url(db, document)
    if url is None:
        raise DomainError("SHARE_TOKEN_UNKNOWN", status_code=404)
    return Response(
        content=qr_service.qr_png(url),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{document_id}/qr.svg")
async def document_qr_svg(document_id: uuid.UUID, ctx: ReadCtx, db: Db) -> Response:
    document = await documents_service.get_document(db, ctx, document_id)
    _, url = await _public_url(db, document)
    if url is None:
        raise DomainError("SHARE_TOKEN_UNKNOWN", status_code=404)
    return Response(
        content=qr_service.qr_svg(url),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{document_id}/file")
async def download_document(document_id: uuid.UUID, ctx: ReadCtx, db: Db) -> StreamingResponse:
    """Authenticated streaming. The storage backend is never exposed."""
    document = await documents_service.get_document(db, ctx, document_id)
    stream = await documents_service.open_stream(db, document)
    return StreamingResponse(
        stream,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition(
                "inline", documents_service.header_filename(document.original_filename)
            ),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{document_id}/history", response_model=DocumentHistoryResponse)
async def document_history(document_id: uuid.UUID, ctx: ReadCtx, db: Db) -> DocumentHistoryResponse:
    """Revisions, printed copies and public QR scans, in one place."""
    history = await documents_service.history(db, ctx, document_id)
    return DocumentHistoryResponse.model_validate(history)
