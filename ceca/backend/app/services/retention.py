"""Retention. The file expires; the legal record never does.

When a period is up the PDF is removed from storage and the row stays behind
with ``withdrawn_at`` and a reason. Nothing is deleted from the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import TenantContext, scoped, scoped_select
from app.errors import DomainError, NotFoundError
from app.models.audit import AuditLog
from app.models.documents import Document, DocumentStatus, ShareToken
from app.models.retention import RetentionAction, RetentionPolicy
from app.services import audit
from app.services.storage import build_adapter
from app.services.storage.ownership import tenant_backend

#: The minimum period the Resolution of 5 June 2026 allows. See docs/DECA.md.
LEGAL_MINIMUM_DAYS = 365

WITHDRAWN_ACTION = "document.withdrawn_by_retention"
REVOKED_ACTION = "share.revoked_by_retention"
FLAGGED_ACTION = "document.flagged_by_retention"
WITHDRAWN_REASON = "retention"


@dataclass(frozen=True, slots=True)
class UpcomingExpiry:
    """A document the sweep will act on soon, so a human can step in first."""

    document_id: UUID
    original_filename: str
    expires_at: datetime
    days_left: int
    policy_id: UUID | None
    policy_name: str | None
    action: RetentionAction | None


async def policies_for_site(db: AsyncSession, ctx: TenantContext) -> list[RetentionPolicy]:
    stmt = (
        scoped_select(RetentionPolicy, ctx)
        .where(RetentionPolicy.is_active.is_(True))
        .order_by(RetentionPolicy.is_default.desc(), RetentionPolicy.name)
    )
    return list((await db.execute(stmt)).scalars().all())


async def compute_expiry(
    db: AsyncSession,
    ctx: TenantContext,
    *,
    uploaded_at: datetime,
    policy_id: UUID | None = None,
) -> tuple[UUID | None, datetime | None]:
    """The policy that governs a new document and the date its file expires."""
    if policy_id is not None:
        policy = await _policy(db, ctx, policy_id)
        return policy.id, uploaded_at + timedelta(days=policy.retention_days)

    policies = await policies_for_site(db, ctx)
    default = next((policy for policy in policies if policy.is_default), None)
    if default is None:
        fallback_days = get_settings().default_retention_days
        return None, uploaded_at + timedelta(days=fallback_days)
    return default.id, uploaded_at + timedelta(days=default.retention_days)


async def upcoming_expiries(
    db: AsyncSession,
    ctx: TenantContext,
    *,
    within_days: int = 30,
    offset: int = 0,
    limit: int = 25,
) -> tuple[list[UpcomingExpiry], int]:
    """What the sweep is about to withdraw, soonest first."""
    now = datetime.now(UTC)
    horizon = now + timedelta(days=within_days)
    conditions = (
        Document.expires_at.is_not(None),
        Document.expires_at <= horizon,
        Document.withdrawn_at.is_(None),
    )
    total = await db.scalar(
        scoped(select(func.count(Document.id)), ctx, Document).where(*conditions)
    )
    stmt = (
        scoped(select(Document, RetentionPolicy), ctx, Document)
        .outerjoin(RetentionPolicy, Document.retention_policy_id == RetentionPolicy.id)
        .where(*conditions)
        .order_by(Document.expires_at)
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    items = [
        _upcoming(document, policy, document.expires_at, now)
        for document, policy in rows
        # The query already excludes a null expiry. Restating it here keeps the
        # arithmetic below honest if anyone ever edits that filter.
        if document.expires_at is not None
    ]
    return items, int(total or 0)


def _upcoming(
    document: Document,
    policy: RetentionPolicy | None,
    expires_at: datetime,
    now: datetime,
) -> UpcomingExpiry:
    return UpcomingExpiry(
        document_id=document.id,
        original_filename=document.original_filename,
        expires_at=expires_at,
        days_left=max(0, (expires_at - now).days),
        policy_id=policy.id if policy else None,
        policy_name=policy.name if policy else None,
        action=RetentionAction(policy.action) if policy else None,
    )


async def _policy(db: AsyncSession, ctx: TenantContext, policy_id: UUID) -> RetentionPolicy:
    stmt = scoped_select(RetentionPolicy, ctx).where(RetentionPolicy.id == policy_id)
    policy = (await db.execute(stmt)).scalars().first()
    if policy is None:
        raise NotFoundError("RETENTION_POLICY_NOT_FOUND")
    return policy


def ensure_legal_minimum(retention_days: int) -> None:
    """A site may lengthen the period, never shorten it below the legal floor."""
    if retention_days < LEGAL_MINIMUM_DAYS:
        raise DomainError("RETENTION_BELOW_LEGAL_MINIMUM", minimum_days=LEGAL_MINIMUM_DAYS)


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


def _due_statement(now: datetime, limit: int) -> Select[tuple[Document, RetentionPolicy]]:
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
        select(
            Document, RetentionPolicy
        )  # tenant-exempt: nightly sweep runs across every tenant, it has no session
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
    if action == RetentionAction.FLAG_ONLY:
        await _log(db, document, FLAGGED_ACTION)
        return True
    if action == RetentionAction.REVOKE_SHARE:
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
    backend = await tenant_backend(db, document)
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
