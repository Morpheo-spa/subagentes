"""Sign in, token refresh, site switching and the session snapshot."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import EmailStr, Field

from app.schemas.common import Schema


class LoginRequest(Schema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class SwitchSiteRequest(Schema):
    """The one place a site id legitimately travels in a body: it is the target."""

    site_id: uuid.UUID


class TokenPair(Schema):
    """Only the access token is ever serialised.

    The refresh token goes back as an HttpOnly cookie, so it never reaches
    JavaScript and cannot be copied into browser storage.
    """

    access_token: str
    #: The OAuth 2.0 scheme name the client must put in the Authorization header.
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int


class SiteSummary(Schema):
    id: uuid.UUID
    name: str
    site_prefix: str
    timezone: str
    is_active: bool


class UserSummary(Schema):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    locale: str
    is_superuser: bool
    default_site_id: uuid.UUID | None = None


class MembershipSummary(Schema):
    """A site the signed in user may switch to, with what they can do there."""

    site: SiteSummary
    role: str
    permissions: list[str]


class SessionResponse(Schema):
    """Everything the SPA needs to boot after a login, refresh or site switch."""

    tokens: TokenPair
    user: UserSummary
    site: SiteSummary
    permissions: list[str]


class MeResponse(Schema):
    user: UserSummary
    site: SiteSummary
    permissions: list[str]
    sites: list[MembershipSummary]
    locale: str
