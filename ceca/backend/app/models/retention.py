"""Retention policies. A delivery note's file expires; its record does not."""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OptimisticLock, TenantScoped, TimestampMixin, uuid_pk


class RetentionAction(enum.StrEnum):
    #: Remove the file from storage, keep the row with withdrawn_at + reason.
    WITHDRAW_FILE = "withdraw_file"
    #: Keep everything, only revoke the public QR token.
    REVOKE_SHARE = "revoke_share"
    #: Do nothing automatically, just flag it for a human.
    FLAG_ONLY = "flag_only"


class RetentionPolicy(Base, TenantScoped, TimestampMixin, OptimisticLock):
    __tablename__ = "retention_policies"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[RetentionAction] = mapped_column(
        String(24), nullable=False, default=RetentionAction.WITHDRAW_FILE
    )
    #: Free text pointing at the article that justifies the period. Shown in exports.
    legal_basis: Mapped[str | None] = mapped_column(String(255))
    warn_days_before: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
