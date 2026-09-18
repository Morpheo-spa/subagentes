"""Sessions: sign in, refresh, sign out, switch site, and who am I.

These routes carry no ``require_permission`` guard on purpose: they *establish*
the permission set rather than consume it, and a viewer with no resource
permission must still be able to sign in and read their own session.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from app.cache import blacklist_token, reject_if_blacklisted
from app.config import get_settings
from app.deps import Db, TenantContext, get_current_context
from app.errors import DomainError
from app.models.tenancy import PERMISSIONS, Site, User, UserSite
from app.routers import ClientIpHash
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    MembershipSummary,
    MeResponse,
    RefreshRequest,
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
    """One of the few sanctioned unscoped reads: the tenant is not known yet."""
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


def _session(user: User, membership: UserSite, site: Site) -> SessionResponse:
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
    return SessionResponse(
        tokens=TokenPair(
            access_token=create_token(**claims, token_type=ACCESS),
            refresh_token=create_token(**claims, token_type=REFRESH),
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
async def login(payload: LoginRequest, db: Db, ip_hash: ClientIpHash) -> SessionResponse:
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
    return _session(user, membership, site)


@router.post("/refresh", response_model=SessionResponse)
async def refresh(payload: RefreshRequest, db: Db) -> SessionResponse:
    claims = decode_token(payload.refresh_token, expected_type=REFRESH)
    await reject_if_blacklisted(claims)

    user = await _active_user(db, uuid.UUID(claims["sub"]))
    tenant_id = claims.get("tenant_id")
    membership, site = _pick_membership(
        user,
        await _memberships(db, user),
        uuid.UUID(tenant_id) if tenant_id else None,
    )
    await blacklist_token(claims)
    return _session(user, membership, site)


@router.post("/logout", response_model=Acknowledgement)
async def logout(
    request: Request,
    payload: LogoutRequest,
    ctx: Annotated[TenantContext, Depends(get_current_context)],
    ip_hash: ClientIpHash,
    db: Db,
) -> Acknowledgement:
    await blacklist_token(_access_payload(request))
    if payload.refresh_token:
        await blacklist_token(decode_token(payload.refresh_token, expected_type=REFRESH))
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
    payload: SwitchSiteRequest,
    ctx: Annotated[TenantContext, Depends(get_current_context)],
    db: Db,
) -> SessionResponse:
    user = await _active_user(db, ctx.user_id)
    membership, site = _pick_membership(user, await _memberships(db, user), payload.site_id)
    await blacklist_token(_access_payload(request))
    return _session(user, membership, site)


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
