"""Retention. The file expires; the legal record never does.

When a period is up the PDF is removed from storage and the row stays behind
with ``withdrawn_at`` and a reason. Nothing is deleted from the database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import TenantContext, scoped_select
from app.errors import DomainError
from app.models.audit import AuditLog
from app.models.documents import Document, DocumentStatus, ShareToken
from app.models.retention import RetentionAction, RetentionPolicy
from app.models.storage import StorageBackend
from app.services import audit
from app.services.storage import build_adapter

#: The minimum period the Resolution of 5 June 2026 allows. See docs/DECA.md.
LEGAL_MINIMUM_DAYS = 365

WITHDRAWN_ACTION = "document.withdrawn_by_retention"
REVOKED_ACTION = "share.revoked_by_retention"
FLAGGED_ACTION = "document.flagged_by_retention"
WITHDRAWN_REASON = "retention"


async def policies_for_site(
    db: AsyncSession, ctx: TenantContext
) -> list[RetentionPolicy]:
    stmt = (
        scoped_select(RetentionPolicy, ctx)
        .where(RetentionPolicy.is_active.is_(True))
        .order_by(RetentionPolicy.is_default.desc(), RetentionPolicy.name)
    )
    return list((await db.execute(stmt)).scalars().all())


async def compute_expiry(
    db: AsyncSession, ctx: TenantContext, *, uploaded_at: datetime
) -> tuple[UUID | None, datetime | None]:
    """The policy that governs a new document and the date its file expires."""
    policies = await policies_for_site(db, ctx)
    default = next((policy for policy in policies if policy.is_default), None)
    if default is None:
        fallback_days = get_settings().default_retention_days
        return None, uploaded_at + timedelta(days=fallback_days)
    return default.id, uploaded_at + timedelta(days=default.retention_days)


def ensure_legal_minimum(retention_days: int) -> None:
    """A site may lengthen the period, never shorten it below the legal floor."""
    if retention_days < LEGAL_MINIMUM_DAYS:
        raise DomainError(
            "RETENTION_BELOW_LEGAL_MINIMUM", minimum_days=LEGAL_MINIMUM_DAYS
        )


async def apply_due(db: AsyncSession, *, limit: int = 500) -> int:
    """Sweep every tenant's expired documents. Returns how many were acted on.

    This is the one place that reads ``documents`` across tenants: it runs from
    a scheduled job that belongs to no site, and every row it touches is written
    back under the mm_id and site_id it already carries.
    """
    now = datetime.now(UTC)
    rows = (await db.execute(_due_statement(now, limit))).all()

    processed = 0
    for document, policy in rows:
        action = RetentionAction(policy.action) if policy else RetentionAction.WITHDRAW_FILE
        if await _apply(db, document, action, now):
            processed += 1
    return processed


def _due_statement(now: datetime, limit: int):
    has_active_token = exists(
        select(ShareToken.id).where(
            ShareToken.document_id == Document.id, ShareToken.revoked_at.is_(None)
        )
    )
    already_flagged = exists(
        select(AuditLog.id).where(
            AuditLog.object_id == Document.id, AuditLog.action == FLAGGED_ACTION
        )
    )
    return (
        select(Document, RetentionPolicy)
        .outerjoin(RetentionPolicy, Document.retention_policy_id == RetentionPolicy.id)
        .where(
            Document.expires_at.is_not(None),
            Document.expires_at <= now,
            Document.withdrawn_at.is_(None),
            or_(
                RetentionPolicy.id.is_(None),
                RetentionPolicy.action == RetentionAction.WITHDRAW_FILE.value,
                and_(
                    RetentionPolicy.action == RetentionAction.REVOKE_SHARE.value,
                    has_active_token,
                ),
                and_(
                    RetentionPolicy.action == RetentionAction.FLAG_ONLY.value,
                    ~already_flagged,
                ),
            ),
        )
        .order_by(Document.expires_at)
        .limit(limit)
    )


async def _apply(
    db: AsyncSession, document: Document, action: RetentionAction, now: datetime
) -> bool:
    if action is RetentionAction.FLAG_ONLY:
        await _log(db, document, FLAGGED_ACTION)
        return True
    if action is RetentionAction.REVOKE_SHARE:
        await _revoke_tokens(db, document, now)
        await _log(db, document, REVOKED_ACTION)
        return True
    return await _withdraw(db, document, now)


async def _withdraw(db: AsyncSession, document: Document, now: datetime) -> bool:
    """Remove the file, keep the record. Retries next sweep if storage is down."""
    if not await _delete_file(db, document):
        return False
    await _revoke_tokens(db, document, now)
    document.withdrawn_at = now
    document.withdrawn_reason = WITHDRAWN_REASON
    document.status = DocumentStatus.WITHDRAWN
    await db.flush()
    await _log(db, document, WITHDRAWN_ACTION)
    return True


async def _delete_file(db: AsyncSession, document: Document) -> bool:
    backend = await db.get(StorageBackend, document.storage_backend_id)
    if backend is None:
        return True
    try:
        await build_adapter(backend).delete(document.storage_key)
    except DomainError:
        return False
    return True


async def _revoke_tokens(db: AsyncSession, document: Document, now: datetime) -> None:
    stmt = select(ShareToken).where(
        ShareToken.document_id == document.id, ShareToken.revoked_at.is_(None)
    )
    for token in (await db.execute(stmt)).scalars().all():
        token.revoked_at = now
    await db.flush()


async def _log(db: AsyncSession, document: Document, action: str) -> None:
    await audit.record(
        db,
        mm_id=document.mm_id,
        site_id=document.site_id,
        actor_user_id=None,
        action=action,
        object_type="document",
        object_id=document.id,
        payload={"expires_at": document.expires_at.isoformat() if document.expires_at else None},
    )
