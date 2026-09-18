"""Subscription billing. Dormant until BILLING_ENABLED, but always modelled."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import (
    UUID as PgUUID,  # noqa: N811 (alias avoids shadowing uuid.UUID)
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OptimisticLock, TimestampMixin, uuid_pk


class SubscriptionStatus(enum.StrEnum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    #: Billing switched off platform-wide: everyone runs unmetered.
    DISABLED = "disabled"


class BillingProvider(enum.StrEnum):
    STRIPE = "stripe"
    MANUAL = "manual"


class Plan(Base, TimestampMixin):
    """A commercial plan. Global catalogue, served by the API, never hardcoded."""

    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name_es: Mapped[str] = mapped_column(String(80), nullable=False)
    name_en: Mapped[str] = mapped_column(String(80), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    interval: Mapped[str] = mapped_column(String(16), nullable=False, default="month")
    #: {"documents_per_month": int, "storage_gb": int, "users": int, "sites": int}
    #: A value of -1 means unlimited.
    limits: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict, nullable=False)
    stripe_price_id: Mapped[str | None] = mapped_column(String(120))
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Subscription(Base, TimestampMixin, OptimisticLock):
    """What an MM is currently entitled to. One live row per MM."""

    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("mm_id", name="uq_subscriptions_mm_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    mm_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("mms.id", ondelete="CASCADE"), nullable=False
    )
    plan_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("plans.code", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        String(16), nullable=False, default=SubscriptionStatus.DISABLED
    )
    provider: Mapped[BillingProvider] = mapped_column(
        String(16), nullable=False, default=BillingProvider.MANUAL
    )
    provider_customer_id: Mapped[str | None] = mapped_column(String(120))
    provider_subscription_id: Mapped[str | None] = mapped_column(String(120))
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Per-tenant overrides that win over the plan's limits.
    limit_overrides: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict, nullable=False)


class UsageCounter(Base, TimestampMixin):
    """Monthly consumption per MM, the input to quota checks."""

    __tablename__ = "usage_counters"
    __table_args__ = (UniqueConstraint("mm_id", "period", name="uq_usage_counters_mm_id_period"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    mm_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("mms.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    documents_uploaded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    labels_printed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bytes_stored: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class BillingEvent(Base):
    """Every provider event ever received, keyed by the provider's own event id.

    The row is inserted *before* the event is handled, inside the same
    transaction: a replay (Stripe retrying, or someone re-sending a captured
    delivery) collides on the primary key and is answered 200 without running
    anything again, and a failure halfway leaves no row, so the retry does run
    (audit E-20). ``processed_at`` is set once the handler has returned.
    """

    __tablename__ = "billing_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    type: Mapped[str] = mapped_column(String(120), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
