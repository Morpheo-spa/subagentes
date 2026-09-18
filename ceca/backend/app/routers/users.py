"""Users of the company and the sites they may work in.

Every route here is an authorisation surface: ``users:manage`` is what turns a
row in ``user_sites`` into permissions, so a careless write is privilege
escalation. Three rules hold the line, and they are enforced here rather than
in the schema because two of them need the caller's own memberships:

1. **Nobody edits their own role or permissions.** Not a ``site_admin``, not an
   ``mm_admin``, not a superuser. Another administrator has to do it.
2. **``users:manage`` reaches only the sites the caller belongs to**, unless the
   caller is ``mm_admin`` of the company (see :class:`app.deps.AdminScope`). A
   site is a tenant, so a site outside that scope answers 404, never 403.
3. **No grant may exceed the granter.** The permission set a role (plus extras)
   would hand out must be a subset of what the caller holds in that same site.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import Select, func, select

from app.cache import invalidate_user_sessions
from app.deps import AdminScope, Db, TenantContext, admin_scope, require_permission
from app.errors import ConflictError, NotFoundError, PermissionDeniedError
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


def _visible_users(ctx: TenantContext, scope: AdminScope) -> Select[tuple[User]]:
    """The company's users, narrowed to the ones the caller may see.

    An ``mm_admin`` sees the whole company. Anyone else sees only the people who
    share one of their own sites: a user of another site is another tenant's
    user, and must be indistinguishable from one that does not exist.
    """
    stmt = _company_users(ctx)
    if scope.company_wide:
        return stmt
    return stmt.where(
        User.id.in_(select(UserSite.user_id).where(UserSite.site_id.in_(scope.site_ids)))
    )


async def _get_user(db: Db, ctx: TenantContext, scope: AdminScope, user_id: uuid.UUID) -> User:
    user = (
        await db.execute(_visible_users(ctx, scope).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise NotFoundError("USER_NOT_FOUND")
    return user


def _assert_may_grant(scope: AdminScope, memberships: list[MembershipWrite]) -> None:
    """No writing outside the caller's sites, and no granting above themselves."""
    for wanted in memberships:
        if not scope.may_administer(wanted.site_id):
            # The site exists, but not for this caller: 404, as for any other tenant.
            raise NotFoundError("SITE_NOT_FOUND")
        held = scope.permissions_in(wanted.site_id)
        if not set(ROLE_PERMISSIONS.get(wanted.role, ())) <= held:
            raise PermissionDeniedError("ROLE_ESCALATION_FORBIDDEN", role=wanted.role)
        beyond = sorted(set(wanted.extra_permissions) - held)
        if beyond:
            raise PermissionDeniedError(
                "PERMISSION_ESCALATION_FORBIDDEN", permissions=", ".join(beyond)
            )


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
    """Build the payload field by field, never from the ORM object wholesale.

    ``UserRead.model_validate(user)`` reads every field off the instance,
    ``memberships`` included — and that one is a lazy relationship, so loading
    it from an async session raises ``MissingGreenlet`` and the route 500s. The
    memberships come from their own query, which is also the only one that
    resolves the site names.
    """
    return UserRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        locale=user.locale,
        default_site_id=user.default_site_id,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        memberships=await _memberships_of(db, user.id),
    )


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
    db: Db,
    ctx: TenantContext,
    scope: AdminScope,
    user: User,
    memberships: list[MembershipWrite],
) -> list[uuid.UUID]:
    """Apply the wanted memberships and return the user's resulting sites.

    The payload replaces only what the caller may administer. Memberships in
    sites outside the caller's scope are left exactly as they were: a
    ``site_admin`` of one delegation must not be able to cut a colleague out of
    another one by omitting it from the list.
    """
    await _assert_sites_belong_to_company(db, ctx, memberships)
    _assert_may_grant(scope, memberships)
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
    untouched = [
        site_id for site_id in existing if not scope.may_administer(site_id)
    ]
    for site_id, removed in existing.items():
        if scope.may_administer(site_id):
            await db.delete(removed)
    return [membership.site_id for membership in memberships] + untouched


async def _assert_default_site_is_a_membership(
    db: Db, user: User, site_id: uuid.UUID
) -> None:
    """``default_site_id`` is a target that arrives in the body, so it is checked.

    It grants nothing by itself — the login only ever picks a site the user is a
    member of — but an unverified site id from a body has no business being
    written to a row, and a site the user does not belong to is not theirs.
    """
    found = await db.scalar(
        select(UserSite.id).where(UserSite.user_id == user.id, UserSite.site_id == site_id)
    )
    if found is None:
        raise NotFoundError("SITE_NOT_FOUND")


def _resolve_default_site(sites: list[uuid.UUID], wanted: uuid.UUID | None) -> uuid.UUID:
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
    stmt = _visible_users(ctx, await admin_scope(ctx, db))
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
    # Globally unique, not per company: the login has no tenant to scope by, so
    # a second company taking this address would break the first owner's login.
    # The unique index is the guarantee; this check is only the polite 409.
    taken = await db.scalar(select(User.id).where(User.email == email))
    if taken is not None:
        raise ConflictError("EMAIL_ALREADY_EXISTS", email=email)

    scope = await admin_scope(ctx, db)
    await _assert_sites_belong_to_company(db, ctx, payload.memberships)
    _assert_may_grant(scope, payload.memberships)
    user = User(
        mm_id=ctx.mm_id,
        email=email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        locale=payload.locale,
        default_site_id=_resolve_default_site(
            [membership.site_id for membership in payload.memberships], payload.default_site_id
        ),
    )
    db.add(user)
    await db.flush()
    await _replace_memberships(db, ctx, scope, user, payload.memberships)
    await db.flush()
    await _audit(db, ctx, user, "user.created", ip_hash)
    return await _read(db, user)


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: uuid.UUID, ctx: ReadCtx, db: Db) -> UserRead:
    return await _read(db, await _get_user(db, ctx, await admin_scope(ctx, db), user_id))


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    ctx: ManageCtx,
    db: Db,
    ip_hash: ClientIpHash,
) -> UserRead:
    scope = await admin_scope(ctx, db)
    user = await _get_user(db, ctx, scope, user_id)
    if payload.memberships is not None and user.id == ctx.user_id:
        # The whole of E-03 in one line: an admin who can rewrite their own
        # memberships can promote themselves to mm_admin and switch site.
        raise PermissionDeniedError("SELF_ROLE_CHANGE_FORBIDDEN")
    if payload.version is not None and payload.version != user.version:
        raise ConflictError("VERSION_CONFLICT")

    if payload.memberships is None and payload.default_site_id is not None:
        await _assert_default_site_is_a_membership(db, user, payload.default_site_id)

    changes = payload.model_dump(exclude_unset=True, exclude={"version", "password", "memberships"})
    for field, value in changes.items():
        setattr(user, field, value)
    if payload.password:
        user.hashed_password = hash_password(payload.password)
    if payload.memberships is not None:
        sites = await _replace_memberships(db, ctx, scope, user, payload.memberships)
        user.default_site_id = _resolve_default_site(
            sites, payload.default_site_id or user.default_site_id
        )
    await db.flush()
    await _audit(db, ctx, user, "user.updated", ip_hash)
    if _touches_session(payload):
        # What the target's access token asserts is no longer true, and the
        # token carries it for another 30 minutes unless we say otherwise.
        await invalidate_user_sessions(user.id)
    return await _read(db, user)


#: Fields whose change makes the target's live access token a lie.
SESSION_BEARING_FIELDS = frozenset({"is_active", "memberships", "password"})


def _touches_session(payload: UserUpdate) -> bool:
    return bool(payload.model_fields_set & SESSION_BEARING_FIELDS)
