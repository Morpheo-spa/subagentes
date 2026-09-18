"""Per-tenant storage backends. Credentials are encrypted at rest."""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import Boolean, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OptimisticLock, TenantScoped, TimestampMixin, uuid_pk


class StorageKind(enum.StrEnum):
    LOCAL = "local"
    S3 = "s3"
    FTP = "ftp"
    SFTP = "sftp"
    GOOGLE_DRIVE = "google_drive"
    ONEDRIVE = "onedrive"


class StorageBackend(Base, TenantScoped, TimestampMixin, OptimisticLock):
    """Where a site's PDFs physically live."""

    __tablename__ = "storage_backends"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[StorageKind] = mapped_column(String(32), nullable=False)
    #: Non-secret settings: bucket, region, base path, host, port.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    #: Fernet-encrypted secrets. Never serialised by any schema, not even masked.
    config_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_health_ok: Mapped[bool | None] = mapped_column(Boolean)
