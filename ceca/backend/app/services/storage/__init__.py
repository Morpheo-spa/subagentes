"""Per-tenant storage backends, one adapter per :class:`StorageKind`."""

from __future__ import annotations

from app.services.storage.base import (
    REGISTRY,
    StorageAdapter,
    build_adapter,
    credentials_of,
    register,
)
from app.services.storage.health import health_check

__all__ = [
    "REGISTRY",
    "StorageAdapter",
    "build_adapter",
    "credentials_of",
    "health_check",
    "register",
]
