"""Stripe subscriptions. Dormant unless BILLING_ENABLED.

Every entry point refuses with ``BILLING_DISABLED`` when billing is off, so an
installation that does not sell anything never reaches the provider at all.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import TenantContext
from app.errors import DomainError, NotFoundError
from app.models.billing import (
    BillingEvent,
    BillingProvider,
    Plan,
    Subscription,
    SubscriptionStatus,
)

logger = logging.getLogger("estampa.billing")

PROVIDER_STATUS: dict[str, SubscriptionStatus] = {
    "trialing": SubscriptionStatus.TRIALING,
    "active": SubscriptionStatus.ACTIVE,
    "past_due": SubscriptionStatus.PAST_DUE,
    "unpaid": SubscriptionStatus.PAST_DUE,
    "incomplete": SubscriptionStatus.PAST_DUE,
    "incomplete_expired": SubscriptionStatus.CANCELED,
    "canceled": SubscriptionStatus.CANCELED,
}


@dataclass(frozen=True, slots=True)
class HostedSession:
    """A provider-hosted page the customer is redirected to."""

    url: str
    session_id: str | None = None


@dataclass(frozen=True, slots=True)
class WebhookOutcome:
    """What became of one provider delivery."""

    event_id: str
    event_type: str
    #: A handler ran for this event type.
    handled: bool
    #: The event id had been recorded already: nothing ran, the provider gets 200.
    duplicate: bool = False


EventHandler = Callable[[AsyncSession, Any], Awaitable[None]]


Owner = TenantContext | UUID


def owner_mm_id(owner: Owner) -> UUID:
    """Accepts the tenant context or a bare company id. Never a request body."""
    return owner.mm_id if isinstance(owner, TenantContext) else owner


def is_enabled() -> bool:
    return get_settings().billing_enabled


async def get_subscription(db: AsyncSession, owner: Owner) -> Subscription | None:
    _require_enabled()
    return await _subscription_of(db, owner_mm_id(owner))


async def list_plans(db: AsyncSession, *, only_public: bool = True) -> list[Plan]:
    """The plan catalogue. A global table, so no tenant filter applies."""
    _require_enabled()
    stmt = select(Plan).order_by(Plan.sort_order, Plan.code)
    if only_public:
        stmt = stmt.where(Plan.is_public.is_(True))
    return list((await db.execute(stmt)).scalars().all())


async def ensure_subscription(db: AsyncSession, owner: Owner) -> Subscription:
    """Return the company's subscription, creating a dormant one if needed."""
    _require_enabled()
    mm_id = owner_mm_id(owner)
    existing = await _subscription_of(db, mm_id)
    if existing is not None:
        return existing

    subscription = Subscription(
        mm_id=mm_id,
        plan_code=(await _cheapest_plan(db)).code,
        status=SubscriptionStatus.DISABLED,
        provider=BillingProvider.STRIPE,
    )
    db.add(subscription)
    await db.flush()
    return subscription


async def create_checkout_session(
    db: AsyncSession,
    owner: Owner,
    *,
    plan_code: str,
    success_url: str | None = None,
    cancel_url: str | None = None,
) -> HostedSession:
    """Start a hosted checkout and return where to send the customer."""
    _require_enabled()
    mm_id = owner_mm_id(owner)
    subscription = await ensure_subscription(db, mm_id)
    plan = await _billable_plan(db, plan_code)
    customer_id = await _ensure_customer(db, subscription, mm_id)

    base = get_settings().public_base_url
    stripe = _stripe()
    try:
        session = await stripe.checkout.Session.create_async(
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": plan.stripe_price_id, "quantity": 1}],
            success_url=success_url or f"{base}/billing?checkout=ok",
            cancel_url=cancel_url or f"{base}/billing?checkout=cancelled",
            client_reference_id=str(mm_id),
            metadata={"mm_id": str(mm_id), "plan_code": plan.code},
        )
    except Exception as exc:
        raise DomainError("BILLING_PROVIDER_ERROR") from exc
    return HostedSession(url=str(session.url), session_id=_identifier_of(session))


async def create_portal_session(
    db: AsyncSession, owner: Owner, *, return_url: str | None = None
) -> HostedSession:
    """Hand the customer over to the provider's own billing portal."""
    _require_enabled()
    subscription = await _subscription_of(db, owner_mm_id(owner))
    if subscription is None or not subscription.provider_customer_id:
        raise NotFoundError("SUBSCRIPTION_NOT_FOUND")

    stripe = _stripe()
    try:
        session = await stripe.billing_portal.Session.create_async(
            customer=subscription.provider_customer_id,
            return_url=return_url or f"{get_settings().public_base_url}/billing",
        )
    except Exception as exc:
        raise DomainError("BILLING_PROVIDER_ERROR") from exc
    return HostedSession(url=str(session.url))


async def handle_webhook(
    db: AsyncSession,
    *,
    body: bytes | None = None,
    payload: bytes | None = None,
    signature: str | None = None,
) -> WebhookOutcome:
    """Apply a provider event exactly once.

    The event id is recorded *first* and the handler runs *after*, inside one
    savepoint: a delivery whose id is already there is answered as a duplicate
    without touching anything (Stripe needs the 200 to stop retrying), and a
    handler that fails rolls the record back with it, so the retry that
    follows does run (audit E-20).
    """
    _require_enabled()
    event = _verified_event(body if body is not None else payload, signature)
    event_id = str(event["id"])
    event_type = str(event["type"])

    handlers: dict[str, EventHandler] = {
        "checkout.session.completed": _on_checkout_completed,
        "customer.subscription.created": _on_subscription_changed,
        "customer.subscription.updated": _on_subscription_changed,
        "customer.subscription.deleted": _on_subscription_deleted,
        "invoice.payment_failed": _on_payment_failed,
    }
    handler = handlers.get(event_type)

    async with db.begin_nested():
        record = await _record_event(db, event_id, event_type)
        if record is None:
            logger.info(
                "billing event replayed, not reprocessed",
                extra={"event_id": event_id, "event_type": event_type},
            )
            return WebhookOutcome(event_id, event_type, handled=False, duplicate=True)
        if handler is not None:
            await handler(db, event["data"]["object"])
        record.processed_at = datetime.now(UTC)
        await db.flush()
    return WebhookOutcome(event_id, event_type, handled=handler is not None)


async def _record_event(db: AsyncSession, event_id: str, event_type: str) -> BillingEvent | None:
    """Claim the event id. ``None`` means another delivery already holds it.

    The lookup answers the common replay; the savepoint around the insert
    answers the race, where two deliveries of the same event arrive together:
    the second insert waits on the primary key and fails once the first
    commits, and only that savepoint is rolled back.
    """
    if await db.get(BillingEvent, event_id) is not None:
        return None
    record = BillingEvent(id=event_id, type=event_type)
    try:
        async with db.begin_nested():
            db.add(record)
            await db.flush()
    except IntegrityError:
        return None
    return record


def _require_enabled() -> None:
    if not is_enabled():
        raise DomainError("BILLING_DISABLED")


def _stripe() -> Any:
    """The SDK, wired to httpx. This codebase never talks HTTP through requests."""
    import stripe

    stripe.api_key = get_settings().stripe_secret_key
    httpx_client = getattr(stripe, "HTTPXClient", None)
    if httpx_client is not None and stripe.default_http_client is None:
        stripe.default_http_client = httpx_client(allow_sync_methods=True)
    return stripe


def _verified_event(payload: bytes | None, signature: str | None) -> Any:
    if payload is None or not signature:
        raise DomainError("BILLING_WEBHOOK_INVALID", status_code=400)
    stripe = _stripe()
    try:
        return stripe.Webhook.construct_event(
            payload, signature, get_settings().stripe_webhook_secret
        )
    except Exception as exc:
        raise DomainError("BILLING_WEBHOOK_INVALID", status_code=400) from exc


async def _subscription_of(db: AsyncSession, mm_id: UUID) -> Subscription | None:
    stmt = select(Subscription).where(Subscription.mm_id == mm_id)
    return (await db.execute(stmt)).scalars().first()


async def _subscription_by_customer(
    db: AsyncSession, customer_id: str | None
) -> Subscription | None:
    if not customer_id:
        return None
    stmt = select(Subscription).where(Subscription.provider_customer_id == customer_id)
    return (await db.execute(stmt)).scalars().first()


async def _billable_plan(db: AsyncSession, plan_code: str) -> Plan:
    plan = await db.get(Plan, plan_code)
    if plan is None or not plan.stripe_price_id:
        raise NotFoundError("PLAN_NOT_FOUND", plan_code=plan_code)
    return plan


async def _cheapest_plan(db: AsyncSession) -> Plan:
    stmt = select(Plan).order_by(Plan.price_cents, Plan.sort_order).limit(1)
    plan = (await db.execute(stmt)).scalars().first()
    if plan is None:
        raise NotFoundError("PLAN_NOT_FOUND", plan_code="-")
    return plan


async def _ensure_customer(db: AsyncSession, subscription: Subscription, mm_id: UUID) -> str:
    if subscription.provider_customer_id:
        return subscription.provider_customer_id

    stripe = _stripe()
    try:
        customer = await stripe.Customer.create_async(metadata={"mm_id": str(mm_id)})
    except Exception as exc:
        raise DomainError("BILLING_PROVIDER_ERROR") from exc

    subscription.provider_customer_id = str(customer.id)
    await db.flush()
    return subscription.provider_customer_id


async def _on_checkout_completed(db: AsyncSession, data: Any) -> None:
    mm_id = _mm_id_of(data)
    subscription = (
        await _subscription_of(db, mm_id)
        if mm_id
        else await _subscription_by_customer(db, data.get("customer"))
    )
    if subscription is None:
        return
    subscription.provider_customer_id = data.get("customer") or subscription.provider_customer_id
    subscription.provider_subscription_id = (
        data.get("subscription") or subscription.provider_subscription_id
    )
    subscription.status = SubscriptionStatus.ACTIVE
    await db.flush()


async def _on_subscription_changed(db: AsyncSession, data: Any) -> None:
    subscription = await _target_of(db, data)
    if subscription is None:
        return

    subscription.provider_subscription_id = data.get("id")
    subscription.status = PROVIDER_STATUS.get(str(data.get("status")), SubscriptionStatus.PAST_DUE)
    subscription.cancel_at_period_end = bool(data.get("cancel_at_period_end"))
    subscription.current_period_start = _moment(data.get("current_period_start"))
    subscription.current_period_end = _moment(data.get("current_period_end"))

    plan_code = await _plan_code_for_price(db, _price_id_of(data))
    if plan_code:
        subscription.plan_code = plan_code
    await db.flush()


async def _on_subscription_deleted(db: AsyncSession, data: Any) -> None:
    subscription = await _target_of(db, data)
    if subscription is None:
        return
    subscription.status = SubscriptionStatus.CANCELED
    subscription.cancel_at_period_end = False
    await db.flush()


async def _on_payment_failed(db: AsyncSession, data: Any) -> None:
    subscription = await _subscription_by_customer(db, data.get("customer"))
    if subscription is None:
        return
    subscription.status = SubscriptionStatus.PAST_DUE
    await db.flush()


async def _target_of(db: AsyncSession, data: Any) -> Subscription | None:
    mm_id = _mm_id_of(data)
    if mm_id is not None:
        return await _subscription_of(db, mm_id)
    return await _subscription_by_customer(db, data.get("customer"))


async def _plan_code_for_price(db: AsyncSession, price_id: str | None) -> str | None:
    if not price_id:
        return None
    stmt = select(Plan).where(Plan.stripe_price_id == price_id)
    plan = (await db.execute(stmt)).scalars().first()
    return plan.code if plan else None


def _price_id_of(data: Any) -> str | None:
    items = (data.get("items") or {}).get("data") or []
    if not items:
        return None
    return (items[0].get("price") or {}).get("id")


def _mm_id_of(data: Any) -> UUID | None:
    raw = (data.get("metadata") or {}).get("mm_id") or data.get("client_reference_id")
    try:
        return UUID(str(raw)) if raw else None
    except ValueError:
        return None


def _identifier_of(session: Any) -> str | None:
    identifier = getattr(session, "id", None)
    return str(identifier) if identifier else None


def _moment(timestamp: Any) -> datetime | None:
    return datetime.fromtimestamp(int(timestamp), UTC) if timestamp else None
