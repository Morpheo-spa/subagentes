"""Declarative base and the mixins every table is built from."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, MetaData, func
from sqlalchemy.dialects.postgresql import (
    UUID as PgUUID,  # noqa: N811 (alias avoids shadowing uuid.UUID)
)
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TenantScoped:
    """Marks a table as isolated per company (MM) and site.

    Inheriting this is what makes :func:`app.deps.scoped` accept the model. A table
    that holds tenant data and does not inherit it is a security bug, and
    ``tests/test_tenant_isolation.py`` fails the build over it.
    """

    @declared_attr
    @classmethod
    def mm_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            PgUUID(as_uuid=True), ForeignKey("mms.id", ondelete="RESTRICT"), nullable=False
        )

    @declared_attr
    @classmethod
    def site_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            PgUUID(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False
        )

    @declared_attr.directive
    @classmethod
    def __table_args__(cls) -> tuple:  # noqa: D105
        return (Index(f"ix_{cls.__tablename__}_tenant", "mm_id", "site_id", "created_at"),)


class OptimisticLock:
    """Guards against lost updates on concurrently edited rows."""

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    @declared_attr.directive
    @classmethod
    def __mapper_args__(cls) -> dict:  # noqa: D105
        return {"version_id_col": cls.__dict__["version"]}
