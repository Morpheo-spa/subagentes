"""Closing a site must close the sessions of the people who worked there.

Deactivating a site revokes access, but an access token keeps asserting it for
as long as it lives. Requests for the closed site were already refused with a
403, so this was never a way back into that site; what stayed wrong is that the
session itself survived a revoked grant. It is now voided, and the member signs
in again with whatever access they still have.
"""

from __future__ import annotations

from typing import Any


async def _sign_in(client: Any, email: str) -> Any:
    return await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "test-password"}
    )


async def test_deactivating_a_site_ends_its_members_sessions(
    client: Any, make_tenant: Any, make_user: Any
) -> None:
    mm, site = await make_tenant()
    await make_user(mm, site, email="closer@estampa-demo.com", role="mm_admin")
    await make_user(mm, site, email="worker@estampa-demo.com", role="operator")

    worker = await _sign_in(client, "worker@estampa-demo.com")
    assert worker.status_code == 200, worker.text
    worker_token = worker.json()["tokens"]["access_token"]
    worker_auth = {"Authorization": f"Bearer {worker_token}"}

    still_working = await client.get("/api/v1/auth/me", headers=worker_auth)
    assert still_working.status_code == 200, "the worker should start out signed in"

    admin = await _sign_in(client, "closer@estampa-demo.com")
    admin_auth = {"Authorization": f"Bearer {admin.json()['tokens']['access_token']}"}
    closed = await client.delete(f"/api/v1/sites/{site.id}", headers=admin_auth)
    assert closed.status_code == 200, closed.text

    after = await client.get("/api/v1/auth/me", headers=worker_auth)
    # 403 was the old behaviour: refused, but still a live session.
    assert after.status_code == 401, "the session must be voided, not merely refused"


async def test_closing_one_site_leaves_another_tenant_alone(
    client: Any, make_tenant: Any, make_user: Any
) -> None:
    """The invalidation is per user, so it must not spill across companies."""
    mm_a, site_a = await make_tenant()
    await make_user(mm_a, site_a, email="admin-a@estampa-demo.com", role="mm_admin")

    mm_b, site_b = await make_tenant(slug="other")
    await make_user(mm_b, site_b, email="worker-b@estampa-demo.com", role="operator")

    worker_b = await _sign_in(client, "worker-b@estampa-demo.com")
    worker_b_auth = {"Authorization": f"Bearer {worker_b.json()['tokens']['access_token']}"}

    admin_a = await _sign_in(client, "admin-a@estampa-demo.com")
    admin_a_auth = {"Authorization": f"Bearer {admin_a.json()['tokens']['access_token']}"}
    await client.delete(f"/api/v1/sites/{site_a.id}", headers=admin_a_auth)

    unaffected = await client.get("/api/v1/auth/me", headers=worker_b_auth)
    assert unaffected.status_code == 200, "another company's session must be untouched"
