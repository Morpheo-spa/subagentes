"""The document lifecycle: ingest, generate, revise, serve, withdraw.

Everything here stays inside one tenant. The only deliberate exception is
:func:`resolve_share_token`, which answers the public viewer and therefore has
no session to scope by.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import TenantContext, scoped_select
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
from app.models.storage import StorageBackend
from app.security import new_share_token
from app.services import audit, pdf, quota, retention
from app.services.deca import DecaValidator, FieldError
from app.services.qr import public_url
from app.services.storage import build_adapter

PDF_CONTENT_TYPE = "application/pdf"
MISSING_FIELD_CODE = "DECA_FIELD_REQUIRED"


async def ingest_upload(
    db: AsyncSession,
    ctx: TenantContext,
    *,
    filename: str,
    data: bytes,
    declared_content_type: str | None,
) -> Document:
    """Archive an uploaded PDF.

    The browser's content type is recorded but never trusted: the magic header
    decides. A file with no text layer is a scan, and a scan cannot be a DeCA,
    so it is archived and returned flagged ``NOT_A_DECA`` rather than rejected.
    The user decides what to do with it.
    """
    _reject_non_pdf(filename, data)
    _reject_oversized(filename, data)

    digest = hashlib.sha256(data).hexdigest()
    await _reject_duplicate(db, ctx, digest)
    await quota.check_can_upload(db, ctx, byte_size=len(data))

    backend = await default_backend(db, ctx)
    text_layer = pdf.has_text_layer(data)
    uploaded_at = datetime.now(UTC)
    policy_id, expires_at = await retention.compute_expiry(db, ctx, uploaded_at=uploaded_at)

    document = Document(
        id=uuid4(),
        mm_id=ctx.mm_id,
        site_id=ctx.site_id,
        original_filename=filename,
        storage_backend_id=backend.id,
        storage_key="",
        byte_size=len(data),
        sha256=digest,
        page_count=pdf.page_count(data),
        status=DocumentStatus.PROCESSING,
        deca={},
        deca_status=DecaStatus.INCOMPLETE if text_layer else DecaStatus.NOT_APPLICABLE,
        origin=DocumentOrigin.UPLOADED_NATIVE if text_layer else DocumentOrigin.UPLOADED_SCANNED,
        compliance_status=(
            ComplianceStatus.INCOMPLETE if text_layer else ComplianceStatus.NOT_A_DECA
        ),
        has_text_layer=text_layer,
        uploaded_by_id=_actor(ctx),
        retention_policy_id=policy_id,
        expires_at=expires_at,
    )
    document.storage_key = storage_key_for(ctx, document.id)
    db.add(document)
    await db.flush()

    await build_adapter(backend).put(document.storage_key, data, PDF_CONTENT_TYPE)
    document.status = DocumentStatus.READY
    await _issue_share_token(db, document)
    await quota.record_upload(db, ctx, byte_size=len(data))
    await _log(
        db,
        ctx,
        document,
        "document.uploaded",
        {
            "filename": filename,
            "declared_content_type": declared_content_type,
            "origin": document.origin.value,
            "compliance_status": document.compliance_status.value,
        },
    )
    return document


async def create_from_deca(
    db: AsyncSession, ctx: TenantContext, *, deca: dict, site_name: str
) -> Document:
    """Render a native DeCA from structured data and archive it."""
    return await _generate(db, ctx, deca=deca, site_name=site_name)


async def create_revision(
    db: AsyncSession,
    ctx: TenantContext,
    *,
    document_id: UUID,
    deca: dict,
    change_reason: str,
    site_name: str,
) -> Document:
    """Supersede a DeCA with a brand new file, keeping the original untouched.

    This is way B of the fifth section of the Resolution: a complete new file
    with its own URL and QR, while the original is preserved. Way A, rewriting
    the same file in place and marking the old values as not valid inside it, is
    not implemented: an immutable chain is easier to defend in an inspection and
    leaves the already printed labels pointing at a document that still exists.
    The superseded values are still printed struck through on the new file, so
    the reader sees what changed and why.
    """
    if not change_reason or not change_reason.strip():
        raise DomainError("CHANGE_REASON_REQUIRED")

    previous = await get_document(db, ctx, document_id)
    _reject_unrevisable(previous)

    revision = await _generate(
        db,
        ctx,
        deca=deca,
        site_name=site_name,
        previous=previous,
        change_reason=change_reason.strip(),
    )
    revision.revision = previous.revision + 1
    revision.supersedes_id = previous.id
    revision.change_reason = change_reason.strip()

    previous.superseded_at = datetime.now(UTC)
    previous.compliance_status = ComplianceStatus.SUPERSEDED
    await db.flush()

    await _log(
        db,
        ctx,
        previous,
        "document.superseded",
        {"superseded_by": str(revision.id), "change_reason": revision.change_reason},
    )
    return revision


async def get_document(
    db: AsyncSession, ctx: TenantContext, document_id: UUID
) -> Document:
    """A document of another tenant is indistinguishable from one that is gone."""
    stmt = scoped_select(Document, ctx).where(Document.id == document_id)
    document = (await db.execute(stmt)).scalars().first()
    if document is None:
        raise NotFoundError("DOCUMENT_NOT_FOUND")
    return document


async def withdraw(
    db: AsyncSession, ctx: TenantContext, *, document_id: UUID, reason: str
) -> Document:
    """Remove the file from storage and keep the record. Idempotent."""
    document = await get_document(db, ctx, document_id)
    if document.withdrawn_at is not None:
        return document

    backend = await db.get(StorageBackend, document.storage_backend_id)
    if backend is not None:
        await build_adapter(backend).delete(document.storage_key)

    now = datetime.now(UTC)
    await _revoke_tokens(db, document, now)
    document.withdrawn_at = now
    document.withdrawn_reason = reason
    document.status = DocumentStatus.WITHDRAWN
    await db.flush()
    await _log(db, ctx, document, "document.withdrawn", {"reason": reason})
    return document


async def open_stream(db: AsyncSession, document: Document) -> AsyncIterator[bytes]:
    """Stream the archived bytes. An async generator: iterate with ``async for``.

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

    backend = await db.get(StorageBackend, document.storage_backend_id)
    if backend is None:
        raise DomainError("STORAGE_NOT_CONFIGURED")

    async for chunk in build_adapter(backend).get_stream(document.storage_key):
        yield chunk


async def resolve_share_token(
    db: AsyncSession, token: str
) -> tuple[Document, ShareToken]:
    """Resolve a QR token for the public viewer.

    No tenant context exists here, by design. Unknown, revoked, expired and
    withdrawn all answer the same way, so the viewer cannot be used to probe
    which tokens ever existed.
    """
    stmt = select(ShareToken).where(ShareToken.token == token)
    share = (await db.execute(stmt)).scalars().first()
    if share is None or not _token_is_live(share):
        raise NotFoundError("SHARE_TOKEN_UNKNOWN")

    document = await db.get(Document, share.document_id)
    if document is None or document.withdrawn_at is not None:
        raise NotFoundError("SHARE_TOKEN_UNKNOWN")
    return document, share


async def record_public_access(
    db: AsyncSession,
    document: Document,
    share_token: ShareToken,
    *,
    ip_hash: str | None,
    user_agent: str | None,
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
    db: AsyncSession, ctx: TenantContext, *, document_id: UUID
) -> None:
    """Kill the published link. The file and the record stay where they are."""
    document = await get_document(db, ctx, document_id)
    revoked = await _revoke_tokens(db, document, datetime.now(UTC))
    if not revoked:
        raise DomainError("SHARE_ALREADY_REVOKED")
    await _log(db, ctx, document, "share.revoked", {"tokens": revoked})


async def active_share_token(
    db: AsyncSession, document_id: UUID
) -> ShareToken | None:
    """The live token of a document, for building its label URL."""
    stmt = (
        select(ShareToken)
        .where(ShareToken.document_id == document_id, ShareToken.revoked_at.is_(None))
        .order_by(ShareToken.created_at.desc())
    )
    return (await db.execute(stmt)).scalars().first()


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

    share = await active_share_token(db, document_id)
    if share is None:
        return False

    backend = await db.get(StorageBackend, document.storage_backend_id)
    if backend is None:
        raise DomainError("STORAGE_NOT_CONFIGURED")

    adapter = build_adapter(backend)
    original = b"".join([chunk async for chunk in adapter.get_stream(document.storage_key)])
    stamped = pdf.embed_qr(original, public_url(share.token))

    await adapter.put(document.storage_key, stamped, PDF_CONTENT_TYPE)
    document.byte_size = len(stamped)
    document.sha256 = hashlib.sha256(stamped).hexdigest()
    document.qr_embedded = True
    await db.flush()
    await _log(db, ctx, document, "document.qr_embedded", {})
    return True


async def _generate(
    db: AsyncSession,
    ctx: TenantContext,
    *,
    deca: dict,
    site_name: str,
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
        site_name=site_name,
        superseded=_changed_values(previous.deca, deca) if previous else None,
        change_reason=change_reason,
        language=ctx.locale,
    )
    await quota.check_can_upload(db, ctx, byte_size=len(rendered))
    _reject_oversized(f"{document_id}.pdf", rendered)

    backend = await default_backend(db, ctx)
    created_at = datetime.now(UTC)
    policy_id, expires_at = await retention.compute_expiry(db, ctx, uploaded_at=created_at)
    complete = not errors

    document = Document(
        id=document_id,
        mm_id=ctx.mm_id,
        site_id=ctx.site_id,
        original_filename=f"deca-{document_id}.pdf",
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
        compliance_status=(
            ComplianceStatus.COMPLIANT if complete else ComplianceStatus.INCOMPLETE
        ),
        has_text_layer=True,
        qr_embedded=True,
        uploaded_by_id=_actor(ctx),
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
        {"deca_status": document.deca_status.value, "supersedes": str(previous.id) if previous else None},
    )
    return document


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


def _token_is_live(share: ShareToken) -> bool:
    if share.revoked_at is not None:
        return False
    return share.expires_at is None or share.expires_at > datetime.now(UTC)


def _changed_values(previous: dict, current: dict) -> dict:
    """The old value of every field this revision actually changes."""
    return {
        code: value
        for code, value in (previous or {}).items()
        if current.get(code) != value
    }


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


async def _reject_duplicate(db: AsyncSession, ctx: TenantContext, digest: str) -> None:
    stmt = scoped_select(Document, ctx).where(
        Document.sha256 == digest, Document.withdrawn_at.is_(None)
    )
    existing = (await db.execute(stmt)).scalars().first()
    if existing is not None:
        raise ConflictError(
            "DUPLICATE_DOCUMENT", uploaded_at=existing.created_at.isoformat()
        )


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
            {"field": error.field, "code": error.code, "params": error.params}
            for error in invalid
        ],
        **first.params,
    )


async def _log(
    db: AsyncSession,
    ctx: TenantContext,
    document: Document,
    action: str,
    payload: dict,
) -> None:
    await audit.record(
        db,
        mm_id=ctx.mm_id,
        site_id=ctx.site_id,
        actor_user_id=_actor(ctx),
        action=action,
        object_type="document",
        object_id=document.id,
        payload=payload,
    )
