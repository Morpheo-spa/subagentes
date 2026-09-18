"""E-03: ``users:manage`` must not be a route to more privilege.

The audited attack was three requests long: a ``site_admin`` of one site read
their own user row (the query filtered by company, not by site), PATCHed
themselves to ``mm_admin`` in every site of the company, and switched site. The
tests below fail on the pre-fix code at each of those steps.

Every assertion checks the database as well as the status code: a route that
answers 403 after having written the row would still be an escalation.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.models.tenancy import Site, User, UserSite
from app.security import hash_password


async def _token(client: Any, email: str) -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "test-password"}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["tokens"]["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _role_in(db: Any, user_id: uuid.UUID, site_id: uuid.UUID) -> str | None:
    membership = (
        await db.execute(
            select(UserSite).where(UserSite.user_id == user_id, UserSite.site_id == site_id)
        )
    ).scalar_one_or_none()
    return None if membership is None else str(membership.role)


@pytest.fixture
async def company(db: Any, make_tenant: Any, make_user: Any) -> dict[str, Any]:
    """One company, two sites, and an administrator confined to the first."""
    mm, site_a = await make_tenant(slug="acme", prefix="AAA")
    site_b = Site(mm_id=mm.id, name="Site B", site_prefix="BBB", is_active=True)
    db.add(site_b)
    await db.flush()

    admin_a = await make_user(mm, site_a, email="admin-a@estampa-demo.com", role="site_admin")
    operator_a = await make_user(mm, site_a, email="op-a@estampa-demo.com", role="operator")
    operator_b = await make_user(mm, site_b, email="op-b@estampa-demo.com", role="operator")
    return {
        "mm": mm,
        "site_a": site_a,
        "site_b": site_b,
        "admin_a": admin_a,
        "operator_a": operator_a,
        "operator_b": operator_b,
    }


async def test_a_site_admin_cannot_promote_themselves(
    client: Any, db: Any, company: dict[str, Any]
) -> None:
    """The headline finding: self-service ``mm_admin``."""
    admin, site_a, site_b = company["admin_a"], company["site_a"], company["site_b"]
    token = await _token(client, admin.email)

    response = await client.patch(
        f"/api/v1/users/{admin.id}",
        headers=_auth(token),
        json={
            "memberships": [
                {"site_id": str(site_a.id), "role": "mm_admin"},
                {"site_id": str(site_b.id), "role": "mm_admin"},
            ]
        },
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "SELF_ROLE_CHANGE_FORBIDDEN"
    assert await _role_in(db, admin.id, site_a.id) == "site_admin"
    assert await _role_in(db, admin.id, site_b.id) is None, "no membership may have been created"


async def test_self_promotion_never_reaches_switch_site(
    client: Any, company: dict[str, Any]
) -> None:
    """Step 4 of the audited chain: the site the attacker tried to grant themselves."""
    admin, site_b = company["admin_a"], company["site_b"]
    token = await _token(client, admin.email)

    await client.patch(
        f"/api/v1/users/{admin.id}",
        headers=_auth(token),
        json={"memberships": [{"site_id": str(site_b.id), "role": "mm_admin"}]},
    )
    switched = await client.post(
        "/api/v1/auth/switch-site", headers=_auth(token), json={"site_id": str(site_b.id)}
    )

    assert switched.status_code == 403, switched.text
    assert switched.json()["detail"]["code"] == "SITE_NOT_ALLOWED"


async def test_a_site_admin_cannot_see_or_touch_a_user_of_another_site(
    client: Any, db: Any, company: dict[str, Any]
) -> None:
    """A site is a tenant, so the answer is 404 and not 403."""
    admin, victim, site_b = company["admin_a"], company["operator_b"], company["site_b"]
    token = await _token(client, admin.email)

    read = await client.get(f"/api/v1/users/{victim.id}", headers=_auth(token))
    assert read.status_code == 404, read.text
    assert read.json()["detail"]["code"] == "USER_NOT_FOUND"

    written = await client.patch(
        f"/api/v1/users/{victim.id}",
        headers=_auth(token),
        json={"memberships": [{"site_id": str(site_b.id), "role": "site_admin"}]},
    )
    assert written.status_code == 404, written.text
    assert await _role_in(db, victim.id, site_b.id) == "operator"

    listed = await client.get("/api/v1/users/", headers=_auth(token))
    assert listed.status_code == 200, listed.text
    assert {item["email"] for item in listed.json()["items"]} == {
        "admin-a@estampa-demo.com",
        "op-a@estampa-demo.com",
    }


async def test_a_site_admin_cannot_grant_a_role_above_their_own(
    client: Any, db: Any, company: dict[str, Any]
) -> None:
    """Lateral escalation: grant it to a puppet account, then sign in as them."""
    admin, target, site_a = company["admin_a"], company["operator_a"], company["site_a"]
    token = await _token(client, admin.email)

    response = await client.patch(
        f"/api/v1/users/{target.id}",
        headers=_auth(token),
        json={"memberships": [{"site_id": str(site_a.id), "role": "mm_admin"}]},
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "ROLE_ESCALATION_FORBIDDEN"
    assert await _role_in(db, target.id, site_a.id) == "operator"


async def test_a_site_admin_cannot_grant_a_permission_they_do_not_hold(
    client: Any, db: Any, company: dict[str, Any]
) -> None:
    """``site_admin`` has every permission except billing, so billing is the probe."""
    admin, target, site_a = company["admin_a"], company["operator_a"], company["site_a"]
    token = await _token(client, admin.email)

    response = await client.patch(
        f"/api/v1/users/{target.id}",
        headers=_auth(token),
        json={
            "memberships": [
                {
                    "site_id": str(site_a.id),
                    "role": "operator",
                    "extra_permissions": ["billing:manage"],
                }
            ]
        },
    )

    assert response.status_code == 403, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "PERMISSION_ESCALATION_FORBIDDEN"
    assert detail["params"]["permissions"] == "billing:manage"
    assert await _role_in(db, target.id, site_a.id) == "operator"


async def test_a_site_admin_cannot_add_a_membership_in_a_site_they_do_not_belong_to(
    client: Any, db: Any, company: dict[str, Any]
) -> None:
    admin, target, site_b = company["admin_a"], company["operator_a"], company["site_b"]
    token = await _token(client, admin.email)

    response = await client.patch(
        f"/api/v1/users/{target.id}",
        headers=_auth(token),
        json={"memberships": [{"site_id": str(site_b.id), "role": "operator"}]},
    )

    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "SITE_NOT_FOUND"
    assert await _role_in(db, target.id, site_b.id) is None


async def test_a_site_admin_cannot_strip_a_membership_out_of_their_reach(
    client: Any, db: Any, company: dict[str, Any]
) -> None:
    """Omitting a site from the list must not delete what the caller cannot grant."""
    admin, target = company["admin_a"], company["operator_a"]
    site_a, site_b = company["site_a"], company["site_b"]
    db.add(UserSite(user_id=target.id, site_id=site_b.id, role="site_admin", extra_permissions=[]))
    await db.flush()
    token = await _token(client, admin.email)

    response = await client.patch(
        f"/api/v1/users/{target.id}",
        headers=_auth(token),
        json={"memberships": [{"site_id": str(site_a.id), "role": "viewer"}]},
    )

    assert response.status_code == 200, response.text
    assert await _role_in(db, target.id, site_a.id) == "viewer", "the in-scope site was updated"
    assert await _role_in(db, target.id, site_b.id) == "site_admin", "the other site survived"


async def test_creating_a_user_cannot_hand_out_a_role_the_creator_lacks(
    client: Any, db: Any, company: dict[str, Any]
) -> None:
    """Otherwise the fix is one POST away from being pointless."""
    admin, site_a = company["admin_a"], company["site_a"]
    token = await _token(client, admin.email)

    response = await client.post(
        "/api/v1/users/",
        headers=_auth(token),
        json={
            "email": "puppet@estampa-demo.com",
            "full_name": "Puppet",
            "password": "a-long-enough-password",
            "memberships": [{"site_id": str(site_a.id), "role": "mm_admin"}],
        },
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "ROLE_ESCALATION_FORBIDDEN"
    assert (
        await db.scalar(select(User.id).where(User.email == "puppet@estampa-demo.com"))
    ) is None, "the user must not exist at all"


async def test_an_mm_admin_still_administers_every_site_of_the_company(
    client: Any, db: Any, company: dict[str, Any]
) -> None:
    """The fix must not lock the legitimate company administrator out."""
    mm, site_a, site_b = company["mm"], company["site_a"], company["site_b"]
    boss = User(
        mm_id=mm.id,
        email="boss@estampa-demo.com",
        full_name="Boss",
        hashed_password=hash_password("test-password"),
        is_active=True,
        default_site_id=site_a.id,
        locale="es",
    )
    db.add(boss)
    await db.flush()
    db.add(UserSite(user_id=boss.id, site_id=site_a.id, role="mm_admin", extra_permissions=[]))
    await db.flush()

    token = await _token(client, boss.email)
    target = company["operator_b"]

    read = await client.get(f"/api/v1/users/{target.id}", headers=_auth(token))
    assert read.status_code == 200, read.text

    response = await client.patch(
        f"/api/v1/users/{target.id}",
        headers=_auth(token),
        json={"memberships": [{"site_id": str(site_b.id), "role": "site_admin"}]},
    )
    assert response.status_code == 200, response.text
    assert await _role_in(db, target.id, site_b.id) == "site_admin"


async def test_a_default_site_the_user_does_not_belong_to_is_refused(
    client: Any, db: Any, company: dict[str, Any]
) -> None:
    """The one site id that legitimately travels in this body is still a target."""
    admin, target, site_b = company["admin_a"], company["operator_a"], company["site_b"]
    token = await _token(client, admin.email)

    response = await client.patch(
        f"/api/v1/users/{target.id}",
        headers=_auth(token),
        json={"default_site_id": str(site_b.id)},
    )

    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "SITE_NOT_FOUND"
    await db.refresh(target)
    assert target.default_site_id == company["site_a"].id
