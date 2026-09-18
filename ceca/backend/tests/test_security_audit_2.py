"""Findings N-01..N-13 of ``docs/SECURITY-AUDIT-2.md``: the fixes that fixed less than they claimed.

Each test here fails on the code the second audit reviewed. The Traefik rate
limiter key (N-01) lives in ``test_infra_hardening.py`` next to the rest of the
proxy checks.
"""

from __future__ import annotations

from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.cookies import REFRESH_COOKIE
from app.errors import DomainError
from app.models.tenancy import User, UserSite
from app.security import hash_password, verify_password
from app.services.storage import s3
from app.services.storage.validation import (
    validate_config,
    validate_endpoint_url,
    validate_host,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


async def _token(client: Any, email: str) -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "test-password"}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["tokens"]["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- N-03: a site_admin must not take over an account that outranks them -------


@pytest.fixture
async def shared_site(db: Any, make_tenant: Any, make_user: Any) -> dict[str, Any]:
    """One site where the company administrator and a site administrator coexist."""
    mm, site = await make_tenant(slug="acme", prefix="AAA")
    boss = User(
        mm_id=mm.id,
        email="boss@estampa-demo.com",
        full_name="Boss",
        hashed_password=hash_password("test-password"),
        is_active=True,
        default_site_id=site.id,
        locale="es",
    )
    db.add(boss)
    await db.flush()
    db.add(UserSite(user_id=boss.id, site_id=site.id, role="mm_admin", extra_permissions=[]))
    await db.flush()
    site_admin = await make_user(mm, site, email="site-admin@estampa-demo.com", role="site_admin")
    operator = await make_user(mm, site, email="operator@estampa-demo.com", role="operator")
    return {"mm": mm, "site": site, "boss": boss, "site_admin": site_admin, "operator": operator}


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"password": "owned-by-site-admin-1"}, id="password"),
        pytest.param({"is_active": False}, id="deactivate"),
        pytest.param({"memberships": []}, id="strip-memberships"),
    ],
)
async def test_a_site_admin_cannot_take_over_the_company_administrator(
    client: Any, db: Any, shared_site: dict[str, Any], change: dict[str, Any]
) -> None:
    """The N-03 chain: PATCH the mm_admin's password, log in as them, own billing."""
    boss, site_admin = shared_site["boss"], shared_site["site_admin"]
    token = await _token(client, site_admin.email)

    response = await client.patch(f"/api/v1/users/{boss.id}", headers=_auth(token), json=change)

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "USER_OUTRANKS_ACTOR"
    await db.refresh(boss)
    assert boss.is_active is True
    assert verify_password("test-password", boss.hashed_password)
    still_admin = (
        await db.execute(
            select(UserSite).where(UserSite.user_id == boss.id, UserSite.role == "mm_admin")
        )
    ).scalar_one_or_none()
    assert still_admin is not None


async def test_a_site_admin_still_manages_the_people_below_them(
    client: Any, db: Any, shared_site: dict[str, Any]
) -> None:
    """The rank check must not take the legitimate delegation away."""
    operator, site_admin = shared_site["operator"], shared_site["site_admin"]
    token = await _token(client, site_admin.email)

    response = await client.patch(
        f"/api/v1/users/{operator.id}",
        headers=_auth(token),
        json={"password": "reset-by-site-admin-1", "is_active": False},
    )

    assert response.status_code == 200, response.text
    await db.refresh(operator)
    assert operator.is_active is False
    assert verify_password("reset-by-site-admin-1", operator.hashed_password)


async def test_the_company_administrator_still_resets_a_site_admin(
    client: Any, db: Any, shared_site: dict[str, Any]
) -> None:
    boss, site_admin = shared_site["boss"], shared_site["site_admin"]
    token = await _token(client, boss.email)

    response = await client.patch(
        f"/api/v1/users/{site_admin.id}",
        headers=_auth(token),
        json={"password": "reset-by-the-boss-1"},
    )

    assert response.status_code == 200, response.text
    await db.refresh(site_admin)
    assert verify_password("reset-by-the-boss-1", site_admin.hashed_password)


async def test_a_site_admin_cannot_reset_a_colleague_who_also_works_elsewhere(
    client: Any, db: Any, make_tenant: Any, make_user: Any
) -> None:
    """A membership in a site outside the actor's reach is another tenant's account."""
    mm, site_a = await make_tenant(slug="acme", prefix="AAA")
    from app.models.tenancy import Site

    site_b = Site(mm_id=mm.id, name="Site B", site_prefix="BBB", is_active=True)
    db.add(site_b)
    await db.flush()
    admin_a = await make_user(mm, site_a, email="admin-a@estampa-demo.com", role="site_admin")
    roaming = await make_user(mm, site_a, email="roaming@estampa-demo.com", role="operator")
    db.add(UserSite(user_id=roaming.id, site_id=site_b.id, role="site_admin", extra_permissions=[]))
    await db.flush()
    token = await _token(client, admin_a.email)

    response = await client.patch(
        f"/api/v1/users/{roaming.id}", headers=_auth(token), json={"password": "hijack-site-b-1"}
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "USER_OUTRANKS_ACTOR"


# --- N-04 / N-06: the S3 client keeps its timeouts and never follows a redirect


def test_the_s3_client_config_keeps_its_timeouts_with_path_style() -> None:
    plain, path_style = s3._client_config(False), s3._client_config(True)
    for config in (plain, path_style):
        assert config.connect_timeout == 5
        assert config.read_timeout == 30
        assert config.retries == {"max_attempts": 2}
    assert path_style.s3 == {"addressing_style": "path"}


async def test_the_s3_http_session_refuses_redirects() -> None:
    """A whitelisted endpoint answering 307 must not become an internal port scan."""
    from aiobotocore.config import AioConfig

    config = s3._client_config(False)
    assert isinstance(config, AioConfig)
    session = config.http_session_cls()
    try:
        client = await session._get_session(None)
        assert type(client).__name__ == "_NoRedirectClientSession"
    finally:
        await session.close()


# --- N-05 / N-09: FTP hosts get the same check as S3 endpoints; CGNAT is internal


@pytest.mark.parametrize(
    "host",
    [
        pytest.param("10.0.0.5", id="private"),
        pytest.param("127.0.0.1", id="loopback"),
        pytest.param("169.254.169.254", id="metadata"),
        pytest.param("100.100.100.200", id="cgnat-metadata"),
        pytest.param("::1", id="loopback-v6"),
    ],
)
def test_an_internal_ftp_host_is_refused(host: str) -> None:
    with pytest.raises(DomainError) as caught:
        validate_config("ftp", {"host": host, "port": 21})
    assert caught.value.code == "STORAGE_ENDPOINT_NOT_PUBLIC"


def test_an_ftp_host_is_required() -> None:
    with pytest.raises(DomainError) as caught:
        validate_config("ftp", {"port": 21})
    assert caught.value.code == "STORAGE_ENDPOINT_INVALID"


@pytest.mark.parametrize("port", ["0", "70000", "abc", -1])
def test_an_impossible_ftp_port_is_refused(port: Any) -> None:
    with pytest.raises(DomainError) as caught:
        validate_host("8.8.8.8", port)
    assert caught.value.code == "STORAGE_ENDPOINT_PORT_INVALID"


def test_a_public_ftp_host_is_normalised() -> None:
    checked = validate_config("ftp", {"host": "8.8.8.8", "port": "2121"})
    assert (checked["host"], checked["port"]) == ("8.8.8.8", 2121)
    assert validate_host("8.8.8.8", None) == ("8.8.8.8", 21)


def test_carrier_grade_nat_is_not_public() -> None:
    with pytest.raises(DomainError) as caught:
        validate_endpoint_url("http://100.64.0.1:9000")
    assert caught.value.code == "STORAGE_ENDPOINT_NOT_PUBLIC"


def test_the_ftp_adapter_bounds_its_connections() -> None:
    from app.services.storage import ftp

    assert 0 < ftp.CONNECTION_TIMEOUT <= 30
    assert 0 < ftp.SOCKET_TIMEOUT <= 60


# --- N-12: leaving with a dead refresh cookie still leaves ----------------------


async def test_logout_with_a_broken_refresh_cookie_still_clears_it(
    client: Any, make_tenant: Any, make_user: Any
) -> None:
    mm, site = await make_tenant()
    await make_user(mm, site, email="leaving@estampa-demo.com", role="operator")
    token = await _token(client, "leaving@estampa-demo.com")
    client.cookies.set(REFRESH_COOKIE, "not-a-token-any-more", domain="testserver")

    response = await client.post(
        "/api/v1/auth/logout", headers={**_auth(token), "Origin": "http://testserver"}
    )

    assert response.status_code == 200, response.text
    jar = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        jar.load(header)
    assert jar[REFRESH_COOKIE].value == ""


# --- N-13: the production gate refuses the SSRF escape hatch ---------------------


def test_check_env_rejects_private_storage_endpoints() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_env", REPO_ROOT / "scripts" / "check_env.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.check_storage_egress({"ALLOW_PRIVATE_STORAGE_ENDPOINTS": "true"})
    assert not module.check_storage_egress({"ALLOW_PRIVATE_STORAGE_ENDPOINTS": "false"})
    assert not module.check_storage_egress({})
