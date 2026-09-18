"""Request-scoped dependencies: the current user, the tenant context, permissions."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import reject_if_blacklisted
from app.db import get_session
from app.errors import DomainError, PermissionDeniedError
from app.models.base import TenantScoped
from app.models.tenancy import User
from app.security import decode_token

SUPPORTED_LANGUAGES = ("es", "en")
DEFAULT_LANGUAGE = "es"


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


def require_permission(permission: str):
    """Router guard. The backend decides; the frontend only hides."""

    async def guard(
        ctx: Annotated[TenantContext, Depends(get_current_context)],
    ) -> TenantContext:
        if not ctx.has(permission):
            raise PermissionDeniedError(permission=permission)
        return ctx

    return guard


def scoped[ModelT](stmt: Select, ctx: TenantContext, model: type[ModelT]) -> Select:
    """Apply the two tenant filters. The only sanctioned way to read tenant data.

    Raises at call time if the model is not tenant scoped, so a missing filter is
    a loud failure rather than a silent cross-tenant read.
    """
    if not issubclass(model, TenantScoped):
        raise TypeError(f"{model.__name__} is not TenantScoped; scoped() would be a no-op filter")
    return stmt.where(model.mm_id == ctx.mm_id, model.site_id == ctx.site_id)


def scoped_select[ModelT](model: type[ModelT], ctx: TenantContext) -> Select:
    return scoped(select(model), ctx, model)


CurrentContext = Annotated[TenantContext, Depends(get_current_context)]
CurrentUser = Annotated[User, Depends(get_current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]
Language = Annotated[str, Depends(get_language)]
