"""Sites, users and the memberships that bind them."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from app.models.tenancy import PERMISSIONS, ROLE_PERMISSIONS
from app.schemas.common import Schema


class SiteCreate(Schema):
    name: str = Field(min_length=1, max_length=160)
    site_prefix: str = Field(min_length=1, max_length=8, pattern=r"^[A-Za-z0-9-]+$")
    timezone: str = Field(default="Europe/Madrid", max_length=64)
    address: str | None = Field(default=None, max_length=255)


class SiteUpdate(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    timezone: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class SiteRead(Schema):
    id: uuid.UUID
    name: str
    site_prefix: str
    timezone: str
    address: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MembershipWrite(Schema):
    """Grants a user access to one site of the caller's company.

    ``site_id`` here is the *target* of the operation, never the tenant of the
    request: it is checked against the caller's ``mm_id`` before it is used.
    """

    site_id: uuid.UUID
    role: str = Field(default="operator", max_length=32)
    extra_permissions: list[str] = Field(default_factory=list)

    @field_validator("role")
    @classmethod
    def _known_role(cls, value: str) -> str:
        if value not in ROLE_PERMISSIONS:
            raise ValueError(f"unknown role: {value}")
        return value

    @field_validator("extra_permissions")
    @classmethod
    def _known_permissions(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(PERMISSIONS))
        if unknown:
            raise ValueError(f"unknown permissions: {', '.join(unknown)}")
        return value

    def granted_permissions(self) -> set[str]:
        """Everything this membership would hand out, role and extras together.

        The router compares it against what the caller holds in the same site:
        a grant is only legitimate if it is a subset of the granter's own.
        """
        return set(ROLE_PERMISSIONS.get(self.role, ())) | set(self.extra_permissions)


class MembershipRead(Schema):
    id: uuid.UUID
    site_id: uuid.UUID
    site_name: str
    role: str
    extra_permissions: list[str]
    permissions: list[str]


class UserCreate(Schema):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=12, max_length=256)
    locale: str = Field(default="es", max_length=5)
    memberships: list[MembershipWrite] = Field(min_length=1)
    default_site_id: uuid.UUID | None = None


class UserUpdate(Schema):
    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    password: str | None = Field(default=None, min_length=12, max_length=256)
    locale: str | None = Field(default=None, max_length=5)
    is_active: bool | None = None
    default_site_id: uuid.UUID | None = None
    memberships: list[MembershipWrite] | None = None
    version: int | None = None


class UserRead(Schema):
    """Never carries ``hashed_password``. There is no field for it on purpose."""

    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_active: bool
    is_superuser: bool
    locale: str
    default_site_id: uuid.UUID | None
    last_login_at: datetime | None
    created_at: datetime
    memberships: list[MembershipRead] = Field(default_factory=list)


class RoleRead(Schema):
    code: str
    permissions: list[str]


class RoleCatalogResponse(Schema):
    """Roles and the whole permission vocabulary, so the UI never hardcodes them."""

    roles: list[RoleRead]
    permissions: list[str]
