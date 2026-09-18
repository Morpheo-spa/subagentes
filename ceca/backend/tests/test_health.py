"""The health endpoints tell the truth, and only as much of it as a probe needs.

``/health/live`` looks at nothing: a dependency outage must not get the
process restarted. ``/health/ready`` looks at Postgres, Redis and the local
storage root, each under a short timeout, and answers 503 naming the failed
check as ``failed`` and nothing more: no version, no host, no exception text.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest
import redis.exceptions

import app.main as main_module
from app import cache

ALLOWED_STATES = {"ok", "failed"}


@pytest.fixture
def healthy_dependencies(monkeypatch: pytest.MonkeyPatch, engine: Any, tmp_path: Path) -> None:
    """Point the checks at things that answer: the test engine, the Redis stub, a tmp dir."""
    monkeypatch.setattr(main_module, "engine", engine)
    monkeypatch.setattr(main_module.settings, "local_storage_root", str(tmp_path))


class _DownRedis:
    async def ping(self) -> bool:
        raise redis.exceptions.ConnectionError("Error 111 connecting to redis-internal:6379")


class _HungRedis:
    async def ping(self) -> bool:
        await asyncio.sleep(10)
        return True


async def test_live_answers_without_looking_at_anything(client: Any) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_stays_an_alias_of_live(client: Any) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_is_200_when_every_dependency_answers(
    client: Any, healthy_dependencies: None
) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": "ok", "redis": "ok", "storage": "ok"}
    assert response.headers["cache-control"] == "no-store"


async def test_ready_is_503_when_redis_is_down(
    client: Any, healthy_dependencies: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cache, "get_redis", lambda: _DownRedis())

    response = await client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["redis"] == "failed"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["storage"] == "ok"


async def test_ready_never_leaks_the_reason(
    client: Any, healthy_dependencies: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cache, "get_redis", lambda: _DownRedis())

    response = await client.get("/health/ready")

    assert "redis-internal" not in response.text
    assert "Error 111" not in response.text
    assert set(response.json()["checks"].values()) <= ALLOWED_STATES
    assert set(response.json()) == {"status", "checks"}


async def test_ready_gives_up_on_a_hung_dependency(
    client: Any, healthy_dependencies: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A readiness probe that hangs is worse than one that fails."""
    monkeypatch.setattr(cache, "get_redis", lambda: _HungRedis())

    started = time.perf_counter()
    response = await client.get("/health/ready")
    elapsed = time.perf_counter() - started

    assert response.status_code == 503
    assert response.json()["checks"]["redis"] == "failed"
    assert elapsed < main_module.READINESS_CHECK_TIMEOUT_SECONDS + 2


async def test_ready_is_503_when_the_storage_root_is_missing(
    client: Any, healthy_dependencies: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(main_module.settings, "local_storage_root", str(tmp_path / "absent"))

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["storage"] == "failed"


async def test_ready_is_503_when_the_database_does_not_answer(
    client: Any, healthy_dependencies: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken() -> bool:
        raise ConnectionRefusedError("postgres-internal:5432")

    monkeypatch.setattr(main_module, "_check_database", broken)

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "failed"
    assert "postgres-internal" not in response.text
