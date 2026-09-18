"""Two retention sweeps that overlap must not process the same document twice.

The sweep runs from a synchronous actor: each run opens its own event loop,
so two runs are two threads here, exactly as two worker threads would be. The
first is held inside ``apply_due`` while the second starts; the second must
find the Redis lease taken and leave without touching the database. The lease
is a real ``SET NX EX`` / compare-and-delete, against an in-memory Redis that
implements just those two commands.
"""

from __future__ import annotations

import importlib
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.services.retention as retention_service
from app import cache
from app.models.audit import AuditLog
from app.models.retention import RetentionAction, RetentionPolicy
from app.services.retention import FLAGGED_ACTION
from app.tasks import locks
from app.tasks.retention import SWEEP_LOCK, run_sweep

# ``app.tasks`` re-exports the broker *instance* under the same name as the
# module, so attribute access would hand back the RedisBroker, not the module.
broker_module = importlib.import_module("app.tasks.broker")


class FakeRedis:
    """SET NX EX and the compare-and-delete script, shared across threads."""

    def __init__(self) -> None:
        self._entries: dict[str, str] = {}
        self._guard = threading.Lock()
        self.set_calls = 0

    async def set(
        self, key: str, value: str, *, nx: bool = False, ex: int | None = None
    ) -> bool | None:
        with self._guard:
            self.set_calls += 1
            if nx and key in self._entries:
                return None
            self._entries[key] = value
            return True

    async def eval(self, _script: str, _numkeys: int, key: str, token: str) -> int:
        with self._guard:
            if self._entries.get(key) == token:
                del self._entries[key]
                return 1
            return 0

    async def get(self, key: str) -> str | None:
        return self._entries.get(key)

    async def aclose(self) -> None:
        return None


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()

    async def _no_close() -> None:
        return None

    monkeypatch.setattr(cache, "get_redis", lambda: fake)
    monkeypatch.setattr(cache, "close_redis", _no_close)
    return fake


@pytest.fixture
def actor_sessions(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Any:
    """The session factory the actor uses, on a pool-less engine.

    Each sweep runs ``asyncio.run`` in its own thread, and a pooled connection
    cannot cross event loops, so every connection is opened and closed inside
    the loop that uses it.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(broker_module, "SessionLocal", factory)
    return factory


@pytest.fixture
async def expired_document(db: Any, make_tenant: Any, make_document: Any) -> Any:
    """A document past its date under a flag-only policy, committed for other sessions."""
    mm, site = await make_tenant(slug="sweep", prefix="SWP")
    policy = RetentionPolicy(
        mm_id=mm.id,
        site_id=site.id,
        name="flag only",
        retention_days=365,
        action=RetentionAction.FLAG_ONLY,
        is_default=True,
        is_active=True,
    )
    db.add(policy)
    await db.flush()
    document = await make_document(mm, site)
    document.retention_policy_id = policy.id
    document.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db.commit()
    return document


class _Held:
    """Holds the first sweep inside apply_due until the test lets it go."""

    def __init__(self, original: Callable[..., Any]) -> None:
        self.original = original
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    async def __call__(self, db: Any, *, limit: int) -> int:
        self.calls += 1
        self.entered.set()
        assert self.release.wait(timeout=10), "the test never released the first sweep"
        result: int = await self.original(db, limit=limit)
        return result


def _sweep_in_thread(results: dict[str, Any], key: str) -> threading.Thread:
    def target() -> None:
        results[key] = run_sweep(limit=10)

    thread = threading.Thread(target=target, name=f"sweep-{key}")
    thread.start()
    return thread


async def _flag_count(db: Any, document_id: Any) -> int:
    stmt = select(func.count(AuditLog.id)).where(
        AuditLog.object_id == document_id, AuditLog.action == FLAGGED_ACTION
    )
    return int(await db.scalar(stmt) or 0)


async def test_two_overlapping_sweeps_process_the_document_once(
    db: Any,
    fake_redis: FakeRedis,
    actor_sessions: Any,
    expired_document: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    held = _Held(retention_service.apply_due)
    monkeypatch.setattr(retention_service, "apply_due", held)
    results: dict[str, Any] = {}

    first = _sweep_in_thread(results, "first")
    assert held.entered.wait(timeout=10), "the first sweep never reached apply_due"

    # The first sweep is inside the batch and holds the lease. The second one
    # starts now, sees the lease, and must leave without sweeping.
    second = _sweep_in_thread(results, "second")
    second.join(timeout=10)
    assert not second.is_alive()
    assert results["second"].acquired is False
    assert results["second"].result is None
    assert held.calls == 1, "the second sweep ran apply_due despite the lease"

    held.release.set()
    first.join(timeout=10)
    assert not first.is_alive()
    assert results["first"].acquired is True
    assert results["first"].result == 1

    assert await _flag_count(db, expired_document.id) == 1
    assert fake_redis.set_calls == 2, "both sweeps tried the lease exactly once"


async def test_the_lease_is_released_and_the_next_sweep_finds_nothing_left(
    db: Any, fake_redis: FakeRedis, actor_sessions: Any, expired_document: Any
) -> None:
    results: dict[str, Any] = {}
    _sweep_in_thread(results, "first").join(timeout=10)
    assert results["first"].acquired is True
    assert results["first"].result == 1
    assert await fake_redis.get(f"{locks.LOCK_PREFIX}{SWEEP_LOCK}") is None, "lease not released"

    # Idempotent on its own, too: the flagged document no longer matches.
    _sweep_in_thread(results, "again").join(timeout=10)
    assert results["again"].acquired is True
    assert results["again"].result == 0
    assert await _flag_count(db, expired_document.id) == 1


async def test_a_lease_that_changed_hands_is_not_deleted_by_the_old_holder(
    fake_redis: FakeRedis,
) -> None:
    ours = await locks.acquire_lock("demo", ttl_seconds=60)
    assert ours is not None
    assert await locks.acquire_lock("demo", ttl_seconds=60) is None

    # Simulate expiry: the key is gone, and someone else takes it.
    await fake_redis.eval("", 1, ours.key, ours.token)
    theirs = await locks.acquire_lock("demo", ttl_seconds=60)
    assert theirs is not None

    assert await locks.release_lock(ours) is False, "an expired lease must not delete a new one"
    assert await fake_redis.get(theirs.key) == theirs.token
    assert await locks.release_lock(theirs) is True
