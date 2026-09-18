"""Storage backends. Secrets go in and never come back out."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.models.storage import StorageKind
from app.schemas.common import Schema


class StorageBackendCreate(Schema):
    name: str = Field(min_length=1, max_length=120)
    kind: StorageKind
    #: Non-secret settings only: bucket, region, host, port, base path.
    config: dict[str, Any] = Field(default_factory=dict)
    #: Credentials. Encrypted before they are stored and never serialised again.
    secrets: dict[str, str] = Field(default_factory=dict)
    is_default: bool = False
    is_active: bool = True


class StorageBackendUpdate(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    config: dict[str, Any] | None = None
    #: Omitted leaves the stored credentials untouched.
    secrets: dict[str, str] | None = None
    is_default: bool | None = None
    is_active: bool | None = None
    version: int | None = None


class StorageBackendRead(Schema):
    """There is deliberately no ``secrets`` field, not even a masked one."""

    id: uuid.UUID
    name: str
    kind: StorageKind
    config: dict[str, Any] = Field(default_factory=dict)
    is_default: bool
    is_active: bool
    last_health_ok: bool | None
    created_at: datetime
    updated_at: datetime
    version: int


class StorageTestResult(Schema):
    ok: bool
    kind: StorageKind
    checked_at: datetime
    code: str | None = None
