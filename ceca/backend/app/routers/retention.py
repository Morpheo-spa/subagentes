"""Retention policies. The legal minimum is a floor, never a suggestion."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select, update

from app.deps import Db, TenantContext, require_permission, scoped_select
from app.errors import ConflictError, DomainError, NotFoundError
from app.models.documents import Document
from app.models.retention import RetentionPolicy
from app.routers import ClientIpHash, Page
from app.schemas.common import Acknowledgement, PageResponse
from app.schemas.retention import (
    RetentionPolicyCreate,
    RetentionPolicyRead,
    RetentionPolicyUpdate,
    UpcomingExpiryItem,
)
from app.services import audit as audit_service
from app.services import retention as retention_service

router = APIRouter(prefix="/retention", tags=["retention"])

ReadCtx = Annotated[TenantContext, Depends(require_permission("retention:read"))]
ManageCtx = Annotated[TenantContext, Depends(require_permission("retention:manage"))]


def _read(policy: RetentionPolicy) -> RetentionPolicyRead:
    return RetentionPolicyRead.model_validate(policy).model_copy(
        update={"legal_minimum_days": retention_service.LEGAL_MINIMUM_DAYS}
    )


def _assert_above_legal_minimum(days: int | None) -> None:
    minimum = retention_service.LEGAL_MINIMUM_DAYS
    if days is not None and days < minimum:
        raise DomainError("RETENTION_BELOW_LEGAL_MINIMUM", minimum_days=minimum)


async def _get_policy(db: Db, ctx: TenantContext, policy_id: uuid.UUID) -> RetentionPolicy:
    stmt = scoped_select(RetentionPolicy, ctx).where(RetentionPolicy.id == policy_id)
    policy = (await db.execute(stmt)).scalar_one_or_none()
    if policy is None:
        raise NotFoundError("RETENTION_POLICY_NOT_FOUND")
    return policy


async def _demote_other_defaults(db: Db, ctx: TenantContext, keep_id: uuid.UUID) -> None:
    await db.execute(
        update(RetentionPolicy)
        .where(
            RetentionPolicy.mm_id == ctx.mm_id,
            RetentionPolicy.site_id == ctx.site_id,
            RetentionPolicy.is_default.is_(True),
            RetentionPolicy.id != keep_id,
        )
        .values(is_default=False)
    )


async def _audit(
    db: Db,
    ctx: TenantContext,
    policy: RetentionPolicy,
    action: str,
    ip_hash: str | None,
) -> None:
    await audit_service.record(
        db,
        mm_id=ctx.mm_id,
        site_id=ctx.site_id,
        actor_user_id=ctx.user_id,
        action=action,
        object_type="retention_policy",
        object_id=policy.id,
        payload={"name": policy.name, "retention_days": policy.retention_days},
        ip_hash=ip_hash,
    )


@router.get("/upcoming", response_model=PageResponse[UpcomingExpiryItem])
async def list_upcoming(
    ctx: ReadCtx,
    db: Db,
    page: Page,
    within_days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> PageResponse[UpcomingExpiryItem]:
    """What the retention sweep will act on soon, so a human can intervene."""
    rows, total = await retention_service.upcoming_expiries(
        db, ctx, within_days=within_days, offset=page.offset, limit=page.limit
    )
    return PageResponse.of([UpcomingExpiryItem.model_validate(row) for row in rows], total, page)


@router.get("/", response_model=PageResponse[RetentionPolicyRead])
async def list_policies(ctx: ReadCtx, db: Db, page: Page) -> PageResponse[RetentionPolicyRead]:
    stmt = scoped_select(RetentionPolicy, ctx)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.execute(
            stmt.order_by(RetentionPolicy.is_default.desc(), RetentionPolicy.name)
            .offset(page.offset)
            .limit(page.limit)
        )
    ).scalars()
    return PageResponse.of([_read(row) for row in rows], total, page)


@router.post("/", response_model=RetentionPolicyRead, status_code=status.HTTP_201_CREATED)
async def create_policy(
    payload: RetentionPolicyCreate, ctx: ManageCtx, db: Db, ip_hash: ClientIpHash
) -> RetentionPolicyRead:
    _assert_above_legal_minimum(payload.retention_days)
    policy = RetentionPolicy(mm_id=ctx.mm_id, site_id=ctx.site_id, **payload.model_dump())
    db.add(policy)
    await db.flush()
    if policy.is_default:
        await _demote_other_defaults(db, ctx, policy.id)
    await _audit(db, ctx, policy, "retention_policy.created", ip_hash)
    return _read(policy)


@router.get("/{policy_id}", response_model=RetentionPolicyRead)
async def get_policy(policy_id: uuid.UUID, ctx: ReadCtx, db: Db) -> RetentionPolicyRead:
    return _read(await _get_policy(db, ctx, policy_id))


@router.patch("/{policy_id}", response_model=RetentionPolicyRead)
async def update_policy(
    policy_id: uuid.UUID,
    payload: RetentionPolicyUpdate,
    ctx: ManageCtx,
    db: Db,
    ip_hash: ClientIpHash,
) -> RetentionPolicyRead:
    policy = await _get_policy(db, ctx, policy_id)
    if payload.version is not None and payload.version != policy.version:
        raise ConflictError("VERSION_CONFLICT")
    _assert_above_legal_minimum(payload.retention_days)

    for field, value in payload.model_dump(exclude_unset=True, exclude={"version"}).items():
        setattr(policy, field, value)
    await db.flush()
    if policy.is_default:
        await _demote_other_defaults(db, ctx, policy.id)
    await _audit(db, ctx, policy, "retention_policy.updated", ip_hash)
    return _read(policy)


@router.delete("/{policy_id}", response_model=Acknowledgement)
async def delete_policy(
    policy_id: uuid.UUID, ctx: ManageCtx, db: Db, ip_hash: ClientIpHash
) -> Acknowledgement:
    policy = await _get_policy(db, ctx, policy_id)
    in_use = (
        await db.scalar(
            select(func.count()).select_from(
                scoped_select(Document, ctx)
                .where(Document.retention_policy_id == policy.id)
                .subquery()
            )
        )
        or 0
    )
    if in_use:
        raise ConflictError("RETENTION_POLICY_IN_USE", count=in_use)

    await _audit(db, ctx, policy, "retention_policy.deleted", ip_hash)
    await db.delete(policy)
    return Acknowledgement()
