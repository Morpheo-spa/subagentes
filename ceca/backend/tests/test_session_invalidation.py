"""E-12: a change of privilege must bite before the token expires.

The access token carries ``permissions`` inside itself and nothing contrasted
them, so disabling an account, lowering a role or removing a membership did
nothing for up to ``access_token_minutes`` (30). A dismissal or a compromised
account left a half-hour window the application could not close.

The fix is a per-user epoch in Redis, written whenever the claims stop being
true and read once per request, next to the blacklist. Same shape, same
failure mode: **closed**.
"""

from __future__ import annotations

from typing import Any

import pytest
import redis.exceptions
from sqlalchemy import select

from app.models.tenancy import UserSite

pytestmark = pytest.mark.anyio

#: Reads its permissions straight from the token and touches nothing else, so a
#: 200 here means the claims were trusted verbatim.
PROBE = "/api/v1/users/roles"


async def _token(client: Any, email: str) -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "test-password"}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["tokens"]["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def session_pair(db: Any, make_tenant: Any, make_user: Any) -> dict[str, Any]:
    mm, site = await make_tenant(slug="revoke", prefix="REV")
    boss = await make_user(mm, site, email="boss@estampa-demo.com", role="mm_admin")
    victim = await make_user(mm, site, email="victim@estampa-demo.com", role="site_admin")
    return {"mm": mm, "site": site, "boss": boss, "victim": victim}


async def test_deactivating_a_user_cuts_their_live_session(
    client: Any, session_pair: dict[str, Any]
) -> None:
    boss_token = await _token(client, "boss@estampa-demo.com")
    victim_token = await _token(client, "victim@estampa-demo.com")
    assert (await client.get(PROBE, headers=_auth(victim_token))).status_code == 200

    disabled = await client.patch(
        f"/api/v1/users/{session_pair['victim'].id}",
        headers=_auth(boss_token),
        json={"is_active": False},
    )
    assert disabled.status_code == 200, disabled.text

    after = await client.get(PROBE, headers=_auth(victim_token))
    assert after.status_code == 401, "the token outlived the account"
    assert after.json()["detail"]["code"] == "SESSION_STALE"


async def test_lowering_a_role_takes_effect_on_the_next_request(
    client: Any, db: Any, session_pair: dict[str, Any]
) -> None:
    boss_token = await _token(client, "boss@estampa-demo.com")
    # Last login wins the refresh cookie, and the victim is the one who refreshes.
    victim_token = await _token(client, "victim@estampa-demo.com")
    assert (await client.get(PROBE, headers=_auth(victim_token))).status_code == 200

    demoted = await client.patch(
        f"/api/v1/users/{session_pair['victim'].id}",
        headers=_auth(boss_token),
        json={"memberships": [{"site_id": str(session_pair["site"].id), "role": "viewer"}]},
    )
    assert demoted.status_code == 200, demoted.text

    assert (await client.get(PROBE, headers=_auth(victim_token))).status_code == 401

    # Refreshing is how a still-legitimate session picks up the new claims: the
    # refresh token is checked against the database, not against the epoch.
    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    assert "users:read" not in refreshed.json()["permissions"]
    assert (
        await client.get(PROBE, headers=_auth(refreshed.json()["tokens"]["access_token"]))
    ).status_code == 403, "the demoted session must not read the user catalogue"


async def test_removing_a_membership_cuts_the_session_for_that_site(
    client: Any, db: Any, session_pair: dict[str, Any]
) -> None:
    mm, site, victim = session_pair["mm"], session_pair["site"], session_pair["victim"]
    from app.models.tenancy import Site

    other = Site(mm_id=mm.id, name="Other", site_prefix="OTH", is_active=True)
    db.add(other)
    await db.flush()
    db.add(UserSite(user_id=victim.id, site_id=other.id, role="operator", extra_permissions=[]))
    await db.flush()

    boss_token = await _token(client, "boss@estampa-demo.com")
    victim_token = await _token(client, "victim@estampa-demo.com")
    assert (await client.get(PROBE, headers=_auth(victim_token))).status_code == 200

    removed = await client.patch(
        f"/api/v1/users/{victim.id}",
        headers=_auth(boss_token),
        json={"memberships": [{"site_id": str(other.id), "role": "operator"}]},
    )
    assert removed.status_code == 200, removed.text
    assert (
        await db.scalar(
            select(UserSite.id).where(UserSite.user_id == victim.id, UserSite.site_id == site.id)
        )
    ) is None

    assert (await client.get(PROBE, headers=_auth(victim_token))).status_code == 401


async def test_an_untouched_session_keeps_working(
    client: Any, session_pair: dict[str, Any]
) -> None:
    """The epoch is per user: revoking one must not log the company out."""
    boss_token = await _token(client, "boss@estampa-demo.com")
    victim_token = await _token(client, "victim@estampa-demo.com")

    await client.patch(
        f"/api/v1/users/{session_pair['victim'].id}",
        headers=_auth(boss_token),
        json={"is_active": False},
    )

    assert (await client.get(PROBE, headers=_auth(boss_token))).status_code == 200
    assert (await client.get(PROBE, headers=_auth(victim_token))).status_code == 401


async def test_a_harmless_edit_does_not_invalidate_the_session(
    client: Any, session_pair: dict[str, Any]
) -> None:
    """Renaming somebody is not a privilege change; do not log them out for it."""
    boss_token = await _token(client, "boss@estampa-demo.com")
    victim_token = await _token(client, "victim@estampa-demo.com")

    renamed = await client.patch(
        f"/api/v1/users/{session_pair['victim'].id}",
        headers=_auth(boss_token),
        json={"full_name": "Victim Renamed"},
    )
    assert renamed.status_code == 200, renamed.text
    assert (await client.get(PROBE, headers=_auth(victim_token))).status_code == 200


async def test_the_check_fails_closed_when_redis_is_unreachable(
    client: Any, app: Any, db: Any, session_pair: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Like the blacklist: no answer from Redis means no access, never free access."""
    import app.cache as cache

    token = await _token(client, "victim@estampa-demo.com")
    assert (await client.get(PROBE, headers=_auth(token))).status_code == 200

    class DeadRedis:
        async def exists(self, *_: str) -> int:
            return 0

        async def get(self, *_: str) -> str | None:
            raise redis.exceptions.ConnectionError("redis is down")

    monkeypatch.setattr(cache, "_client", DeadRedis(), raising=False)

    # A client that lets the app's own 500 handler answer, the way uvicorn does,
    # instead of re-raising the exception into the test.
    import httpx

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as unlucky:
        response = await unlucky.get(PROBE, headers=_auth(token))

    assert response.status_code != 200, "an unanswerable revocation check must deny"
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "INTERNAL_ERROR"
