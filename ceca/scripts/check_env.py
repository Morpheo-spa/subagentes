#!/usr/bin/env python3
"""Validate a production .env file before deploying.

Standard library only: this runs on a deploy host that may have nothing installed.

    python scripts/check_env.py .env.production

Exit code 0 when the file is deployable, 1 when it is not.
"""

from __future__ import annotations

import base64
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRAEFIK_CONFIG = "./infra/traefik/traefik.yml"

REQUIRED_KEYS = (
    "ENVIRONMENT",
    "DEBUG",
    "PUBLIC_BASE_URL",
    "TRUSTED_PROXY_COUNT",
    "DATABASE_URL",
    "REDIS_URL",
    "JWT_SECRET_KEY",
    "STORAGE_SECRET_KEY",
    "ACCESS_LOG_IP_SALT",
    "MAX_UPLOAD_MB",
    "BILLING_ENABLED",
    "DEFAULT_RETENTION_DAYS",
    # Infrastructure credentials: the compose services have no defaults left.
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "GARAGE_RPC_SECRET",
    "GARAGE_ADMIN_TOKEN",
    "GARAGE_ACCESS_KEY",
    "GARAGE_SECRET_KEY",
)

MINIMUM_LENGTHS = {
    "JWT_SECRET_KEY": 32,
    "STORAGE_SECRET_KEY": 32,
    "ACCESS_LOG_IP_SALT": 16,
    "POSTGRES_PASSWORD": 16,
    "REDIS_PASSWORD": 16,
    "GARAGE_ADMIN_TOKEN": 16,
    "GARAGE_SECRET_KEY": 32,
}

SECRET_KEYS = (
    "JWT_SECRET_KEY",
    "STORAGE_SECRET_KEY",
    "ACCESS_LOG_IP_SALT",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "GARAGE_RPC_SECRET",
    "GARAGE_ADMIN_TOKEN",
    "GARAGE_SECRET_KEY",
)

PLACEHOLDER_PATTERN = re.compile(
    r"change_?me|changeme|example|placeholder|xxxx|todo|secret_here|your[-_]",
    re.IGNORECASE,
)

WEAK_VALUES = {"estampa", "postgres", "password", "admin", "test", "dev", "secret", "changeme"}

# Shipped-by-default identities. An object store still answering to any of
# these is an open object store (audit E-06).
DEFAULT_IDENTITIES = {"estampa", "minio", "minioadmin", "admin", "root", "access_key"}
HEX_64 = re.compile(r"^[0-9a-fA-F]{64}$")
GARAGE_KEY_ID = re.compile(r"^GK[0-9a-fA-F]{24}$")

# Values this repository has shipped as defaults at some point. Any of them
# still in place means the credential was never chosen.
SHIPPED_DEFAULTS = {"estampa", "estampa-dev-secret", "minioadmin", "estampa-secret"}

TRUE_VALUES = {"1", "true", "yes", "on"}


def parse_env(path: Path) -> dict[str, str]:
    """Read KEY=VALUE lines, ignoring comments, exports and surrounding quotes."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        values[key.strip()] = strip_inline_comment(value.strip())
    return values


def strip_inline_comment(value: str) -> str:
    if value[:1] in {'"', "'"} and value[-1:] == value[:1] and len(value) > 1:
        return value[1:-1]
    return value.split(" #")[0].strip()


def is_true(value: str) -> bool:
    return value.strip().lower() in TRUE_VALUES


def is_valid_fernet_key(value: str) -> bool:
    """A Fernet key is 32 raw bytes in url-safe base64, no dependency needed."""
    try:
        return len(base64.urlsafe_b64decode(value.encode())) == 32
    except (ValueError, TypeError):
        return False


def check_required(env: dict[str, str]) -> list[str]:
    return [f"{key}: missing or empty" for key in REQUIRED_KEYS if not env.get(key, "").strip()]


def check_secrets(env: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for key in SECRET_KEYS:
        value = env.get(key, "")
        if not value:
            continue
        if PLACEHOLDER_PATTERN.search(value):
            problems.append(f"{key}: still holds a placeholder value")
        elif value.lower() in WEAK_VALUES:
            problems.append(f"{key}: trivially guessable value")
        elif value.lower() in SHIPPED_DEFAULTS:
            problems.append(f"{key}: still the value this repository ships as a default")
    for key, minimum in MINIMUM_LENGTHS.items():
        value = env.get(key, "")
        if value and len(value) < minimum:
            problems.append(f"{key}: shorter than {minimum} characters")
    return problems


def check_production_flags(env: dict[str, str]) -> list[str]:
    problems: list[str] = []
    environment = env.get("ENVIRONMENT", "").strip().lower()
    if environment != "production":
        problems.append(f"ENVIRONMENT: expected 'production', found '{environment or 'unset'}'")
    if is_true(env.get("DEBUG", "")):
        problems.append(
            "DEBUG: must be false in production - it makes SQLAlchemy log every "
            "statement with its bound parameters, password hashes and viewer "
            "tokens included (the API also refuses to start this way)"
        )
    base_url = env.get("PUBLIC_BASE_URL", "")
    if base_url and not base_url.startswith("https://"):
        problems.append("PUBLIC_BASE_URL: must be https in production")
    if base_url.endswith("/"):
        problems.append("PUBLIC_BASE_URL: must not end with a slash")
    problems.extend(check_trusted_proxies(env))
    problems.extend(check_storage_egress(env))
    return problems


def check_storage_egress(env: dict[str, str]) -> list[str]:
    """The SSRF guard on tenant storage endpoints returns early when this is on."""
    if is_true(env.get("ALLOW_PRIVATE_STORAGE_ENDPOINTS", "")):
        return [
            "ALLOW_PRIVATE_STORAGE_ENDPOINTS: must be false in production - with it "
            "on, any tenant can point a storage backend at the internal network"
        ]
    return []


def check_trusted_proxies(env: dict[str, str]) -> list[str]:
    """The hop count the API uses to read X-Forwarded-For from the right."""
    raw = env.get("TRUSTED_PROXY_COUNT", "").strip()
    if not raw:
        return []
    if not raw.isdigit():
        return ["TRUSTED_PROXY_COUNT: must be a whole number of proxy hops"]
    if int(raw) < 1:
        return [
            "TRUSTED_PROXY_COUNT: must be at least 1 behind Traefik, or every "
            "access is logged with the proxy's own address"
        ]
    return []


def url_password(url: str) -> str | None:
    """The password inside a URL, or None when it carries none."""
    try:
        return urlsplit(url).password
    except ValueError:
        return None


def url_host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def check_redis(env: dict[str, str]) -> list[str]:
    """Redis holds the JWT blacklist and the Dramatiq broker: never unauthenticated.

    Whoever reaches an open Redis can delete blacklist entries to revive revoked
    tokens and enqueue withdraw_document with any mm_id/site_id, which the task
    runner accepts as a superuser context (audit E-06).
    """
    problems: list[str] = []
    password = env.get("REDIS_PASSWORD", "").strip()
    url = env.get("REDIS_URL", "").strip()
    if url:
        in_url = url_password(url)
        if not in_url:
            problems.append(
                "REDIS_URL: carries no password - use redis://:<REDIS_PASSWORD>@host:6379/0"
            )
        elif password and in_url != password:
            problems.append("REDIS_URL: password does not match REDIS_PASSWORD")
        if url.startswith("redis://") and url_host(url) not in {"redis", "localhost", "127.0.0.1"}:
            problems.append(
                "REDIS_URL: use rediss:// for a Redis outside the compose network"
            )
    return problems


def check_postgres(env: dict[str, str]) -> list[str]:
    problems: list[str] = []
    password = env.get("POSTGRES_PASSWORD", "").strip()
    url = env.get("DATABASE_URL", "").strip()
    if url and url_host(url) == "postgres":
        in_url = url_password(url)
        if not in_url:
            problems.append("DATABASE_URL: carries no password")
        elif password and in_url != password:
            problems.append("DATABASE_URL: password does not match POSTGRES_PASSWORD")
    return problems


def check_object_store(env: dict[str, str]) -> list[str]:
    """Garage's secrets have a shape; a wrong shape means it will not start."""
    problems: list[str] = []
    rpc = env.get("GARAGE_RPC_SECRET", "").strip()
    if rpc and not HEX_64.match(rpc):
        problems.append("GARAGE_RPC_SECRET: must be exactly 64 hexadecimal characters")
    key_id = env.get("GARAGE_ACCESS_KEY", "").strip()
    if key_id and key_id.lower() in DEFAULT_IDENTITIES:
        problems.append(f"GARAGE_ACCESS_KEY: default identity '{key_id}', pick an unguessable one")
    if key_id and PLACEHOLDER_PATTERN.search(key_id):
        problems.append("GARAGE_ACCESS_KEY: still holds a placeholder value")
    elif key_id and not GARAGE_KEY_ID.match(key_id):
        problems.append("GARAGE_ACCESS_KEY: must be 'GK' followed by 24 hexadecimal characters")
    secret = env.get("GARAGE_SECRET_KEY", "").strip()
    if secret and not PLACEHOLDER_PATTERN.search(secret) and not HEX_64.match(secret):
        problems.append("GARAGE_SECRET_KEY: must be exactly 64 hexadecimal characters")
    return problems


def check_storage_key(env: dict[str, str]) -> list[str]:
    value = env.get("STORAGE_SECRET_KEY", "")
    if value and not is_valid_fernet_key(value):
        return [
            "STORAGE_SECRET_KEY: not a valid Fernet key "
            '(python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())")'
        ]
    return []


def check_billing(env: dict[str, str]) -> list[str]:
    if not is_true(env.get("BILLING_ENABLED", "")):
        return []
    return [
        f"{key}: required when BILLING_ENABLED=true"
        for key in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET")
        if not env.get(key, "").strip()
    ]


def check_retention(env: dict[str, str]) -> list[str]:
    raw = env.get("DEFAULT_RETENTION_DAYS", "").strip()
    if not raw:
        return []
    if not raw.isdigit():
        return ["DEFAULT_RETENTION_DAYS: must be a whole number of days"]
    if int(raw) < 365:
        return ["DEFAULT_RETENTION_DAYS: below the 365-day legal minimum"]
    return []


def traefik_config_path(env: dict[str, str], base_dir: Path) -> Path:
    """Where the Traefik static configuration lives, as compose would mount it."""
    raw = env.get("TRAEFIK_STATIC_CONFIG", "").strip() or DEFAULT_TRAEFIK_CONFIG
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate
    for root in (base_dir, REPO_ROOT):
        resolved = root / candidate
        if resolved.is_file():
            return resolved
    return base_dir / candidate


def check_tls(env: dict[str, str], base_dir: Path) -> list[str]:
    """TLS is part of the environment: read the static config this .env mounts.

    Access tokens, the refresh cookie and every PDF travel over this proxy, and
    the dashboard behind it maps the whole deployment (audit E-06).
    """
    path = traefik_config_path(env, base_dir)
    if not path.is_file():
        return [f"TRAEFIK_STATIC_CONFIG: {path} does not exist"]

    text = path.read_text(encoding="utf-8")
    active = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    problems: list[str] = []
    if re.search(r"(?m)^\s*insecure:\s*true", active):
        problems.append(f"{path.name}: the Traefik API is exposed without authentication")
    if not re.search(r"(?m)^\s*to:\s*websecure", active):
        problems.append(f"{path.name}: no HTTP-to-HTTPS redirection, traffic would travel in clear")
    if not re.search(r"(?m)^\s*certResolver:|^\s*certificatesResolvers:", active):
        problems.append(f"{path.name}: no certificate resolver, TLS cannot be served")
    if re.search(r"(?m)^\s*email:.*@example\.(com|org|net)\s*$", active):
        problems.append(f"{path.name}: the ACME contact is still the example address")
    return problems


CHECKS = (
    check_required,
    check_production_flags,
    check_secrets,
    check_storage_key,
    check_billing,
    check_retention,
    check_redis,
    check_postgres,
    check_object_store,
)


def validate(env: dict[str, str], base_dir: Path) -> list[str]:
    problems: list[str] = []
    for check in CHECKS:
        problems.extend(check(env))
    problems.extend(check_tls(env, base_dir))
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_env.py <env-file>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"FAIL  {path} does not exist", file=sys.stderr)
        return 1

    problems = validate(parse_env(path), path.resolve().parent)
    if problems:
        print(f"FAIL  {path}: {len(problems)} problem(s)", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"OK    {path} is deployable")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
