"""Plans, subscription, usage and Stripe. Switchable off platform-wide."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from app.deps import Db, TenantContext, require_permission
from app.errors import DomainError
from app.models.billing import UsageCounter
from app.schemas.billing import (
    CheckoutRequest,
    CheckoutSessionResponse,
    PlanRead,
    PlansResponse,
    PortalSessionResponse,
    SubscriptionRead,
    SubscriptionResponse,
    UsageResponse,
    WebhookAck,
)
from app.services import billing as billing_service
from app.services import quota as quota_service

router = APIRouter(prefix="/billing", tags=["billing"])

ReadCtx = Annotated[TenantContext, Depends(require_permission("billing:read"))]
ManageCtx = Annotated[TenantContext, Depends(require_permission("billing:manage"))]


def _current_period() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def _require_enabled() -> None:
    """Reads degrade gracefully; writes refuse outright."""
    if not billing_service.is_enabled():
        raise DomainError("BILLING_DISABLED")


@router.get("/plans", response_model=PlansResponse)
async def list_plans(ctx: ReadCtx, db: Db) -> PlansResponse:
    """Both names travel: the client picks the one matching its locale."""
    if not billing_service.is_enabled():
        return PlansResponse(enabled=False)
    plans = await billing_service.list_plans(db)
    return PlansResponse(enabled=True, items=[PlanRead.model_validate(plan) for plan in plans])


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(ctx: ReadCtx, db: Db) -> SubscriptionResponse:
    if not billing_service.is_enabled():
        return SubscriptionResponse(enabled=False)
    subscription = await billing_service.get_subscription(db, ctx)
    if subscription is None:
        return SubscriptionResponse(enabled=True)
    limits = await quota_service.limits_for(db, ctx)
    return SubscriptionResponse(
        enabled=True,
        subscription=SubscriptionRead.model_validate(subscription).model_copy(
            update={"limits": limits}
        ),
    )


@router.get("/usage", response_model=UsageResponse)
async def get_usage(ctx: ReadCtx, db: Db) -> UsageResponse:
    period = _current_period()
    counter = (
        await db.execute(
            select(UsageCounter).where(
                UsageCounter.mm_id == ctx.mm_id, UsageCounter.period == period
            )
        )
    ).scalar_one_or_none()
    return UsageResponse(
        enabled=billing_service.is_enabled(),
        period=period,
        documents_uploaded=counter.documents_uploaded if counter else 0,
        labels_printed=counter.labels_printed if counter else 0,
        bytes_stored=counter.bytes_stored if counter else 0,
        limits=await quota_service.limits_for(db, ctx),
    )


@router.post("/checkout", response_model=CheckoutSessionResponse)
async def create_checkout(
    payload: CheckoutRequest, ctx: ManageCtx, db: Db
) -> CheckoutSessionResponse:
    _require_enabled()
    session = await billing_service.create_checkout_session(db, ctx, plan_code=payload.plan_code)
    return CheckoutSessionResponse.model_validate(session)


@router.post("/portal", response_model=PortalSessionResponse)
async def create_portal(ctx: ManageCtx, db: Db) -> PortalSessionResponse:
    _require_enabled()
    session = await billing_service.create_portal_session(db, ctx)
    return PortalSessionResponse.model_validate(session)


@router.post("/webhook", response_model=WebhookAck, include_in_schema=False)
async def stripe_webhook(request: Request, db: Db) -> WebhookAck:
    """Unauthenticated by design: the provider signature is the credential."""
    _require_enabled()
    handled = await billing_service.handle_webhook(
        db,
        body=await request.body(),
        signature=request.headers.get("Stripe-Signature"),
    )
    return WebhookAck(received=True, handled=bool(handled))
