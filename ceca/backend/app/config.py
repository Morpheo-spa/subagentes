"""Application settings. The single source of truth for environment configuration."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read once from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    environment: Literal["local", "staging", "production"] = "local"
    debug: bool = False

    # --- Identity -----------------------------------------------------------
    app_name: str = "Estampa"
    public_base_url: str = "http://localhost"
    api_prefix: str = "/api/v1"

    # --- Persistence --------------------------------------------------------
    database_url: PostgresDsn
    redis_url: RedisDsn

    # --- Security -----------------------------------------------------------
    jwt_secret_key: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 14
    storage_secret_key: str = Field(
        min_length=32,
        description="Fernet key used to encrypt storage backend credentials at rest.",
    )
    access_log_ip_salt: str = Field(
        min_length=16,
        description="Salt for hashing visitor IPs in the public access log.",
    )

    # --- Uploads ------------------------------------------------------------
    # The Resolution of 5 June 2026 caps a DeCA file at 5 MB. See docs/DECA.md.
    max_upload_mb: int = 5
    max_files_per_upload: int = 100

    # --- Billing ------------------------------------------------------------
    billing_enabled: bool = False
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_lookup_prefix: str = "estampa_"

    # --- Retention ----------------------------------------------------------
    # 365 days is the legal minimum for keeping DeCA files. Tenants may raise it,
    # and the UI warns when a site is left sitting on the bare minimum.
    default_retention_days: int = 365
    retention_sweep_hour_utc: int = 2

    @field_validator("public_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def require_billing_config(self) -> None:
        """Fail loudly when billing is switched on without its credentials."""
        if not self.billing_enabled:
            return
        missing = [
            name
            for name, value in (
                ("STRIPE_SECRET_KEY", self.stripe_secret_key),
                ("STRIPE_WEBHOOK_SECRET", self.stripe_webhook_secret),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "BILLING_ENABLED=true requires: " + ", ".join(missing)
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()  # type: ignore[call-arg]
    settings.require_billing_config()
    return settings
