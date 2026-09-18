"""Retention policies and what is about to expire."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.models.retention import RetentionAction
from app.schemas.common import Schema


class RetentionPolicyCreate(Schema):
    name: str = Field(min_length=1, max_length=120)
    #: Checked against the legal minimum in the router before anything is written.
    retention_days: int = Field(ge=1, le=36500)
    action: RetentionAction = RetentionAction.WITHDRAW_FILE
    legal_basis: str | None = Field(default=None, max_length=255)
    warn_days_before: int = Field(default=30, ge=0, le=365)
    is_default: bool = False
    is_active: bool = True


class RetentionPolicyUpdate(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    retention_days: int | None = Field(default=None, ge=1, le=36500)
    action: RetentionAction | None = None
    legal_basis: str | None = Field(default=None, max_length=255)
    warn_days_before: int | None = Field(default=None, ge=0, le=365)
    is_default: bool | None = None
    is_active: bool | None = None
    version: int | None = None


class RetentionPolicyRead(Schema):
    id: uuid.UUID
    name: str
    retention_days: int
    action: RetentionAction
    legal_basis: str | None
    warn_days_before: int
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
    version: int
    #: The floor the law puts under every policy, echoed so the UI can warn.
    legal_minimum_days: int


class UpcomingExpiryItem(Schema):
    document_id: uuid.UUID
    original_filename: str
    expires_at: datetime
    days_left: int
    policy_id: uuid.UUID | None
    policy_name: str | None
    action: RetentionAction | None
