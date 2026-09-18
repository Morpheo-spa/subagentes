"""The document lifecycle: ingest, generate, revise, serve, withdraw, export.

Everything here stays inside one tenant. The only deliberate exception is
:func:`resolve_share_token`, which answers the public viewer and therefore has
no session to scope by.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import TenantContext, scoped, scoped_select
from app.errors import ConflictError, DomainError, NotFoundError
from app.models.documents import (
    ComplianceStatus,
    DecaStatus,
    Document,
    DocumentAccess,
    DocumentOrigin,
    DocumentStatus,
    ShareToken,
)
from app.models.printing import PrintJob, PrintJobItem
from app.models.storage import StorageBackend
from app.models.tenancy import Site
from app.security import new_share_token
from app.services import audit, pdf, quota, retention
from app.services.deca import DecaValidator, FieldError
from app.services.qr import public_url
from app.services.storage import build_adapter
from app.services.storage.ownership import tenant_backend

PDF_CONTENT_TYPE = "application/pdf"
MISSING_FIELD_CODE = "DECA_FIELD_REQUIRED"
READ_CHUNK = 1024 * 1024
ACCESS_HISTORY_LIMIT = 200

CSV_COLUMNS = (
    "id",
    "original_filename",
    "status",
    "deca_status",
    "origin",
    "compliance_status",
    "revision",
    "byte_size",
    "page_count",
    "print_count",
    "created_at",
    "expires_at",
    "withdrawn_at",
    "superseded_at",
)


class UploadLike(Protocol):
    """Just enough of an upload to read it. The HTTP type never gets in here."""

    async def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True, slots=True)
class IngestWarning:
    """Something the user should know about a file that was archived anyway."""

    code: str
    params: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    document: Document
    warnings: list[IngestWarning] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ShareResolution:
    document: Document
    share_token: ShareToken
    site_name: str | None = None


@dataclass(frozen=True, slots=True)
class RevisionEntry:
    id: UUID
    revision: int
    change_reason: str | None
    created_at: datetime
    superseded_at: datetime | None
    is_current: bool


@dataclass(frozen=True, slots=True)
class PrintEntry:
    print_job_id: UUID
    copies: int
    template_code: str
    printed_at: datetime | None
    user_id: UUID | None


@dataclass(frozen=True, slots=True)
class PublicAccessEntry:
    accessed_at: datetime
    ip_hash: str | None
    user_agent: str | None


@dataclass(frozen=True, slots=True)
class DocumentHistory:
    document_id: UUID
    revisions: list[RevisionEntry]
    prints: list[PrintEntry]
    public_accesses: list[PublicAccessEntry]


async def list_documents(
    db: AsyncSession,
    ctx: TenantContext,
    *,
    filters: Any,
    offset: int = 0,
    limit: int = 25,
) -> tuple[list[Document], int]:
    """One page of the archive, plus the total the filters match."""
    conditions = _filter_conditions(filters)
    total = await db.scalar(
        scoped(select(func.count(Document.id)), ctx, Document).where(*conditions)
    )
    stmt = (
        scoped_select(Document, ctx)
        .where(*conditions)
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return rows, int(total or 0)


async def ingest_upload(
    db: AsyncSession,
    ctx: TenantContext,
    *,
    upload: UploadLike | None = None,
    filename: str,
    data: bytes | None = None,
    deca: dict | None = None,
    retention_policy_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    ip_hash: str | None = None,
    declared_content_type: str | None = None,
) -> IngestOutcome:
    """Archive an uploaded PDF.

    The browser's content type is recorded but never trusted: the magic header
    decides. A file with no text layer is a scan, and a scan cannot be a DeCA,
    so it is archived and flagged ``NOT_A_DECA`` rather than rejected: the user
    decides what to do with it. A duplicate is archived too, with a warning.
    """
    payload = data if data is not None else await _read_upload(upload, filename)
    _reject_non_pdf(filename, payload)

    digest = hashlib.sha256(payload).hexdigest()
    warnings: list[IngestWarning] = []
    duplicate = await _duplicate_of(db, ctx, digest)
    if duplicate is not None:
        warnings.append(
            IngestWarning(
                "DUPLICATE_DOCUMENT",
                {"uploaded_at": duplicate.created_at.isoformat()},
            )
        )

    await quota.check_can_upload(db, ctx, byte_size=len(payload), count=1)

    backend = await default_backend(db, ctx)
    text_layer = pdf.has_text_layer(payload)
    if not text_layer:
        warnings.append(IngestWarning("DOCUMENT_IS_A_SCAN", {"filename": filename}))

    validator = await DecaValidator.load(db)
    metadata = dict(deca or {})
    complete = bool(metadata) and validator.is_complete(metadata)

    uploaded_at = datetime.now(UTC)
    policy_id, expires_at = await retention.compute_expiry(
        db, ctx, uploaded_at=uploaded_at, policy_id=retention_policy_id
    )

    document = Document(
        id=uuid4(),
        mm_id=ctx.mm_id,
        site_id=ctx.site_id,
        original_filename=filename,
        storage_backend_id=backend.id,
        storage_key="",
        byte_size=len(payload),
        sha256=digest,
        page_count=pdf.page_count(payload),
        status=DocumentStatus.PROCESSING,
        deca=metadata,
        deca_status=_deca_status(text_layer, complete),
        deca_catalog_version=validator.catalog_version,
        origin=(DocumentOrigin.UPLOADED_NATIVE if text_layer else DocumentOrigin.UPLOADED_SCANNED),
        compliance_status=ComplianceStatus.INCOMPLETE,
        has_text_layer=text_layer,
        uploaded_by_id=actor_user_id or _actor(ctx),
        retention_policy_id=policy_id,
        expires_at=expires_at,
    )
    document.storage_key = storage_key_for(ctx, document.id)
    _recompute_compliance(document)
    db.add(document)
    await db.flush()

    await build_adapter(backend).put(document.storage_key, payload, PDF_CONTENT_TYPE)
    document.status = DocumentStatus.READY
    await _issue_share_token(db, document)
    await quota.record_upload(db, ctx, byte_size=len(payload))
    await _log(
        db,
        ctx,
        document,
        "document.uploaded",
        {
            "filename": filename,
            "declared_content_type": declared_content_type,
            "origin": DocumentOrigin(document.origin).value,
            "warnings": [warning.code for warning in warnings],
        },
        actor_user_id=actor_user_id,
        ip_hash=ip_hash,
    )
    return IngestOutcome(document=document, warnings=warnings)


async def create_from_deca(
    db: AsyncSession,
    ctx: TenantContext,
    *,
    deca: dict,
    filename: str | None = None,
    site_name: str | None = None,
    retention_policy_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    ip_hash: str | None = None,
) -> Document:
    """Render a native DeCA from structured data and archive it."""
    return await _generate(
        db,
        ctx,
        deca=deca,
        filename=filename,
        site_name=site_name,
        retention_policy_id=retention_policy_id,
        actor_user_id=actor_user_id,
        ip_hash=ip_hash,
    )


async def create_revision(
    db: AsyncSession,
    ctx: TenantContext,
    document_id: UUID,
    *,
    change_reason: str,
    deca: dict | None = None,
    site_name: str | None = None,
    actor_user_id: UUID | None = None,
    ip_hash: str | None = None,
) -> Document:
    """Supersede a DeCA with a brand new file, keeping the original untouched.

    This is way B of the fifth section of the Resolution: a complete new file
    with its own URL and QR, while the original is preserved. Way A, rewriting
    the same file in place and marking the old values as not valid inside it, is
    not implemented: an immutable chain is easier to defend in an inspection and
    leaves already printed labels pointing at a document that still exists. The
    superseded values are still printed struck through on the new file, so the
    reader sees what changed and why.
    """
    if not change_reason or not change_reason.strip():
        raise DomainError("CHANGE_REASON_REQUIRED")

    previous = await get_document(db, ctx, document_id)
    _reject_unrevisable(previous)
    reason = change_reason.strip()

    revision = await _generate(
        db,
        ctx,
        deca=dict(deca) if deca is not None else dict(previous.deca or {}),
        filename=None,
        site_name=site_name,
        retention_policy_id=previous.retention_policy_id,
        actor_user_id=actor_user_id,
        ip_hash=ip_hash,
        previous=previous,
        change_reason=reason,
    )
    revision.revision = previous.revision + 1
    revision.supersedes_id = previous.id
    revision.change_reason = reason

    previous.superseded_at = datetime.now(UTC)
    previous.compliance_status = ComplianceStatus.SUPERSEDED
    await db.flush()

    await _log(
        db,
        ctx,
        previous,
        "document.superseded",
        {"superseded_by": str(revision.id), "change_reason": reason},
        actor_user_id=actor_user_id,
        ip_hash=ip_hash,
    )
    return revision


async def update_deca(
    db: AsyncSession,
    ctx: TenantContext,
    document_id: UUID,
    *,
    deca: dict,
    expected_version: int | None = None,
    actor_user_id: UUID | None = None,
    ip_hash: str | None = None,
) -> Document:
    """Complete or correct the metadata of an archived upload.

    A PDF we rendered ourselves cannot be patched: its data is printed on its
    face, so changing it means a new revision.
    """
    document = await get_document(db, ctx, document_id)
    _reject_unrevisable(document)
    if DocumentOrigin(document.origin) is DocumentOrigin.GENERATED:
        raise DomainError("DECA_EDIT_REQUIRES_REVISION", status_code=409)
    if expected_version is not None and expected_version != document.version:
        raise ConflictError("VERSION_CONFLICT")

    validator = await DecaValidator.load(db)
    merged = {**(document.deca or {}), **deca}
    errors = validator.validate(merged)
    _reject_invalid_values(errors)

    document.deca = merged
    document.deca_status = _deca_status(bool(document.has_text_layer), not errors)
    document.deca_catalog_version = validator.catalog_version
    _recompute_compliance(document)
    await db.flush()

    await _log(
        db,
        ctx,
        document,
        "document.deca_updated",
        {"fields": sorted(deca)},
        actor_user_id=actor_user_id,
        ip_hash=ip_hash,
    )
    return document


async def get_document(db: AsyncSession, ctx: TenantContext, document_id: UUID) -> Document:
    """A document of another tenant is indistinguishable from one that is gone."""
    stmt = scoped_select(Document, ctx).where(Document.id == document_id)
    document = (await db.execute(stmt)).scalars().first()
    if document is None:
        raise NotFoundError("DOCUMENT_NOT_FOUND")
    return document


async def withdraw(
    db: AsyncSession,
    ctx: TenantContext,
    document_id: UUID,
    *,
    reason: str,
    actor_user_id: UUID | None = None,
    ip_hash: str | None = None,
) -> Document:
    """Remove the file from storage and keep the record. Idempotent."""
    document = await get_document(db, ctx, document_id)
    if document.withdrawn_at is not None:
        return document

    backend = await tenant_backend(db, document)
    if backend is not None:
        await build_adapter(backend).delete(document.storage_key)

    now = datetime.now(UTC)
    await _revoke_tokens(db, document, now)
    document.withdrawn_at = now
    document.withdrawn_reason = reason
    document.status = DocumentStatus.WITHDRAWN
    await db.flush()
    await _log(
        db,
        ctx,
        document,
        "document.withdrawn",
        {"reason": reason},
        actor_user_id=actor_user_id,
        ip_hash=ip_hash,
    )
    return document


async def open_stream(db: AsyncSession, document: Document) -> AsyncIterator[bytes]:
    """Return an async iterator over the archived bytes.

    The storage URL is never handed out, not even signed: every byte the public
    sees comes through the API.
    """
    if document.withdrawn_at is not None:
        raise DomainError(
            "DOCUMENT_WITHDRAWN",
            status_code=410,
            withdrawn_at=document.withdrawn_at.isoformat(),
        )
    if DocumentStatus(document.status) is not DocumentStatus.READY:
        raise DomainError("DOCUMENT_NOT_READY", status_code=409)

    backend = await tenant_backend(db, document)
    if backend is None:
        raise DomainError("STORAGE_NOT_CONFIGURED")
    return build_adapter(backend).get_stream(document.storage_key)


async def export_csv(db: AsyncSession, ctx: TenantContext, *, filters: Any) -> AsyncIterator[str]:
    """Stream the archive as CSV rows, header first. One row per document."""
    validator = await DecaValidator.load(db)
    codes = [spec.code for spec in validator.specs]
    yield _csv_line([*CSV_COLUMNS, *codes])

    conditions = _filter_conditions(filters)
    stmt = scoped_select(Document, ctx).where(*conditions).order_by(Document.created_at.desc())
    result = await db.stream(stmt)
    async for document in result.scalars():
        yield _csv_line(_csv_row(document, codes))


async def history(db: AsyncSession, ctx: TenantContext, document_id: UUID) -> DocumentHistory:
    """Revisions, printed copies and public scans of one document."""
    document = await get_document(db, ctx, document_id)
    return DocumentHistory(
        document_id=document.id,
        revisions=await _revisions_of(db, ctx, document),
        prints=await _prints_of(db, document),
        public_accesses=await _accesses_of(db, document),
    )


async def resolve_share_token(db: AsyncSession, token: str) -> ShareResolution | None:
    """Resolve a QR token for the public viewer, or None.

    No tenant context exists here, by design. Unknown, revoked and expired all
    answer the same way, so the viewer cannot be used to probe which tokens ever
    existed.
    """
    stmt = select(ShareToken).where(ShareToken.token == token)
    share = (await db.execute(stmt)).scalars().first()
    if share is None or not _token_is_live(share):
        return None

    document = await db.get(
        Document, share.document_id
    )  # tenant-exempt: public QR viewer resolves by secret token, it has no session
    if document is None:
        return None

    site = await db.get(Site, document.site_id)
    return ShareResolution(
        document=document,
        share_token=share,
        site_name=site.name if site else None,
    )


async def record_public_access(
    db: AsyncSession,
    *,
    document: Document,
    share_token: ShareToken,
    ip_hash: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Log a QR scan. The IP arrives already hashed; the raw one never gets here."""
    now = datetime.now(UTC)
    db.add(
        DocumentAccess(
            document_id=document.id,
            share_token_id=share_token.id,
            accessed_at=now,
            ip_hash=ip_hash,
            user_agent=user_agent,
        )
    )
    share_token.access_count += 1
    share_token.last_accessed_at = now
    await db.flush()


async def revoke_share(
    db: AsyncSession,
    ctx: TenantContext,
    document_id: UUID,
    *,
    actor_user_id: UUID | None = None,
    ip_hash: str | None = None,
) -> None:
    """Kill the published link. The file and the record stay where they are."""
    document = await get_document(db, ctx, document_id)
    revoked = await _revoke_tokens(db, document, datetime.now(UTC))
    if not revoked:
        raise DomainError("SHARE_ALREADY_REVOKED")
    await _log(
        db,
        ctx,
        document,
        "share.revoked",
        {"tokens": revoked},
        actor_user_id=actor_user_id,
        ip_hash=ip_hash,
    )


async def active_share_token(db: AsyncSession, document: Document | UUID) -> ShareToken | None:
    """The live token of a document, for building its label URL."""
    document_id = document if isinstance(document, UUID) else document.id
    stmt = (
        select(ShareToken)
        .where(ShareToken.document_id == document_id, ShareToken.revoked_at.is_(None))
        .order_by(ShareToken.created_at.desc())
    )
    for share in (await db.execute(stmt)).scalars().all():
        if _token_is_live(share):
            return share
    return None


async def default_backend(db: AsyncSession, ctx: TenantContext) -> StorageBackend:
    stmt = (
        scoped_select(StorageBackend, ctx)
        .where(StorageBackend.is_active.is_(True))
        .order_by(StorageBackend.is_default.desc(), StorageBackend.created_at)
    )
    backend = (await db.execute(stmt)).scalars().first()
    if backend is None:
        raise DomainError("STORAGE_NOT_CONFIGURED")
    return backend


def storage_key_for(ctx: TenantContext, document_id: UUID) -> str:
    """The file is named after the GUID. The original name only lives in the row."""
    return f"{ctx.mm_id}/{ctx.site_id}/{document_id}.pdf"


async def stamp_qr(db: AsyncSession, ctx: TenantContext, document_id: UUID) -> bool:
    """Embed the QR into a natively uploaded PDF. Idempotent.

    Returns False when there is nothing to do, which is what makes the actor
    that calls it safe to retry.
    """
    document = await get_document(db, ctx, document_id)
    if document.qr_embedded or document.withdrawn_at is not None:
        return False
    if not document.has_text_layer:
        return False

    share = await active_share_token(db, document)
    if share is None:
        return False

    backend = await tenant_backend(db, document)
    if backend is None:
        raise DomainError("STORAGE_NOT_CONFIGURED")

    adapter = build_adapter(backend)
    original = b"".join([chunk async for chunk in adapter.get_stream(document.storage_key)])
    stamped = pdf.embed_qr(original, public_url(share.token))

    await adapter.put(document.storage_key, stamped, PDF_CONTENT_TYPE)
    document.byte_size = len(stamped)
    document.sha256 = hashlib.sha256(stamped).hexdigest()
    document.qr_embedded = True
    _recompute_compliance(document)
    await db.flush()
    await _log(db, ctx, document, "document.qr_embedded", {})
    return True


async def _generate(
    db: AsyncSession,
    ctx: TenantContext,
    *,
    deca: dict,
    filename: str | None,
    site_name: str | None,
    retention_policy_id: UUID | None,
    actor_user_id: UUID | None,
    ip_hash: str | None,
    previous: Document | None = None,
    change_reason: str | None = None,
) -> Document:
    validator = await DecaValidator.load(db)
    errors = validator.validate(deca)
    _reject_invalid_values(errors)

    document_id = uuid4()
    token = new_share_token()
    rendered = pdf.render_deca_pdf(
        deca,
        qr_url=public_url(token),
        document_id=document_id,
        site_name=site_name or await _site_name(db, ctx),
        superseded=_changed_values(previous.deca, deca) if previous else None,
        change_reason=change_reason,
        language=ctx.locale,
    )
    await quota.check_can_upload(db, ctx, byte_size=len(rendered), count=1)
    _reject_oversized(f"{document_id}.pdf", rendered)

    backend = await default_backend(db, ctx)
    created_at = datetime.now(UTC)
    policy_id, expires_at = await retention.compute_expiry(
        db, ctx, uploaded_at=created_at, policy_id=retention_policy_id
    )
    complete = not errors

    document = Document(
        id=document_id,
        mm_id=ctx.mm_id,
        site_id=ctx.site_id,
        original_filename=filename or f"deca-{document_id}.pdf",
        storage_backend_id=backend.id,
        storage_key=storage_key_for(ctx, document_id),
        byte_size=len(rendered),
        sha256=hashlib.sha256(rendered).hexdigest(),
        page_count=pdf.page_count(rendered),
        status=DocumentStatus.PROCESSING,
        deca=deca,
        deca_status=DecaStatus.COMPLETE if complete else DecaStatus.INCOMPLETE,
        deca_catalog_version=validator.catalog_version,
        origin=DocumentOrigin.GENERATED,
        compliance_status=(ComplianceStatus.COMPLIANT if complete else ComplianceStatus.INCOMPLETE),
        has_text_layer=True,
        qr_embedded=True,
        uploaded_by_id=actor_user_id or _actor(ctx),
        retention_policy_id=policy_id,
        expires_at=expires_at,
    )
    db.add(document)
    await db.flush()

    await build_adapter(backend).put(document.storage_key, rendered, PDF_CONTENT_TYPE)
    document.status = DocumentStatus.READY
    await _issue_share_token(db, document, token=token)
    await quota.record_upload(db, ctx, byte_size=len(rendered))
    await _log(
        db,
        ctx,
        document,
        "document.generated",
        {
            "deca_status": DecaStatus(document.deca_status).value,
            "supersedes": str(previous.id) if previous else None,
        },
        actor_user_id=actor_user_id,
        ip_hash=ip_hash,
    )
    return document


async def _read_upload(upload: UploadLike | None, filename: str) -> bytes:
    """Read the upload in chunks, refusing it the moment it is too big."""
    if upload is None:
        raise DomainError("DOCUMENT_NOT_PDF", filename=filename)

    maximum = get_settings().max_upload_mb * 1024 * 1024
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await upload.read(READ_CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > maximum:
            raise DomainError(
                "DOCUMENT_TOO_LARGE",
                status_code=413,
                filename=filename,
                size_mb=round(size / (1024 * 1024), 2),
                max_mb=get_settings().max_upload_mb,
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _site_name(db: AsyncSession, ctx: TenantContext) -> str:
    site = await db.get(Site, ctx.site_id)
    return site.name if site else ""


async def _issue_share_token(
    db: AsyncSession, document: Document, *, token: str | None = None
) -> ShareToken:
    share = ShareToken(document_id=document.id, token=token or new_share_token())
    db.add(share)
    await db.flush()
    return share


async def _revoke_tokens(db: AsyncSession, document: Document, now: datetime) -> int:
    stmt = select(ShareToken).where(
        ShareToken.document_id == document.id, ShareToken.revoked_at.is_(None)
    )
    tokens = (await db.execute(stmt)).scalars().all()
    for token in tokens:
        token.revoked_at = now
    await db.flush()
    return len(tokens)


async def _revisions_of(
    db: AsyncSession, ctx: TenantContext, document: Document
) -> list[RevisionEntry]:
    chain = {document.id: document}

    current = document
    while current.supersedes_id and current.supersedes_id not in chain:
        stmt = scoped_select(Document, ctx).where(Document.id == current.supersedes_id)
        previous = (await db.execute(stmt)).scalars().first()
        if previous is None:
            break
        chain[previous.id] = previous
        current = previous

    pending = [document.id]
    while pending:
        stmt = scoped_select(Document, ctx).where(Document.supersedes_id.in_(pending))
        successors = (await db.execute(stmt)).scalars().all()
        pending = [row.id for row in successors if row.id not in chain]
        chain.update({row.id: row for row in successors})

    return [
        RevisionEntry(
            id=row.id,
            revision=row.revision,
            change_reason=row.change_reason,
            created_at=row.created_at,
            superseded_at=row.superseded_at,
            is_current=row.superseded_at is None and row.withdrawn_at is None,
        )
        for row in sorted(chain.values(), key=lambda row: row.revision)
    ]


async def _prints_of(db: AsyncSession, document: Document) -> list[PrintEntry]:
    stmt = (
        select(PrintJobItem, PrintJob)
        .join(PrintJob, PrintJobItem.print_job_id == PrintJob.id)
        .where(PrintJobItem.document_id == document.id)
        .order_by(PrintJob.created_at.desc())
    )
    return [
        PrintEntry(
            print_job_id=job.id,
            copies=item.copies,
            template_code=job.template_code,
            printed_at=job.confirmed_at,
            user_id=job.user_id,
        )
        for item, job in (await db.execute(stmt)).all()
    ]


async def _accesses_of(db: AsyncSession, document: Document) -> list[PublicAccessEntry]:
    stmt = (
        select(DocumentAccess)
        .where(DocumentAccess.document_id == document.id)
        .order_by(DocumentAccess.accessed_at.desc())
        .limit(ACCESS_HISTORY_LIMIT)
    )
    return [
        PublicAccessEntry(
            accessed_at=row.accessed_at,
            ip_hash=row.ip_hash,
            user_agent=row.user_agent,
        )
        for row in (await db.execute(stmt)).scalars().all()
    ]


def _filter_conditions(filters: Any) -> list:
    conditions = []
    search = _filter(filters, "search")
    if search:
        pattern = f"%{search}%"
        conditions.append(
            or_(
                Document.original_filename.ilike(pattern),
                cast(Document.id, String).ilike(pattern),
            )
        )
    for attribute, column in (
        ("status", Document.status),
        ("deca_status", Document.deca_status),
        ("compliance_status", Document.compliance_status),
        ("origin", Document.origin),
    ):
        value = _filter(filters, attribute)
        if value is not None:
            conditions.append(column == getattr(value, "value", value))

    since = _filter(filters, "created_from") or _filter(filters, "uploaded_from")
    if since:
        conditions.append(Document.created_at >= _start_of(since))
    until = _filter(filters, "created_to") or _filter(filters, "uploaded_to")
    if until:
        conditions.append(Document.created_at <= _end_of(until))
    expires_before = _filter(filters, "expires_before")
    if expires_before:
        conditions.append(Document.expires_at <= _end_of(expires_before))

    if not _filter(filters, "include_superseded"):
        conditions.append(Document.superseded_at.is_(None))
    return conditions


def _filter(filters: Any, name: str) -> Any:
    if filters is None:
        return None
    if isinstance(filters, dict):
        return filters.get(name)
    return getattr(filters, name, None)


def _start_of(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.min, tzinfo=UTC)


def _end_of(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.max, tzinfo=UTC)


def _csv_line(values: list[str]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerow(values)
    return buffer.getvalue()


def _csv_row(document: Document, codes: list[str]) -> list[str]:
    row = [_csv_value(getattr(document, column, None)) for column in CSV_COLUMNS]
    metadata = document.deca or {}
    return row + [_csv_value(metadata.get(code)) for code in codes]


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(getattr(value, "value", value))


def _deca_status(has_text_layer: bool, complete: bool) -> DecaStatus:
    if not has_text_layer:
        return DecaStatus.NOT_APPLICABLE
    return DecaStatus.COMPLETE if complete else DecaStatus.INCOMPLETE


def _recompute_compliance(document: Document) -> None:
    """A scan is never a DeCA; anything else needs full data and an embedded QR."""
    if DocumentOrigin(document.origin) is DocumentOrigin.UPLOADED_SCANNED:
        document.compliance_status = ComplianceStatus.NOT_A_DECA
        return
    if document.superseded_at is not None:
        document.compliance_status = ComplianceStatus.SUPERSEDED
        return
    is_complete = DecaStatus(document.deca_status) is DecaStatus.COMPLETE
    document.compliance_status = (
        ComplianceStatus.COMPLIANT
        if is_complete and document.qr_embedded
        else ComplianceStatus.INCOMPLETE
    )


def _token_is_live(share: ShareToken) -> bool:
    if share.revoked_at is not None:
        return False
    return share.expires_at is None or share.expires_at > datetime.now(UTC)


def _changed_values(previous: dict | None, current: dict) -> dict:
    """The old value of every field this revision actually changes."""
    return {code: value for code, value in (previous or {}).items() if current.get(code) != value}


def _actor(ctx: TenantContext) -> UUID | None:
    """A background job has no user behind it."""
    return None if ctx.user_id == audit.SYSTEM_ACTOR_ID else ctx.user_id


def _reject_non_pdf(filename: str, data: bytes) -> None:
    if not pdf.is_pdf(data):
        raise DomainError("DOCUMENT_NOT_PDF", filename=filename)


def _reject_oversized(filename: str, data: bytes) -> None:
    max_mb = get_settings().max_upload_mb
    if len(data) > max_mb * 1024 * 1024:
        raise DomainError(
            "DOCUMENT_TOO_LARGE",
            status_code=413,
            filename=filename,
            size_mb=round(len(data) / (1024 * 1024), 2),
            max_mb=max_mb,
        )


async def _duplicate_of(db: AsyncSession, ctx: TenantContext, digest: str) -> Document | None:
    stmt = scoped_select(Document, ctx).where(
        Document.sha256 == digest, Document.withdrawn_at.is_(None)
    )
    return (await db.execute(stmt)).scalars().first()


def _reject_unrevisable(document: Document) -> None:
    if document.withdrawn_at is not None:
        raise DomainError(
            "DOCUMENT_WITHDRAWN",
            status_code=410,
            withdrawn_at=document.withdrawn_at.isoformat(),
        )
    if document.superseded_at is not None:
        raise DomainError(
            "DOCUMENT_SUPERSEDED",
            status_code=409,
            superseded_at=document.superseded_at.isoformat(),
        )


def _reject_invalid_values(errors: list[FieldError]) -> None:
    """Missing data only marks the DeCA incomplete; wrong data is refused.

    The first bad field decides the message; the whole list travels in
    ``fields`` so the form can mark every one of them at once.
    """
    invalid = [error for error in errors if error.code != MISSING_FIELD_CODE]
    if not invalid:
        return
    first = invalid[0]
    raise DomainError(
        first.code,
        status_code=422,
        fields=[
            {"field": error.field, "code": error.code, "params": error.params} for error in invalid
        ],
        **first.params,
    )


async def _log(
    db: AsyncSession,
    ctx: TenantContext,
    document: Document,
    action: str,
    payload: dict,
    *,
    actor_user_id: UUID | None = None,
    ip_hash: str | None = None,
) -> None:
    await audit.record(
        db,
        mm_id=ctx.mm_id,
        site_id=ctx.site_id,
        actor_user_id=actor_user_id or _actor(ctx),
        action=action,
        object_type="document",
        object_id=document.id,
        payload=payload,
        ip_hash=ip_hash,
    )
