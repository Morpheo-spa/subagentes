"""Plans, subscription and usage. Every response says whether billing is on."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.models.billing import BillingProvider, SubscriptionStatus
from app.schemas.common import Schema


class PlanRead(Schema):
    code: str
    name_es: str
    name_en: str
    price_cents: int
    currency: str
    interval: str
    limits: dict[str, Any] = Field(default_factory=dict)
    sort_order: int


class PlansResponse(Schema):
    enabled: bool
    items: list[PlanRead] = Field(default_factory=list)


class SubscriptionRead(Schema):
    plan_code: str
    status: SubscriptionStatus
    provider: BillingProvider
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    limits: dict[str, Any] = Field(default_factory=dict)


class SubscriptionResponse(Schema):
    enabled: bool
    subscription: SubscriptionRead | None = None


class UsageResponse(Schema):
    enabled: bool
    period: str
    documents_uploaded: int = 0
    labels_printed: int = 0
    bytes_stored: int = 0
    limits: dict[str, Any] = Field(default_factory=dict)


class CheckoutRequest(Schema):
    """Return URLs are built server side from the configured base URL."""

    plan_code: str = Field(min_length=1, max_length=32)


class CheckoutSessionResponse(Schema):
    url: str
    session_id: str | None = None


class PortalSessionResponse(Schema):
    url: str


class WebhookAck(Schema):
    received: bool = True
    handled: bool = False
