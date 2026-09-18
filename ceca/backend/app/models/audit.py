"""Append-only audit trail. Never updated, never deleted."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_tenant", "mm_id", "site_id", "created_at"),
        Index("ix_audit_logs_object", "object_type", "object_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    mm_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    site_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    #: Dotted verb, e.g. "document.uploaded", "print_job.confirmed", "share.revoked".
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(48), nullable=False)
    object_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
