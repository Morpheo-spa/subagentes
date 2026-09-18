"""The address that ends up in the legal access log must not be client-writable.

``document_accesses.ip_hash`` is what a tenant shows an inspector to prove who
opened a delivery note. Reading the leftmost element of ``X-Forwarded-For`` let
the visitor choose that value (audit E-10), so the hop is now counted from the
right with ``TRUSTED_PROXY_COUNT``, the same way Traefik counts it for the login
rate limit (``ipStrategy.depth``).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import Request

from app.config import get_settings
from app.routers import client_ip, get_client_ip_hash
from app.security import hash_ip

PROXY = "10.0.0.9"  # what request.client.host sees: Traefik itself
REAL_CLIENT = "203.0.113.7"  # the address Traefik appended on the right
SPOOFED = "8.8.8.8"  # whatever the visitor decided to send


@pytest.fixture(autouse=True)
def _clear_settings_cache():  # noqa: ANN202
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def make_request(forwarded_for: str | None, peer: str | None = PROXY) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    scope: dict[str, Any] = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/v/token",
        "raw_path": b"/v/token",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": (peer, 51234) if peer else None,
        "server": ("testserver", 80),
    }
    return Request(scope)


def test_a_forged_prefix_cannot_choose_the_logged_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")

    assert client_ip(make_request(f"{SPOOFED}, {REAL_CLIENT}")) == REAL_CLIENT


def test_several_forged_hops_are_all_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
    chain = f"{SPOOFED}, 198.51.100.1, 192.0.2.44, {REAL_CLIENT}"

    assert client_ip(make_request(chain)) == REAL_CLIENT


def test_a_single_hop_is_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")

    assert client_ip(make_request(REAL_CLIENT)) == REAL_CLIENT


def test_two_trusted_proxies_step_two_hops_from_the_right(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A CDN in front of Traefik: the client is one element further left."""
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "2")
    chain = f"{SPOOFED}, {REAL_CLIENT}, 172.16.0.4"

    assert client_ip(make_request(chain)) == REAL_CLIENT


def test_zero_trusted_proxies_ignores_the_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """No proxy in front: the header is decoration and the socket is the truth."""
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "0")

    assert client_ip(make_request(f"{SPOOFED}, {REAL_CLIENT}")) == PROXY


def test_a_short_chain_is_clamped_instead_of_trusting_the_spoof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fewer hops than configured: take the leftmost present, never a forged one."""
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "3")

    assert client_ip(make_request(REAL_CLIENT)) == REAL_CLIENT


def test_without_the_header_the_peer_address_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")

    assert client_ip(make_request(None)) == PROXY


def test_no_peer_and_no_header_yields_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")

    assert client_ip(make_request(None, peer=None)) is None


def test_blank_entries_do_not_shift_the_hop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")

    assert client_ip(make_request(f"{SPOOFED}, ,  {REAL_CLIENT} ,")) == REAL_CLIENT


def test_the_access_log_hash_is_the_hash_of_the_real_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
    request = make_request(f"{SPOOFED}, {REAL_CLIENT}")

    logged = get_client_ip_hash(request)

    assert logged == hash_ip(REAL_CLIENT)
    assert logged != hash_ip(SPOOFED)
