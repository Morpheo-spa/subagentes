"""A tenant configures its own storage, so those values are attacker input.

The dangerous one is ``endpoint_url``: handed to an S3 client it will connect
wherever it is told. Aimed at a cloud metadata service it turns into credential
theft, and aimed at an internal host it turns into a port scanner that already
sits inside the network.
"""

from __future__ import annotations

import pytest

from app.errors import DomainError
from app.services.storage.validation import (
    validate_base_path,
    validate_endpoint_url,
)

#: Literal addresses, so the test never depends on DNS being available.
INTERNAL_ENDPOINTS = [
    pytest.param("http://169.254.169.254/latest/meta-data/", id="aws-metadata"),
    pytest.param("http://169.254.169.254:80/", id="aws-metadata-explicit-port"),
    pytest.param("http://127.0.0.1:9000", id="loopback"),
    pytest.param("http://10.0.0.5:9000", id="private-10"),
    pytest.param("http://192.168.1.10:9000", id="private-192"),
    pytest.param("http://172.16.0.9:9000", id="private-172"),
    pytest.param("http://[::1]:9000", id="loopback-v6"),
    pytest.param("http://0.0.0.0:9000", id="unspecified"),
]


@pytest.mark.parametrize("url", INTERNAL_ENDPOINTS)
def test_an_internal_endpoint_is_refused(url: str) -> None:
    with pytest.raises(DomainError) as caught:
        validate_endpoint_url(url)
    assert caught.value.code == "STORAGE_ENDPOINT_NOT_PUBLIC"


def test_a_public_endpoint_is_accepted() -> None:
    assert validate_endpoint_url("https://8.8.8.8") == "https://8.8.8.8"


def test_a_non_http_scheme_is_refused() -> None:
    with pytest.raises(DomainError) as caught:
        validate_endpoint_url("file:///etc/passwd")
    assert caught.value.code == "STORAGE_ENDPOINT_SCHEME_INVALID"


def test_an_unexpected_port_is_refused() -> None:
    """Storage does not live on 22 or 6379; letting those through is a port scanner."""
    with pytest.raises(DomainError) as caught:
        validate_endpoint_url("http://8.8.8.8:22")
    assert caught.value.code == "STORAGE_ENDPOINT_PORT_INVALID"


def test_no_endpoint_is_fine() -> None:
    assert validate_endpoint_url(None) is None
    assert validate_endpoint_url("") is None


def test_private_endpoints_are_allowed_only_when_the_deployment_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Garage of the same stack must stay usable without opening the door in production."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_PRIVATE_STORAGE_ENDPOINTS", "true")
    try:
        assert validate_endpoint_url("http://10.0.0.5:3900") == "http://10.0.0.5:3900"
    finally:
        get_settings.cache_clear()


def test_base_path_cannot_escape_the_storage_root(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path))
    try:
        with pytest.raises(DomainError) as caught:
            validate_base_path("/etc")
        assert caught.value.code == "STORAGE_BASE_PATH_OUTSIDE_ROOT"

        with pytest.raises(DomainError):
            validate_base_path("../../etc")
    finally:
        get_settings.cache_clear()


def test_base_path_inside_the_root_is_accepted_and_resolved(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path))
    try:
        assert validate_base_path("site-a") == str(tmp_path / "site-a")
        assert validate_base_path(None) == str(tmp_path)
    finally:
        get_settings.cache_clear()


def test_s3_refuses_to_fall_back_to_the_host_credentials() -> None:
    """Omitting the keys once made botocore sign with the instance role."""
    from app.services.storage.s3 import _session

    with pytest.raises(DomainError) as caught:
        _session({})
    assert caught.value.code == "STORAGE_CREDENTIALS_REQUIRED"

    with pytest.raises(DomainError):
        _session({"access_key_id": "AKIAEXAMPLE"})
