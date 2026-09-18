"""The refresh token must never be reachable from JavaScript.

The SPA is forbidden from keeping tokens in browser storage, so the refresh
token rides an HttpOnly cookie instead. That swaps an XSS exposure for a CSRF
one, and these tests pin down both halves of the trade.
"""

from __future__ import annotations

from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

import pytest

from app.config import get_settings
from app.cookies import REFRESH_COOKIE

BACKEND_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.anyio


async def _sign_in(client: Any, email: str) -> Any:
    return await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "test-password"}
    )


def _cookie_attributes(response: Any) -> SimpleCookie:
    jar = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        jar.load(header)
    return jar


@pytest.fixture
async def signed_in(client: Any, make_tenant: Any, make_user: Any) -> Any:
    mm, site = await make_tenant()
    await make_user(mm, site, email="cookie@estampa-demo.com", role="site_admin")
    return await _sign_in(client, "cookie@estampa-demo.com")


async def test_the_refresh_token_never_appears_in_the_response_body(signed_in: Any) -> None:
    assert signed_in.status_code == 200, signed_in.text
    body = signed_in.json()
    assert "refresh_token" not in body["tokens"]
    assert REFRESH_COOKIE not in signed_in.text
    # Belt and braces: the cookie value must not be echoed anywhere in the body.
    cookie_value = _cookie_attributes(signed_in)[REFRESH_COOKIE].value
    assert cookie_value not in signed_in.text


async def test_the_cookie_is_locked_down(signed_in: Any) -> None:
    morsel = _cookie_attributes(signed_in)[REFRESH_COOKIE]
    settings = get_settings()

    assert morsel["httponly"], "script must not be able to read the refresh token"
    assert morsel["samesite"].lower() == "strict", "a cross-site POST must not carry it"
    assert morsel["path"] == f"{settings.api_prefix}/auth", "scope it to the routes that need it"
    if settings.environment != "local":
        assert morsel["secure"], "outside local development it must never cross plain HTTP"


async def test_refresh_without_the_cookie_is_rejected(client: Any, signed_in: Any) -> None:
    client.cookies.clear()
    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "NOT_AUTHENTICATED"


async def test_refresh_from_another_origin_is_rejected(client: Any, signed_in: Any) -> None:
    response = await client.post(
        "/api/v1/auth/refresh", headers={"Origin": "https://albaranes-gratis.example"}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "CROSS_ORIGIN_REJECTED"


async def test_refresh_rotates_so_a_stolen_token_dies_on_first_reuse(
    client: Any, signed_in: Any
) -> None:
    stolen = client.cookies.get(REFRESH_COOKIE)
    assert stolen

    first = await client.post("/api/v1/auth/refresh")
    assert first.status_code == 200, first.text
    assert client.cookies.get(REFRESH_COOKIE) != stolen, "the cookie must be replaced"

    client.cookies.set(REFRESH_COOKIE, stolen)
    replayed = await client.post("/api/v1/auth/refresh")
    assert replayed.status_code == 401, "a rotated token must not work twice"


async def test_logout_clears_the_cookie(client: Any, signed_in: Any) -> None:
    access = signed_in.json()["tokens"]["access_token"]
    response = await client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {access}"}
    )
    assert response.status_code == 200, response.text
    assert not client.cookies.get(REFRESH_COOKIE)


def test_the_demo_seed_uses_addresses_the_api_will_accept() -> None:
    """A seeded demo user who cannot sign in is a demo that does not work.

    Reserved TLDs such as .test read as valid to a human and are rejected by
    the email validator behind LoginRequest, so the seed looked fine and locked
    everyone out.
    """
    import re

    from pydantic import TypeAdapter, ValidationError
    from pydantic.networks import EmailStr

    seed = (BACKEND_ROOT.parent / "scripts" / "seed_demo.py").read_text(encoding="utf-8")
    addresses = set(re.findall(r'"([^"@\s]+@[^"\s]+)"', seed))
    assert addresses, "found no seeded addresses; the pattern above is wrong"

    adapter = TypeAdapter(EmailStr)
    rejected = []
    for address in sorted(addresses):
        try:
            adapter.validate_python(address)
        except ValidationError:
            rejected.append(address)
    assert not rejected, f"the API would reject these seeded logins: {rejected}"
