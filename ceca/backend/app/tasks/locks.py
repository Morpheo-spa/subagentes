"""A Redis lease so two overlapping runs of the same job do not both do the work.

The scheduler fires the retention sweep once a night, but "once" is a hope,
not a guarantee: a second scheduler replica, a manual run from the runbook
during the scheduled one, or a worker restarted mid-sweep all produce two
sweeps at the same time. Each document is only ever withdrawn once regardless
(a handled row no longer matches the query), but two sweeps racing over the
same batch would each delete the same files and write the same audit rows,
and a storage error in one would be reported twice.

``SET NX EX`` on the shared Redis client is the whole mechanism: whoever sets
the key runs, the other logs a skip and ends. The lease carries a random token
and is released only by its holder, so a run that outlives the TTL cannot
delete a newer holder's key.

Actors are synchronous, and every ``asyncio.run`` is a fresh event loop, so
the async client's connection pool cannot be carried from one call into the
next: each helper opens the client, uses it once and closes it again.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app import cache

logger = logging.getLogger("estampa.tasks.locks")

LOCK_PREFIX = "lock:"

#: Delete the key only if it still holds our token. One round trip, atomic.
_RELEASE_SCRIPT = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0"
)


@dataclass(frozen=True, slots=True)
class Lease:
    name: str
    token: str

    @property
    def key(self) -> str:
        return f"{LOCK_PREFIX}{self.name}"


@dataclass(frozen=True, slots=True)
class LockedRun[ResultT]:
    """What :func:`locked` returns: whether the lock was ours, and the result if it was."""

    acquired: bool
    result: ResultT | None = None


async def acquire_lock(name: str, *, ttl_seconds: int) -> Lease | None:
    """Take the lease, or return ``None`` if another run holds it."""
    lease = Lease(name=name, token=uuid4().hex)
    taken = await cache.get_redis().set(lease.key, lease.token, nx=True, ex=ttl_seconds)
    return lease if taken else None


async def release_lock(lease: Lease) -> bool:
    """Give the lease back. ``False`` means it had already expired or changed hands."""
    deleted = await cache.get_redis().eval(_RELEASE_SCRIPT, 1, lease.key, lease.token)
    return bool(deleted)


def locked[ResultT](
    name: str, *, ttl_seconds: int, operation: Callable[[], ResultT]
) -> LockedRun[ResultT]:
    """Run ``operation`` under the lease, from a synchronous actor.

    ``ttl_seconds`` bounds how long a crashed holder can block the next run;
    pick it above the longest honest run. The lease is released after
    ``operation`` returns, and only then, so whoever comes next sees the
    committed state and not a half-finished batch.
    """
    lease = _in_fresh_loop(acquire_lock(name, ttl_seconds=ttl_seconds))
    if lease is None:
        return LockedRun(acquired=False)
    try:
        return LockedRun(acquired=True, result=operation())
    finally:
        if not _in_fresh_loop(release_lock(lease)):
            logger.warning("lock %s was not ours to release: the run outlived its lease", lease.key)


def _in_fresh_loop[ResultT](coroutine: Coroutine[Any, Any, ResultT]) -> ResultT:
    async def _use_once() -> ResultT:
        try:
            return await coroutine
        finally:
            await cache.close_redis()

    return asyncio.run(_use_once())
