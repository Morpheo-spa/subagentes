"""Reachability of a configured backend, recorded on the row."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import DomainError
from app.models.storage import StorageBackend
from app.services.storage.base import build_adapter


async def health_check(db: AsyncSession, backend: StorageBackend) -> bool:
    """Probe the backend and remember the answer. Never raises."""
    try:
        ok = await build_adapter(backend).health()
    except DomainError:
        ok = False
    backend.last_health_ok = ok
    await db.flush()
    return ok
