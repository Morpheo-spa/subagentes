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

from app import main as app_main
from app.cookies import REFRESH_COOKIE
from app.errors import DomainError
from app.models.tenancy import User, UserSite
from app.routers import documents as documents_router
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


# --- N-07: a file part is cut off at the limit, not spooled and then refused ----


class _Channel:
    """An ASGI receive channel that serves the body in chunks and counts them."""

    def __init__(self, data: bytes, chunk: int) -> None:
        self._chunks = [data[i : i + chunk] for i in range(0, len(data), chunk)]
        self.served = 0

    async def __call__(self) -> dict[str, Any]:
        if not self._chunks:
            return {"type": "http.disconnect"}
        body = self._chunks.pop(0)
        self.served += len(body)
        return {"type": "http.request", "body": body, "more_body": bool(self._chunks)}


def _multipart_file(filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = "estampa-boundary"
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return body, f"multipart/form-data; boundary={boundary}"


async def test_a_file_part_over_the_limit_stops_the_stream_at_the_limit() -> None:
    """Before: a 500 MB part hit the disk in full, and was refused afterwards."""
    from starlette.requests import Request

    from app.config import get_settings

    body, content_type = _multipart_file("enorme.pdf", b"x" * (6 * 1024 * 1024))
    channel = _Channel(body, chunk=64 * 1024)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/documents/",
            "headers": [(b"content-type", content_type.encode())],
        },
        channel,
    )
    # Ten files of 1 MB are allowed, so the body cap (11 MB) is not what trips.
    limits = get_settings().model_copy(update={"max_files_per_upload": 10, "max_upload_mb": 1})

    with pytest.raises(DomainError) as raised:
        await documents_router._parse_upload(request, limits)

    assert raised.value.code == "UPLOAD_FILE_TOO_LARGE"
    assert raised.value.params == {"filename": "enorme.pdf", "max_mb": 1}
    assert channel.served < 2 * 1024 * 1024, f"{channel.served} bytes were read past the limit"


async def test_a_file_at_the_limit_still_parses() -> None:
    from starlette.requests import Request

    from app.config import get_settings

    body, content_type = _multipart_file("justo.pdf", b"%PDF-1.4" + b"x" * (1024 * 1024 - 8))
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/documents/",
            "headers": [(b"content-type", content_type.encode())],
        },
        _Channel(body, chunk=64 * 1024),
    )
    limits = get_settings().model_copy(update={"max_files_per_upload": 10, "max_upload_mb": 1})

    form = await documents_router._parse_upload(request, limits)
    try:
        (upload,) = form.getlist("files")
        assert upload.filename == "justo.pdf"  # type: ignore[union-attr]
    finally:
        await form.close()


# --- N-08: no DNS on the event loop -----------------------------------------------


def test_the_adapters_check_a_name_without_resolving_it(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def no_dns(*_: Any, **__: Any) -> Any:
        raise AssertionError("getaddrinfo must not run on the request path")

    monkeypatch.setattr(socket, "getaddrinfo", no_dns)
    assert validate_endpoint_url("https://bucket.example.net:9000", resolve=False)
    assert validate_host("ftp.example.net", 21, resolve=False) == ("ftp.example.net", 21)
    # A literal address needs no lookup and is still refused.
    with pytest.raises(DomainError):
        validate_endpoint_url("http://10.0.0.5:9000", resolve=False)


async def test_saving_a_backend_resolves_in_a_worker_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket
    import threading

    from app.services.storage.validation import validate_config_offloaded

    seen: list[str] = []

    def record(host: str, *_: Any, **__: Any) -> list[Any]:
        seen.append(threading.current_thread().name)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", record)
    checked = await validate_config_offloaded("s3", {"endpoint_url": "https://s3.example.net"})

    assert checked["endpoint_url"] == "https://s3.example.net"
    assert seen and seen[0] != threading.main_thread().name


def test_the_storage_router_never_calls_the_blocking_validator() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "routers" / "storage.py").read_text()
    assert "validate_config_offloaded(" in source
    assert " validate_config(" not in source


# --- N-11: X-Request-ID is ours to bound -----------------------------------------


@pytest.mark.parametrize(
    "offered",
    [
        pytest.param("x" * 65, id="too-long"),
        pytest.param("id with spaces", id="spaces"),
        pytest.param("id\tline", id="control"),
        pytest.param("ünïcode", id="non-ascii"),
        pytest.param("", id="empty"),
    ],
)
def test_an_unacceptable_request_id_is_replaced(offered: str) -> None:
    accepted = app_main._accepted_request_id(offered)
    assert accepted != offered
    assert len(accepted) == 32


def test_a_reasonable_request_id_is_kept() -> None:
    assert app_main._accepted_request_id("req-2026.09.19_abc") == "req-2026.09.19_abc"


async def test_the_response_echoes_only_a_bounded_request_id(client: Any) -> None:
    response = await client.get("/health/live", headers={"X-Request-ID": "y" * 4096})
    assert response.status_code == 200
    assert len(response.headers["X-Request-ID"]) == 32
