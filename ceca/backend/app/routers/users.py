"""Users of the company and the sites they may work in."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import Select, func, select

from app.deps import Db, TenantContext, require_permission
from app.errors import ConflictError, NotFoundError
from app.models.tenancy import PERMISSIONS, ROLE_PERMISSIONS, Site, User, UserSite
from app.routers import ClientIpHash, Page
from app.schemas.common import PageResponse
from app.schemas.tenancy import (
    MembershipRead,
    MembershipWrite,
    RoleCatalogResponse,
    RoleRead,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.security import hash_password
from app.services import audit as audit_service

router = APIRouter(prefix="/users", tags=["users"])

ReadCtx = Annotated[TenantContext, Depends(require_permission("users:read"))]
ManageCtx = Annotated[TenantContext, Depends(require_permission("users:manage"))]


def _company_users(ctx: TenantContext) -> Select[tuple[User]]:
    return select(User).where(User.mm_id == ctx.mm_id)


async def _get_user(db: Db, ctx: TenantContext, user_id: uuid.UUID) -> User:
    user = (await db.execute(_company_users(ctx).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise NotFoundError("USER_NOT_FOUND")
    return user


async def _memberships_of(db: Db, user_id: uuid.UUID) -> list[MembershipRead]:
    stmt = (
        select(UserSite, Site)
        .join(Site, Site.id == UserSite.site_id)
        .where(UserSite.user_id == user_id)
        .order_by(Site.name)
    )
    return [
        MembershipRead(
            id=membership.id,
            site_id=site.id,
            site_name=site.name,
            role=membership.role,
            extra_permissions=list(membership.extra_permissions),
            permissions=sorted(membership.permissions()),
        )
        for membership, site in (await db.execute(stmt)).all()
    ]


async def _read(db: Db, user: User) -> UserRead:
    payload = UserRead.model_validate(user)
    return payload.model_copy(update={"memberships": await _memberships_of(db, user.id)})


async def _assert_sites_belong_to_company(
    db: Db, ctx: TenantContext, memberships: list[MembershipWrite]
) -> None:
    """A site id in the body is a target, and a target of another company is a 404."""
    wanted = {membership.site_id for membership in memberships}
    found = set(
        (
            await db.execute(select(Site.id).where(Site.mm_id == ctx.mm_id, Site.id.in_(wanted)))
        ).scalars()
    )
    if wanted - found:
        raise NotFoundError("SITE_NOT_FOUND")


async def _replace_memberships(
    db: Db, ctx: TenantContext, user: User, memberships: list[MembershipWrite]
) -> None:
    await _assert_sites_belong_to_company(db, ctx, memberships)
    existing = {
        membership.site_id: membership
        for membership in (
            await db.execute(select(UserSite).where(UserSite.user_id == user.id))
        ).scalars()
    }
    for wanted in memberships:
        current = existing.pop(wanted.site_id, None)
        if current is None:
            db.add(
                UserSite(
                    user_id=user.id,
                    site_id=wanted.site_id,
                    role=wanted.role,
                    extra_permissions=list(wanted.extra_permissions),
                )
            )
            continue
        current.role = wanted.role
        current.extra_permissions = list(wanted.extra_permissions)
    for removed in existing.values():
        await db.delete(removed)


def _resolve_default_site(
    memberships: list[MembershipWrite], wanted: uuid.UUID | None
) -> uuid.UUID:
    sites = [membership.site_id for membership in memberships]
    if wanted is not None and wanted in sites:
        return wanted
    return sites[0]


async def _audit(db: Db, ctx: TenantContext, user: User, action: str, ip_hash: str | None) -> None:
    await audit_service.record(
        db,
        mm_id=ctx.mm_id,
        site_id=ctx.site_id,
        actor_user_id=ctx.user_id,
        action=action,
        object_type="user",
        object_id=user.id,
        payload={"email": user.email},
        ip_hash=ip_hash,
    )


@router.get("/roles", response_model=RoleCatalogResponse)
async def list_roles(ctx: ReadCtx) -> RoleCatalogResponse:
    """The permission vocabulary, so the admin UI never hardcodes it."""
    return RoleCatalogResponse(
        roles=[
            RoleRead(code=code, permissions=sorted(permissions))
            for code, permissions in ROLE_PERMISSIONS.items()
        ],
        permissions=list(PERMISSIONS),
    )


@router.get("/", response_model=PageResponse[UserRead])
async def list_users(
    ctx: ReadCtx,
    db: Db,
    page: Page,
    search: Annotated[str | None, Query(max_length=255)] = None,
    is_active: bool | None = None,
) -> PageResponse[UserRead]:
    stmt = _company_users(ctx)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(User.full_name.ilike(pattern) | User.email.ilike(pattern))
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.execute(stmt.order_by(User.full_name).offset(page.offset).limit(page.limit))
    ).scalars()
    items = [await _read(db, user) for user in rows]
    return PageResponse.of(items, total, page)


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate, ctx: ManageCtx, db: Db, ip_hash: ClientIpHash
) -> UserRead:
    email = payload.email.lower()
    taken = await db.scalar(_company_users(ctx).where(User.email == email))
    if taken is not None:
        raise ConflictError("EMAIL_ALREADY_EXISTS", email=email)

    await _assert_sites_belong_to_company(db, ctx, payload.memberships)
    user = User(
        mm_id=ctx.mm_id,
        email=email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        locale=payload.locale,
        default_site_id=_resolve_default_site(payload.memberships, payload.default_site_id),
    )
    db.add(user)
    await db.flush()
    await _replace_memberships(db, ctx, user, payload.memberships)
    await db.flush()
    await _audit(db, ctx, user, "user.created", ip_hash)
    return await _read(db, user)


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: uuid.UUID, ctx: ReadCtx, db: Db) -> UserRead:
    return await _read(db, await _get_user(db, ctx, user_id))


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    ctx: ManageCtx,
    db: Db,
    ip_hash: ClientIpHash,
) -> UserRead:
    user = await _get_user(db, ctx, user_id)
    if payload.version is not None and payload.version != user.version:
        raise ConflictError("VERSION_CONFLICT")

    changes = payload.model_dump(exclude_unset=True, exclude={"version", "password", "memberships"})
    for field, value in changes.items():
        setattr(user, field, value)
    if payload.password:
        user.hashed_password = hash_password(payload.password)
    if payload.memberships is not None:
        await _replace_memberships(db, ctx, user, payload.memberships)
        user.default_site_id = _resolve_default_site(
            payload.memberships, payload.default_site_id or user.default_site_id
        )
    await db.flush()
    await _audit(db, ctx, user, "user.updated", ip_hash)
    return await _read(db, user)
