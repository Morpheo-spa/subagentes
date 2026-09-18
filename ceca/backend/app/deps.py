"""Request-scoped dependencies: the current user, the tenant context, permissions."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import reject_if_blacklisted, reject_if_stale
from app.db import get_session
from app.errors import DomainError, PermissionDeniedError
from app.models.base import TenantScoped
from app.models.tenancy import PERMISSIONS, Site, User, UserSite
from app.security import decode_token

SUPPORTED_LANGUAGES = ("es", "en")
DEFAULT_LANGUAGE = "es"

#: Roles whose holder administers **every** site of their own company. Anyone
#: else with ``users:manage`` administers only the sites they belong to. See
#: ``.claude/rules/backend.md`` § "Ámbito de administración".
COMPANY_ADMIN_ROLES: frozenset[str] = frozenset({"mm_admin"})


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Everything a query needs to stay inside its tenant.

    Built from the JWT only. Nothing here is ever read from the request body.
    """

    user_id: uuid.UUID
    mm_id: uuid.UUID
    site_id: uuid.UUID
    site_prefix: str | None
    permissions: frozenset[str] = field(default_factory=frozenset)
    is_superuser: bool = False
    locale: str = DEFAULT_LANGUAGE

    def has(self, permission: str) -> bool:
        return self.is_superuser or permission in self.permissions


def negotiate_language(accept_language: str | None) -> str:
    """Pick a supported language from the Accept-Language header. ES wins ties."""
    if not accept_language:
        return DEFAULT_LANGUAGE
    for chunk in accept_language.split(","):
        tag = chunk.split(";")[0].strip().lower()
        if not tag:
            continue
        primary = tag.split("-")[0]
        if primary in SUPPORTED_LANGUAGES:
            return primary
    return DEFAULT_LANGUAGE


async def get_language(
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
) -> str:
    return negotiate_language(accept_language)


async def get_db() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise DomainError("NOT_AUTHENTICATED", status_code=401)
    return token


async def get_current_context(request: Request) -> TenantContext:
    payload: dict[str, Any] = decode_token(_bearer_token(request))
    # A logged-out or rotated token is still cryptographically valid, so the
    # blacklist is the only thing that stops it. Check before trusting any claim.
    await reject_if_blacklisted(payload)
    # The permissions ride inside the token, so disabling an account or lowering
    # a role would otherwise take effect only when the token expires. The epoch
    # mark closes that window with one more Redis read.
    await reject_if_stale(payload)
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise DomainError("NO_SITE_SELECTED", status_code=403)
    return TenantContext(
        user_id=uuid.UUID(payload["sub"]),
        mm_id=uuid.UUID(payload["mm_id"]),
        site_id=uuid.UUID(tenant_id),
        site_prefix=payload.get("site_prefix"),
        permissions=frozenset(payload.get("permissions", [])),
        is_superuser=bool(payload.get("is_superuser")),
        locale=payload.get("locale") or DEFAULT_LANGUAGE,
    )


async def get_current_user(
    ctx: Annotated[TenantContext, Depends(get_current_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    user = await db.get(User, ctx.user_id)
    if user is None or not user.is_active:
        raise DomainError("NOT_AUTHENTICATED", status_code=401)
    return user


def require_permission(permission: str) -> Callable[[TenantContext], Awaitable[TenantContext]]:
    """Router guard. The backend decides; the frontend only hides."""

    async def guard(
        ctx: Annotated[TenantContext, Depends(get_current_context)],
    ) -> TenantContext:
        if not ctx.has(permission):
            raise PermissionDeniedError(permission=permission)
        return ctx

    return guard


@dataclass(frozen=True, slots=True)
class AdminScope:
    """How far an actor's ``users:manage`` reaches, read from the database.

    A site is a tenant (``CLAUDE.md`` § 1), so administering a site the actor
    does not belong to is a cross-tenant write. Two rules, and nothing else:

    * **which sites** — every site of the company for a superuser or for an
      ``mm_admin``; otherwise only the sites where the actor is a member;
    * **how much** — never more permission than the actor holds in that same
      site, so ``site_admin`` cannot hand out ``mm_admin``.

    Built from live rows rather than from the JWT: a scope taken from claims
    would be as stale as the claims.
    """

    user_id: uuid.UUID
    mm_id: uuid.UUID
    company_wide: bool
    site_ids: frozenset[uuid.UUID]
    permissions_by_site: dict[uuid.UUID, frozenset[str]]

    def may_administer(self, site_id: uuid.UUID) -> bool:
        return self.company_wide or site_id in self.site_ids

    def permissions_in(self, site_id: uuid.UUID) -> frozenset[str]:
        """What the actor may hand out in that site. Never more than they hold."""
        if self.company_wide:
            return frozenset(PERMISSIONS)
        return self.permissions_by_site.get(site_id, frozenset())


async def admin_scope(ctx: TenantContext, db: AsyncSession) -> AdminScope:
    """Resolve the actor's administration scope from their real memberships."""
    rows = (
        await db.execute(
            select(UserSite)
            .join(Site, Site.id == UserSite.site_id)
            .where(UserSite.user_id == ctx.user_id, Site.mm_id == ctx.mm_id)
        )
    ).scalars()
    memberships = list(rows)
    return AdminScope(
        user_id=ctx.user_id,
        mm_id=ctx.mm_id,
        company_wide=ctx.is_superuser
        or any(membership.role in COMPANY_ADMIN_ROLES for membership in memberships),
        site_ids=frozenset(membership.site_id for membership in memberships),
        permissions_by_site={
            membership.site_id: frozenset(membership.permissions()) for membership in memberships
        },
    )


def scoped[RowT: tuple[Any, ...]](
    stmt: Select[RowT], ctx: TenantContext, model: type[object]
) -> Select[RowT]:
    """Apply the two tenant filters. The only sanctioned way to read tenant data.

    Raises at call time if the model is not tenant scoped, so a missing filter is
    a loud failure rather than a silent cross-tenant read.
    """
    if not issubclass(model, TenantScoped):
        raise TypeError(f"{model.__name__} is not TenantScoped; scoped() would be a no-op filter")
    return stmt.where(model.mm_id == ctx.mm_id, model.site_id == ctx.site_id)


def scoped_select[ModelT](model: type[ModelT], ctx: TenantContext) -> Select[tuple[ModelT]]:
    return scoped(select(model), ctx, model)


CurrentContext = Annotated[TenantContext, Depends(get_current_context)]
CurrentUser = Annotated[User, Depends(get_current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]
Language = Annotated[str, Depends(get_language)]
