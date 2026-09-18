"""The archive: upload, generate, complete, revise, withdraw, share and export."""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.config import get_settings
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
    """The multipart sidecar carrying metadata common to the whole batch."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DomainError("VALIDATION_ERROR", status_code=422) from exc
    if not isinstance(parsed, dict):
        raise DomainError("VALIDATION_ERROR", status_code=422)
    return parsed


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
    return PageResponse.of(
        [DocumentSummary.model_validate(row) for row in rows], total, page
    )


@router.post(
    "/", response_model=UploadResponse, status_code=status.HTTP_201_CREATED
)
async def upload_documents(
    ctx: CreateCtx,
    db: Db,
    language: Language,
    ip_hash: ClientIpHash,
    files: Annotated[list[UploadFile], File()],
    deca: Annotated[str | None, Form()] = None,
    retention_policy_id: Annotated[uuid.UUID | None, Form()] = None,
) -> UploadResponse:
    """Multi-file upload. One bad file is one bad row, not a failed batch."""
    settings = get_settings()
    if len(files) > settings.max_files_per_upload:
        raise DomainError(
            "TOO_MANY_FILES",
            count=len(files),
            max_files=settings.max_files_per_upload,
        )
    await quota_service.check_can_upload(db, ctx, count=len(files))

    metadata = _parse_deca(deca)
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

    accepted = sum(1 for item in items if item.accepted)
    return UploadResponse(
        items=items, accepted=accepted, rejected=len(items) - accepted
    )


@router.post(
    "/generate", response_model=DocumentRead, status_code=status.HTTP_201_CREATED
)
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
    rows = documents_service.export_csv(db, ctx, filters=filters)
    return StreamingResponse(
        rows,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": content_disposition("attachment", "albaranes.csv"),
            "Cache-Control": "no-store",
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
async def download_document(
    document_id: uuid.UUID, ctx: ReadCtx, db: Db
) -> StreamingResponse:
    """Authenticated streaming. The storage backend is never exposed."""
    document = await documents_service.get_document(db, ctx, document_id)
    stream = await documents_service.open_stream(db, document)
    return StreamingResponse(
        stream,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition(
                "inline", document.original_filename
            ),
            "Cache-Control": "no-store",
        },
    )


@router.get("/{document_id}/history", response_model=DocumentHistoryResponse)
async def document_history(
    document_id: uuid.UUID, ctx: ReadCtx, db: Db
) -> DocumentHistoryResponse:
    """Revisions, printed copies and public QR scans, in one place."""
    history = await documents_service.history(db, ctx, document_id)
    return DocumentHistoryResponse.model_validate(history)
