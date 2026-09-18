"""Validation of tenant-supplied storage settings.

A storage backend is configured by the customer, so its values are attacker
controlled. Two of them reach out of the process and need checking before they
are ever used:

``endpoint_url``
    Handed to an S3 client, which will happily connect anywhere. Pointed at a
    cloud metadata service it becomes credential theft; pointed at an internal
    host it becomes a port scanner with our network position.

``base_path``
    The directory the local adapter writes into. Unconstrained, a tenant can
    write anywhere the process can, and can also park delivery notes outside the
    persistent volume, where a restart deletes them with no error at all.
"""

from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlsplit

from app.config import get_settings
from app.errors import DomainError

ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_PORTS = frozenset({80, 443, 9000, 9001, 8333})


def _is_forbidden(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Everything that is not a plain, routable public address."""
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local  # 169.254.0.0/16 holds the cloud metadata service
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _resolved_addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise DomainError("STORAGE_ENDPOINT_UNRESOLVABLE", host=host) from exc
    return [ipaddress.ip_address(info[4][0]) for info in infos]


def validate_endpoint_url(url: str | None) -> str | None:
    """Refuse an endpoint that points anywhere but the public internet.

    Every address the host resolves to is checked, not just the first: a name
    that answers with one public and one private address must not pass.

    Private addresses are allowed only when the deployment says so, which is how
    a local MinIO or a self-hosted Garage on the same network stays usable.
    """
    if not url:
        return None

    settings = get_settings()
    parts = urlsplit(url)

    if parts.scheme not in ALLOWED_SCHEMES:
        raise DomainError("STORAGE_ENDPOINT_SCHEME_INVALID", scheme=parts.scheme or "")
    if not parts.hostname:
        raise DomainError("STORAGE_ENDPOINT_INVALID", url=url)
    if parts.port is not None and parts.port not in ALLOWED_PORTS:
        raise DomainError("STORAGE_ENDPOINT_PORT_INVALID", port=parts.port)

    if settings.allow_private_storage_endpoints:
        return url

    try:
        literal = ipaddress.ip_address(parts.hostname)
    except ValueError:
        addresses = _resolved_addresses(parts.hostname)
    else:
        addresses = [literal]

    for address in addresses:
        if _is_forbidden(address):
            raise DomainError("STORAGE_ENDPOINT_NOT_PUBLIC", host=parts.hostname)
    return url


def validate_base_path(base_path: str | None) -> str:
    """Confine the local adapter to the directory the deployment set aside.

    Returns the resolved path as a string so the caller stores what it will
    actually use, rather than the text a tenant typed.
    """
    settings = get_settings()
    root = Path(settings.local_storage_root).resolve()

    if not base_path:
        return str(root)

    candidate = (
        (root / base_path).resolve()
        if not Path(base_path).is_absolute()
        else Path(base_path).resolve()
    )

    if candidate != root and root not in candidate.parents:
        raise DomainError("STORAGE_BASE_PATH_OUTSIDE_ROOT", base_path=base_path)
    return str(candidate)


def validate_config(kind: str, config: dict[str, object]) -> dict[str, object]:
    """Normalise and check the non-secret half of a backend's settings."""
    checked = dict(config)
    if kind == "s3":
        endpoint = checked.get("endpoint_url")
        checked["endpoint_url"] = validate_endpoint_url(
            endpoint if isinstance(endpoint, str) else None
        )
    if kind == "local":
        raw = checked.get("base_path")
        checked["base_path"] = validate_base_path(raw if isinstance(raw, str) else None)
    return checked
