"""Redis access, and the JWT blacklist that makes logout mean something.

One module owns the client and the key prefix so the writer (logout, refresh
rotation) and the reader (request authentication) can never drift apart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis

from app.config import get_settings
from app.errors import DomainError

BLACKLIST_PREFIX = "jwt:blacklist:"

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(str(get_settings().redis_url), decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _remaining_seconds(payload: dict[str, Any]) -> int:
    """How long the token would still have lived. Nothing outlives its own expiry."""
    expires_at = payload.get("exp")
    if not expires_at:
        return 0
    return max(int(expires_at - datetime.now(UTC).timestamp()), 0)


async def blacklist_token(payload: dict[str, Any]) -> None:
    jti = payload.get("jti")
    ttl = _remaining_seconds(payload)
    if not jti or ttl <= 0:
        return
    await get_redis().setex(f"{BLACKLIST_PREFIX}{jti}", ttl, "1")


async def is_blacklisted(payload: dict[str, Any]) -> bool:
    jti = payload.get("jti")
    if not jti:
        return False
    return bool(await get_redis().exists(f"{BLACKLIST_PREFIX}{jti}"))


async def reject_if_blacklisted(payload: dict[str, Any]) -> None:
    if await is_blacklisted(payload):
        raise DomainError("TOKEN_REVOKED", status_code=401)
