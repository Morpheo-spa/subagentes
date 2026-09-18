"""Sessions: sign in, refresh, sign out, switch site, and who am I.

These routes carry no ``require_permission`` guard on purpose: they *establish*
the permission set rather than consume it, and a viewer with no resource
permission must still be able to sign in and read their own session.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from app.cache import blacklist_token, reject_if_blacklisted
from app.config import get_settings
from app.cookies import (
    REFRESH_COOKIE,
    clear_refresh_cookie,
    read_refresh_cookie,
    require_same_origin,
    set_refresh_cookie,
)
from app.deps import Db, TenantContext, get_current_context
from app.errors import DomainError
from app.models.tenancy import PERMISSIONS, Site, User, UserSite
from app.routers import ClientIpHash
from app.schemas.auth import (
    LoginRequest,
    MembershipSummary,
    MeResponse,
    SessionResponse,
    SiteSummary,
    SwitchSiteRequest,
    TokenPair,
    UserSummary,
)
from app.schemas.common import Acknowledgement
from app.security import ACCESS, REFRESH, create_token, decode_token, verify_password
from app.services import audit as audit_service

router = APIRouter(prefix="/auth", tags=["auth"])


Membership = tuple[UserSite, Site]


async def _user_by_email(db: Db, email: str) -> User | None:
    """One of the few sanctioned unscoped reads: the tenant is not known yet.

    ``scalar_one_or_none`` is safe here only because ``users.email`` carries a
    **global** unique index (``ix_users_email``, migration 0004). Were the
    address unique per company instead, a second company registering the same
    email would make this query return two rows and turn every login attempt by
    either owner into a 500, permanently. Creating that duplicate is refused at
    the API with ``EMAIL_ALREADY_EXISTS`` and at the database by the index.
    """
    stmt = select(User).where(User.email == email.lower())
    return (await db.execute(stmt)).scalar_one_or_none()


async def _active_user(db: Db, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise DomainError("NOT_AUTHENTICATED", status_code=401)
    if not user.is_active:
        raise DomainError("USER_INACTIVE", status_code=403)
    return user


async def _memberships(db: Db, user: User) -> list[Membership]:
    stmt = (
        select(UserSite, Site)
        .join(Site, Site.id == UserSite.site_id)
        .where(
            UserSite.user_id == user.id,
            Site.mm_id == user.mm_id,
            Site.is_active.is_(True),
        )
        .order_by(Site.name)
    )
    return [(membership, site) for membership, site in (await db.execute(stmt)).all()]


def _pick_membership(
    user: User, memberships: list[Membership], site_id: uuid.UUID | None = None
) -> Membership:
    if not memberships:
        raise DomainError("NO_SITE_SELECTED", status_code=403)
    if site_id is not None:
        for membership in memberships:
            if membership[1].id == site_id:
                return membership
        raise DomainError("SITE_NOT_ALLOWED", status_code=403, site_id=str(site_id))
    for membership in memberships:
        if membership[1].id == user.default_site_id:
            return membership
    return memberships[0]


def _permissions_of(user: User, membership: UserSite) -> set[str]:
    return set(PERMISSIONS) if user.is_superuser else membership.permissions()


def _session(response: Response, user: User, membership: UserSite, site: Site) -> SessionResponse:
    permissions = _permissions_of(user, membership)
    claims: dict[str, Any] = {
        "user_id": user.id,
        "mm_id": user.mm_id,
        "site_id": site.id,
        "site_prefix": site.site_prefix,
        "permissions": permissions,
        "is_superuser": user.is_superuser,
        "locale": user.locale,
    }
    set_refresh_cookie(response, create_token(**claims, token_type=REFRESH))
    return SessionResponse(
        tokens=TokenPair(
            access_token=create_token(**claims, token_type=ACCESS),
            expires_in=get_settings().access_token_minutes * 60,
        ),
        user=UserSummary.model_validate(user),
        site=SiteSummary.model_validate(site),
        permissions=sorted(permissions),
    )


def _access_payload(request: Request) -> dict[str, Any]:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise DomainError("NOT_AUTHENTICATED", status_code=401)
    return decode_token(token)


@router.post("/login", response_model=SessionResponse)
async def login(
    payload: LoginRequest, response: Response, db: Db, ip_hash: ClientIpHash
) -> SessionResponse:
    user = await _user_by_email(db, payload.email)
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise DomainError("INVALID_CREDENTIALS", status_code=401)
    if not user.is_active:
        raise DomainError("USER_INACTIVE", status_code=403)

    membership, site = _pick_membership(user, await _memberships(db, user))
    user.last_login_at = datetime.now(UTC)
    await audit_service.record(
        db,
        mm_id=user.mm_id,
        site_id=site.id,
        actor_user_id=user.id,
        action="auth.login",
        object_type="user",
        object_id=user.id,
        payload={},
        ip_hash=ip_hash,
    )
    return _session(response, user, membership, site)


@router.post("/refresh", response_model=SessionResponse)
async def refresh(request: Request, response: Response, db: Db) -> SessionResponse:
    """Rotate the session. The refresh token is read from its HttpOnly cookie.

    The browser attaches that cookie by itself, so this route is the one place
    a forged cross-site POST could ride an existing session. SameSite blocks
    that, and the origin check below refuses it a second time.
    """
    require_same_origin(request)
    claims = decode_token(read_refresh_cookie(request), expected_type=REFRESH)
    await reject_if_blacklisted(claims)

    user = await _active_user(db, uuid.UUID(claims["sub"]))
    tenant_id = claims.get("tenant_id")
    membership, site = _pick_membership(
        user,
        await _memberships(db, user),
        uuid.UUID(tenant_id) if tenant_id else None,
    )
    await blacklist_token(claims)
    return _session(response, user, membership, site)


@router.post("/logout", response_model=Acknowledgement)
async def logout(
    request: Request,
    response: Response,
    ctx: Annotated[TenantContext, Depends(get_current_context)],
    ip_hash: ClientIpHash,
    db: Db,
) -> Acknowledgement:
    await blacklist_token(_access_payload(request))
    cookie = request.cookies.get(REFRESH_COOKIE)
    if cookie:
        await blacklist_token(decode_token(cookie, expected_type=REFRESH))
    clear_refresh_cookie(response)
    await audit_service.record(
        db,
        mm_id=ctx.mm_id,
        site_id=ctx.site_id,
        actor_user_id=ctx.user_id,
        action="auth.logout",
        object_type="user",
        object_id=ctx.user_id,
        payload={},
        ip_hash=ip_hash,
    )
    return Acknowledgement()


@router.post("/switch-site", response_model=SessionResponse)
async def switch_site(
    request: Request,
    response: Response,
    payload: SwitchSiteRequest,
    ctx: Annotated[TenantContext, Depends(get_current_context)],
    db: Db,
) -> SessionResponse:
    user = await _active_user(db, ctx.user_id)
    membership, site = _pick_membership(user, await _memberships(db, user), payload.site_id)
    await blacklist_token(_access_payload(request))
    # The old refresh token still names the old site, so it is replaced, not kept.
    cookie = request.cookies.get(REFRESH_COOKIE)
    if cookie:
        await blacklist_token(decode_token(cookie, expected_type=REFRESH))
    return _session(response, user, membership, site)


@router.get("/me", response_model=MeResponse)
async def me(ctx: Annotated[TenantContext, Depends(get_current_context)], db: Db) -> MeResponse:
    user = await _active_user(db, ctx.user_id)
    memberships = await _memberships(db, user)
    current, site = _pick_membership(user, memberships, ctx.site_id)
    return MeResponse(
        user=UserSummary.model_validate(user),
        site=SiteSummary.model_validate(site),
        permissions=sorted(_permissions_of(user, current)),
        sites=[
            MembershipSummary(
                site=SiteSummary.model_validate(member_site),
                role=membership.role,
                permissions=sorted(_permissions_of(user, membership)),
            )
            for membership, member_site in memberships
        ],
        locale=user.locale,
    )
