"""The append-only trail. Every write that matters legally passes through here."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog

#: Actor recorded for work done by a background job, which belongs to no user.
SYSTEM_ACTOR_ID = UUID(int=0)


async def record(
    db: AsyncSession,
    *,
    mm_id: UUID | None,
    site_id: UUID | None,
    actor_user_id: UUID | None,
    action: str,
    object_type: str,
    object_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
    ip_hash: str | None = None,
) -> None:
    """Append one entry. Never updates, never deletes, never raises on content."""
    db.add(
        AuditLog(
            mm_id=mm_id,
            site_id=site_id,
            actor_user_id=None if actor_user_id == SYSTEM_ACTOR_ID else actor_user_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            payload=payload or {},
            ip_hash=ip_hash,
            created_at=datetime.now(UTC),
        )
    )
    await db.flush()
