"""The Dramatiq broker and the plumbing every actor shares.

An actor is handed IDs and a tenant, never a JWT and never credentials.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.deps import TenantContext
from app.services.audit import SYSTEM_ACTOR_ID

broker = RedisBroker(url=str(get_settings().redis_url))
dramatiq.set_broker(broker)


def run[ResultT](operation: Callable[[AsyncSession], Awaitable[ResultT]]) -> ResultT:
    """Run one async unit of work in its own session, from a synchronous actor."""

    async def _run() -> ResultT:
        async with SessionLocal() as session:
            try:
                result = await operation(session)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            return result

    return asyncio.run(_run())


def tenant_context(mm_id: str | UUID, site_id: str | UUID) -> TenantContext:
    """The context a job runs under: a tenant, and no user behind it."""
    return TenantContext(
        user_id=SYSTEM_ACTOR_ID,
        mm_id=UUID(str(mm_id)),
        site_id=UUID(str(site_id)),
        site_prefix=None,
        permissions=frozenset(),
        is_superuser=True,
    )
