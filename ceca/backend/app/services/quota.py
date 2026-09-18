"""Plan limits and monthly consumption.

With ``BILLING_ENABLED`` off every limit is unlimited and no quota error is ever
raised; usage is still counted, because the numbers are useful on their own.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import TenantContext
from app.errors import QuotaExceededError
from app.models.billing import Plan, Subscription, UsageCounter

#: A limit of -1 means unlimited.
UNLIMITED = -1
BYTES_PER_GB = 1024**3

DEFAULT_LIMITS: dict[str, int] = {
    "documents_per_month": UNLIMITED,
    "storage_gb": UNLIMITED,
    "users": UNLIMITED,
    "sites": UNLIMITED,
}


def current_period(moment: datetime | None = None) -> str:
    return (moment or datetime.now(UTC)).strftime("%Y-%m")


async def limits_for(db: AsyncSession, mm_id: UUID) -> dict:
    """The plan's limits with the subscription's overrides applied on top."""
    if not get_settings().billing_enabled:
        return dict(DEFAULT_LIMITS)

    subscription = await _subscription(db, mm_id)
    if subscription is None:
        return dict(DEFAULT_LIMITS)

    plan = await db.get(Plan, subscription.plan_code)
    limits = dict(DEFAULT_LIMITS)
    limits.update(plan.limits if plan else {})
    limits.update(subscription.limit_overrides or {})
    return limits


async def check_can_upload(
    db: AsyncSession, ctx: TenantContext, *, byte_size: int, file_count: int = 1
) -> None:
    if not get_settings().billing_enabled:
        return

    limits = await limits_for(db, ctx.mm_id)
    period = current_period()
    counter = await _counter(db, ctx.mm_id, period)
    used_documents = counter.documents_uploaded if counter else 0
    used_bytes = counter.bytes_stored if counter else 0

    documents_limit = int(limits.get("documents_per_month", UNLIMITED))
    if documents_limit != UNLIMITED and used_documents + file_count > documents_limit:
        raise QuotaExceededError(
            "QUOTA_DOCUMENTS_EXCEEDED", limit=documents_limit, period=period
        )

    storage_limit_gb = int(limits.get("storage_gb", UNLIMITED))
    if (
        storage_limit_gb != UNLIMITED
        and used_bytes + byte_size > storage_limit_gb * BYTES_PER_GB
    ):
        raise QuotaExceededError("QUOTA_STORAGE_EXCEEDED", limit_gb=storage_limit_gb)


async def record_upload(db: AsyncSession, ctx: TenantContext, *, byte_size: int) -> None:
    await _bump(db, ctx.mm_id, documents_uploaded=1, bytes_stored=byte_size)


async def record_prints(db: AsyncSession, ctx: TenantContext, *, labels: int) -> None:
    await _bump(db, ctx.mm_id, labels_printed=labels)


async def _bump(
    db: AsyncSession,
    mm_id: UUID,
    *,
    documents_uploaded: int = 0,
    labels_printed: int = 0,
    bytes_stored: int = 0,
) -> None:
    period = current_period()
    statement = pg_insert(UsageCounter).values(
        mm_id=mm_id,
        period=period,
        documents_uploaded=documents_uploaded,
        labels_printed=labels_printed,
        bytes_stored=bytes_stored,
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=["mm_id", "period"],
            set_={
                "documents_uploaded": UsageCounter.documents_uploaded + documents_uploaded,
                "labels_printed": UsageCounter.labels_printed + labels_printed,
                "bytes_stored": UsageCounter.bytes_stored + bytes_stored,
            },
        )
    )


async def _subscription(db: AsyncSession, mm_id: UUID) -> Subscription | None:
    stmt = select(Subscription).where(Subscription.mm_id == mm_id)
    return (await db.execute(stmt)).scalars().first()


async def _counter(db: AsyncSession, mm_id: UUID, period: str) -> UsageCounter | None:
    stmt = select(UsageCounter).where(
        UsageCounter.mm_id == mm_id, UsageCounter.period == period
    )
    return (await db.execute(stmt)).scalars().first()
