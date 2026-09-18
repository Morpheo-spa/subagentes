"""Redis access, the JWT blacklist, and the per-user session epoch.

One module owns the client and the key prefixes so the writer (logout, refresh
rotation, a role change) and the reader (request authentication) can never
drift apart.

Both checks fail **closed**: if Redis does not answer, the connection error
propagates, the request ends in a 500 and the caller is denied. A revocation
store that fails open is not a revocation store.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis

from app.config import get_settings
from app.errors import DomainError

BLACKLIST_PREFIX = "jwt:blacklist:"
#: Tokens carry their permissions inside, so revoking a *claim* needs a second
#: mark: "every access token this user was issued before T is stale".
SESSION_EPOCH_PREFIX = "jwt:epoch:"

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


def _epoch_key(user_id: uuid.UUID | str) -> str:
    return f"{SESSION_EPOCH_PREFIX}{user_id}"


async def invalidate_user_sessions(user_id: uuid.UUID) -> None:
    """Void every access token this user already holds.

    Called when what the token *asserts* stops being true: the account is
    disabled, the role or the extra permissions change, a membership is added
    or removed, or the password is replaced. The mark only has to outlive the
    longest-lived access token, so it expires with one.

    The mark is a sub-second timestamp, and so is the ``iat`` it is compared
    against: a token minted a moment *after* the change carries the new claims
    and must keep working, which is how a live session recovers by refreshing.
    """
    ttl = get_settings().access_token_minutes * 60 + 60
    epoch = datetime.now(UTC).timestamp()
    await get_redis().setex(_epoch_key(user_id), ttl, repr(epoch))


async def reject_if_stale(payload: dict[str, Any]) -> None:
    """Refuse an access token issued before the user's claims last changed.

    One Redis read per request, the same shape as the blacklist. The refresh
    token is deliberately *not* checked here: ``/auth/refresh`` rebuilds the
    claims from the database, so it is how a still-valid session picks up its
    new permissions instead of being logged out.
    """
    subject = payload.get("sub")
    if not subject:
        return
    raw: Any = await get_redis().get(_epoch_key(str(subject)))
    if raw is None:
        return
    issued_at = payload.get("iat")
    if issued_at is None or float(issued_at) < float(raw):
        raise DomainError("SESSION_STALE", status_code=401)
