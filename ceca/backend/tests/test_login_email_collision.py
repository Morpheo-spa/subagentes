"""E-08: one company must not be able to break another company's login.

While ``users.email`` was unique per company, the administrator of company A
could register the address of company B's administrator inside A. The login
lookup has no tenant to scope by, so from that moment ``scalar_one_or_none()``
found two rows, raised ``MultipleResultsFound`` and answered 500 to *both*
owners of the address, for good. One POST, permanent cross-tenant denial of
service.

The policy chosen is global uniqueness (migration 0004): the address is the
login identity, so it identifies exactly one person. The attempt is refused up
front with 409, and the unique index is what actually guarantees it.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.tenancy import User, UserSite
from app.security import hash_password

VICTIM = "victim-admin@estampa-demo.com"


async def _login(client: Any, email: str) -> Any:
    return await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "test-password"}
    )


@pytest.fixture
async def two_companies(db: Any, make_tenant: Any, make_user: Any) -> dict[str, Any]:
    mm_a, site_a = await make_tenant(slug="attacker", prefix="ATK")
    mm_b, site_b = await make_tenant(slug="victim", prefix="VIC")
    attacker = await make_user(mm_a, site_a, email="boss-a@estampa-demo.com", role="mm_admin")
    victim = await make_user(mm_b, site_b, email=VICTIM, role="mm_admin")
    return {"site_a": site_a, "attacker": attacker, "victim": victim, "mm_a": mm_a}


async def test_a_company_cannot_register_another_companys_address(
    client: Any, two_companies: dict[str, Any]
) -> None:
    token = (await _login(client, two_companies["attacker"].email)).json()["tokens"]["access_token"]

    response = await client.post(
        "/api/v1/users/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": VICTIM,
            "full_name": "Not the victim",
            "password": "a-long-enough-password",
            "memberships": [{"site_id": str(two_companies["site_a"].id), "role": "operator"}],
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "EMAIL_ALREADY_EXISTS"


async def test_the_victims_login_still_works_afterwards(
    client: Any, two_companies: dict[str, Any]
) -> None:
    """The finding itself: before the fix this answered 500, for ever."""
    token = (await _login(client, two_companies["attacker"].email)).json()["tokens"]["access_token"]
    await client.post(
        "/api/v1/users/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": VICTIM.upper(),  # the lookup lowercases, so must the guard
            "full_name": "Not the victim",
            "password": "a-long-enough-password",
            "memberships": [{"site_id": str(two_companies["site_a"].id), "role": "operator"}],
        },
    )

    response = await _login(client, VICTIM)

    assert response.status_code == 200, response.text
    assert response.json()["user"]["email"] == VICTIM


async def test_the_database_refuses_the_duplicate_even_without_the_router(
    db: Any, two_companies: dict[str, Any]
) -> None:
    """The index is the guarantee; the 409 above is only the polite version of it."""
    db.add(
        User(
            mm_id=two_companies["mm_a"].id,
            email=VICTIM,
            full_name="Not the victim",
            hashed_password=hash_password("test-password"),
            is_active=True,
            default_site_id=two_companies["site_a"].id,
            locale="es",
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_the_same_address_is_still_one_person_across_sites(
    db: Any, two_companies: dict[str, Any]
) -> None:
    """Global uniqueness costs nothing real: a person joins sites by membership."""
    victim = two_companies["victim"]
    memberships = (
        await db.execute(UserSite.__table__.select().where(UserSite.user_id == victim.id))
    ).all()
    assert len(memberships) == 1
