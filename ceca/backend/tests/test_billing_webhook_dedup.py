"""E-20: a Stripe event is applied once, however many times it is delivered.

Stripe retries until it gets a 200, and a captured delivery can be re-sent
within the signature's tolerance window. The event id is recorded before the
handler runs, in the same transaction: a second delivery is acknowledged and
ignored, and a handler that fails leaves no record, so the retry does run.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.models.billing import (
    BillingEvent,
    BillingProvider,
    Plan,
    Subscription,
    SubscriptionStatus,
)
from app.services import billing as billing_service

WEBHOOK = "/api/v1/billing/webhook"
HEADERS = {"Stripe-Signature": "t=1700000000,v1=not-checked-here"}


def _event(event_id: str, mm_id: Any, *, status: str = "active") -> dict[str, Any]:
    return {
        "id": event_id,
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_123",
                "customer": "cus_123",
                "status": status,
                "cancel_at_period_end": False,
                "current_period_start": 1700000000,
                "current_period_end": 1702592000,
                "metadata": {"mm_id": str(mm_id)},
                "items": {"data": [{"price": {"id": "price_basic"}}]},
            }
        },
    }


@pytest.fixture
async def subscribed_company(db: Any, make_tenant: Any) -> Any:
    mm, _site = await make_tenant(slug="billing", prefix="BIL")
    db.add(
        Plan(
            code="basic",
            name_es="Básico",
            name_en="Basic",
            price_cents=1000,
            limits={},
            stripe_price_id="price_basic",
        )
    )
    await db.flush()
    db.add(
        Subscription(
            mm_id=mm.id,
            plan_code="basic",
            status=SubscriptionStatus.DISABLED,
            provider=BillingProvider.STRIPE,
            provider_customer_id="cus_123",
        )
    )
    await db.flush()
    return mm


@pytest.fixture
def billing_on(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Billing enabled, signature verification replaced, handler counted."""
    monkeypatch.setattr(billing_service, "is_enabled", lambda: True)

    state: dict[str, Any] = {"event": None, "handled": 0}

    def verified(_payload: bytes | None, _signature: str | None) -> Any:
        return state["event"]

    original = billing_service._on_subscription_changed

    async def counted(db: Any, data: Any) -> None:
        state["handled"] += 1
        await original(db, data)

    monkeypatch.setattr(billing_service, "_verified_event", verified)
    monkeypatch.setattr(billing_service, "_on_subscription_changed", counted)
    return state


async def _deliver(client: Any, state: dict[str, Any], event: dict[str, Any]) -> Any:
    state["event"] = event
    return await client.post(WEBHOOK, content=b"{}", headers=HEADERS)


async def test_the_same_event_twice_is_processed_once(
    client: Any, db: Any, subscribed_company: Any, billing_on: dict[str, Any]
) -> None:
    event = _event("evt_once", subscribed_company.id)

    first = await _deliver(client, billing_on, event)
    second = await _deliver(client, billing_on, event)

    assert first.status_code == 200, first.text
    assert first.json() == {"received": True, "handled": True}
    assert second.status_code == 200, "Stripe must get a 200 or it keeps retrying"
    assert second.json() == {"received": True, "handled": False}
    assert billing_on["handled"] == 1

    record = await db.get(BillingEvent, "evt_once")
    assert record is not None
    assert record.type == "customer.subscription.updated"
    assert record.processed_at is not None


async def test_a_replay_cannot_undo_a_later_change(
    client: Any, db: Any, subscribed_company: Any, billing_on: dict[str, Any]
) -> None:
    """The attack in E-20: capture an 'active' event, replay it after cancellation."""
    active = _event("evt_active", subscribed_company.id, status="active")
    canceled = _event("evt_canceled", subscribed_company.id, status="canceled")

    await _deliver(client, billing_on, active)
    await _deliver(client, billing_on, canceled)
    replay = await _deliver(client, billing_on, active)

    assert replay.status_code == 200
    subscription = await billing_service.get_subscription(db, subscribed_company.id)
    assert subscription is not None
    assert subscription.status == SubscriptionStatus.CANCELED
    assert billing_on["handled"] == 2


async def test_a_failed_handler_leaves_no_record_so_the_retry_runs(
    client: Any,
    db: Any,
    subscribed_company: Any,
    billing_on: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _event("evt_retry", subscribed_company.id)
    working = billing_service._on_subscription_changed

    async def broken(_db: Any, _data: Any) -> None:
        raise RuntimeError("provider hiccup")

    monkeypatch.setattr(billing_service, "_on_subscription_changed", broken)
    with pytest.raises(RuntimeError):
        await _deliver(client, billing_on, event)
    assert await db.get(BillingEvent, "evt_retry") is None, "a failed event was marked as seen"

    monkeypatch.setattr(billing_service, "_on_subscription_changed", working)
    retry = await _deliver(client, billing_on, event)

    assert retry.status_code == 200, retry.text
    assert retry.json()["handled"] is True
    assert billing_on["handled"] == 1
    record = await db.get(BillingEvent, "evt_retry")
    assert record is not None and record.processed_at is not None


async def test_an_unhandled_event_type_is_still_recorded(
    client: Any, db: Any, subscribed_company: Any, billing_on: dict[str, Any]
) -> None:
    event = _event("evt_ignored", subscribed_company.id)
    event["type"] = "invoice.paid"

    first = await _deliver(client, billing_on, event)
    second = await _deliver(client, billing_on, event)

    assert first.json() == {"received": True, "handled": False}
    assert second.json() == {"received": True, "handled": False}
    assert billing_on["handled"] == 0
    assert await db.get(BillingEvent, "evt_ignored") is not None


async def test_billing_disabled_still_refuses_the_webhook(client: Any, db: Any) -> None:
    response = await client.post(WEBHOOK, content=b"{}", headers=HEADERS)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "BILLING_DISABLED"
    assert await db.get(BillingEvent, "evt_never") is None
