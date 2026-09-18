"""Sites of the signed in company. A site is the isolation boundary."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import Select, func, select

from app.deps import Db, TenantContext, require_permission
from app.errors import ConflictError, NotFoundError
from app.models.tenancy import Site
from app.routers import ClientIpHash, Page
from app.schemas.common import Acknowledgement, PageResponse
from app.schemas.tenancy import SiteCreate, SiteRead, SiteUpdate
from app.services import audit as audit_service

router = APIRouter(prefix="/sites", tags=["sites"])

ReadCtx = Annotated[TenantContext, Depends(require_permission("sites:read"))]
ManageCtx = Annotated[TenantContext, Depends(require_permission("sites:manage"))]


def _company_sites(ctx: TenantContext) -> Select:
    """Sites are scoped by company: a site row cannot be scoped by itself."""
    return select(Site).where(Site.mm_id == ctx.mm_id)


async def _get_site(db: Db, ctx: TenantContext, site_id: uuid.UUID) -> Site:
    stmt = _company_sites(ctx).where(Site.id == site_id)
    site = (await db.execute(stmt)).scalar_one_or_none()
    if site is None:
        raise NotFoundError("SITE_NOT_FOUND")
    return site


async def _audit(
    db: Db, ctx: TenantContext, site: Site, action: str, ip_hash: str | None
) -> None:
    await audit_service.record(
        db,
        mm_id=ctx.mm_id,
        site_id=ctx.site_id,
        actor_user_id=ctx.user_id,
        action=action,
        object_type="site",
        object_id=site.id,
        payload={"name": site.name, "site_prefix": site.site_prefix},
        ip_hash=ip_hash,
    )


@router.get("/", response_model=PageResponse[SiteRead])
async def list_sites(
    ctx: ReadCtx,
    db: Db,
    page: Page,
    search: Annotated[str | None, Query(max_length=160)] = None,
    is_active: bool | None = None,
) -> PageResponse[SiteRead]:
    stmt = _company_sites(ctx)
    if search:
        stmt = stmt.where(Site.name.ilike(f"%{search}%"))
    if is_active is not None:
        stmt = stmt.where(Site.is_active.is_(is_active))

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.execute(
            stmt.order_by(Site.name).offset(page.offset).limit(page.limit)
        )
    ).scalars()
    return PageResponse.of(
        [SiteRead.model_validate(site) for site in rows], total, page
    )


@router.post("/", response_model=SiteRead, status_code=status.HTTP_201_CREATED)
async def create_site(
    payload: SiteCreate, ctx: ManageCtx, db: Db, ip_hash: ClientIpHash
) -> SiteRead:
    taken = await db.scalar(
        _company_sites(ctx).where(Site.site_prefix == payload.site_prefix)
    )
    if taken is not None:
        raise ConflictError("SITE_PREFIX_TAKEN", site_prefix=payload.site_prefix)

    site = Site(mm_id=ctx.mm_id, **payload.model_dump())
    db.add(site)
    await db.flush()
    await _audit(db, ctx, site, "site.created", ip_hash)
    return SiteRead.model_validate(site)


@router.get("/{site_id}", response_model=SiteRead)
async def get_site(site_id: uuid.UUID, ctx: ReadCtx, db: Db) -> SiteRead:
    return SiteRead.model_validate(await _get_site(db, ctx, site_id))


@router.patch("/{site_id}", response_model=SiteRead)
async def update_site(
    site_id: uuid.UUID,
    payload: SiteUpdate,
    ctx: ManageCtx,
    db: Db,
    ip_hash: ClientIpHash,
) -> SiteRead:
    site = await _get_site(db, ctx, site_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(site, field, value)
    await db.flush()
    await _audit(db, ctx, site, "site.updated", ip_hash)
    return SiteRead.model_validate(site)


@router.delete("/{site_id}", response_model=Acknowledgement)
async def deactivate_site(
    site_id: uuid.UUID, ctx: ManageCtx, db: Db, ip_hash: ClientIpHash
) -> Acknowledgement:
    """Sites are deactivated, never deleted: their documents outlive them."""
    site = await _get_site(db, ctx, site_id)
    site.is_active = False
    await db.flush()
    await _audit(db, ctx, site, "site.deactivated", ip_hash)
    return Acknowledgement()
