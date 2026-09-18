"""Company (MM) -> Site -> User. The spine of tenant isolation."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import (
    UUID as PgUUID,  # noqa: N811 (alias avoids shadowing uuid.UUID)
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, OptimisticLock, TimestampMixin, uuid_pk

#: Every permission the API enforces. The frontend only ever mirrors this list.
PERMISSIONS: tuple[str, ...] = (
    "documents:read",
    "documents:create",
    "documents:update",
    "documents:withdraw",
    "documents:export",
    "share:revoke",
    "printing:read",
    "printing:queue",
    "printing:print",
    "storage:read",
    "storage:manage",
    "retention:read",
    "retention:manage",
    "billing:read",
    "billing:manage",
    "users:read",
    "users:manage",
    "sites:read",
    "sites:manage",
    "audit:read",
)

ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "viewer": ("documents:read", "printing:read", "audit:read"),
    "operator": (
        "documents:read",
        "documents:create",
        "documents:update",
        "printing:read",
        "printing:queue",
        "printing:print",
    ),
    "site_admin": tuple(p for p in PERMISSIONS if not p.startswith("billing:")),
    "mm_admin": PERMISSIONS,
}


class MM(Base, TimestampMixin):
    """A customer company. The billing and quota boundary."""

    __tablename__ = "mms"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    tax_id: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    sites: Mapped[list[Site]] = relationship(back_populates="mm")


class Site(Base, TimestampMixin):
    """A physical site. The isolation boundary for documents."""

    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("mm_id", "site_prefix", name="uq_sites_mm_id_site_prefix"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    mm_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("mms.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    site_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Madrid", nullable=False)
    address: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    mm: Mapped[MM] = relationship(back_populates="sites")


class User(Base, TimestampMixin, OptimisticLock):
    """A person. Belongs to one MM and to one or more of its sites."""

    __tablename__ = "users"
    __table_args__ = (Index("ix_users_mm_id_email", "mm_id", "email", unique=True),)

    id: Mapped[uuid.UUID] = uuid_pk()
    mm_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("mms.id", ondelete="RESTRICT"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_site_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sites.id", ondelete="SET NULL")
    )
    locale: Mapped[str] = mapped_column(String(5), default="es", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list[UserSite]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSite(Base, TimestampMixin):
    """Membership of a user in a site, with the role that grants permissions."""

    __tablename__ = "user_sites"
    __table_args__ = (UniqueConstraint("user_id", "site_id", name="uq_user_sites_user_id_site_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="operator")
    extra_permissions: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), default=list, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="memberships")

    def permissions(self) -> set[str]:
        return set(ROLE_PERMISSIONS.get(self.role, ())) | set(self.extra_permissions)
