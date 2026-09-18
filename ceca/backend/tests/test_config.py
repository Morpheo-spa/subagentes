"""Configuration must fail at start-up, never halfway through a customer's checkout."""

from __future__ import annotations

import pytest

from app.config import Settings, get_settings

STRIPE_KEYS = ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET")


@pytest.fixture(autouse=True)
def _clear_settings_cache():  # noqa: ANN202
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _enable_billing(monkeypatch: pytest.MonkeyPatch, **stripe: str) -> None:
    monkeypatch.setenv("BILLING_ENABLED", "true")
    for key in STRIPE_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in stripe.items():
        monkeypatch.setenv(key, value)


def test_billing_without_stripe_keys_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_billing(monkeypatch)

    with pytest.raises(RuntimeError) as excinfo:
        get_settings()

    message = str(excinfo.value)
    assert "STRIPE_SECRET_KEY" in message
    assert "STRIPE_WEBHOOK_SECRET" in message


def test_billing_with_only_one_stripe_key_still_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_billing(monkeypatch, STRIPE_SECRET_KEY="sk_test_not_a_real_key")

    with pytest.raises(RuntimeError) as excinfo:
        get_settings()

    assert "STRIPE_WEBHOOK_SECRET" in str(excinfo.value)


def test_billing_with_both_stripe_keys_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_billing(
        monkeypatch,
        STRIPE_SECRET_KEY="sk_test_not_a_real_key",
        STRIPE_WEBHOOK_SECRET="whsec_not_a_real_secret",
    )

    settings = get_settings()

    assert settings.billing_enabled is True


def test_billing_disabled_needs_no_stripe_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILLING_ENABLED", "false")
    for key in STRIPE_KEYS:
        monkeypatch.delenv(key, raising=False)

    settings = get_settings()

    assert settings.billing_enabled is False


def test_public_base_url_loses_its_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    """QR URLs are built by concatenation; a double slash would break the scan."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://albaranes.example.com/")

    assert get_settings().public_base_url == "https://albaranes.example.com"


def test_a_short_jwt_secret_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", "too-short")

    with pytest.raises(ValueError):
        Settings()  # type: ignore[call-arg]


def test_retention_default_is_the_legal_minimum() -> None:
    assert get_settings().default_retention_days >= 365
