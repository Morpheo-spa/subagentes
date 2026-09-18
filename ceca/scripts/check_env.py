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
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
)

MINIMUM_LENGTHS = {
    "JWT_SECRET_KEY": 32,
    "STORAGE_SECRET_KEY": 32,
    "ACCESS_LOG_IP_SALT": 16,
    "POSTGRES_PASSWORD": 16,
    "REDIS_PASSWORD": 16,
    "MINIO_ROOT_PASSWORD": 16,
}

SECRET_KEYS = (
    "JWT_SECRET_KEY",
    "STORAGE_SECRET_KEY",
    "ACCESS_LOG_IP_SALT",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "MINIO_ROOT_PASSWORD",
)

PLACEHOLDER_PATTERN = re.compile(
    r"change_?me|changeme|example|placeholder|xxxx|todo|secret_here|your[-_]",
    re.IGNORECASE,
)

WEAK_VALUES = {"estampa", "postgres", "password", "admin", "test", "dev", "secret", "changeme"}

# Shipped-by-default identities. A MinIO instance still answering to any of
# these is an open object store (audit E-06).
DEFAULT_IDENTITIES = {"estampa", "minio", "minioadmin", "admin", "root", "access_key"}

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
        problems.append("DEBUG: must be false in production")
    base_url = env.get("PUBLIC_BASE_URL", "")
    if base_url and not base_url.startswith("https://"):
        problems.append("PUBLIC_BASE_URL: must be https in production")
    if base_url.endswith("/"):
        problems.append("PUBLIC_BASE_URL: must not end with a slash")
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


CHECKS = (
    check_required,
    check_production_flags,
    check_secrets,
    check_storage_key,
    check_billing,
    check_retention,
)


def validate(env: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for check in CHECKS:
        problems.extend(check(env))
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_env.py <env-file>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"FAIL  {path} does not exist", file=sys.stderr)
        return 1

    problems = validate(parse_env(path))
    if problems:
        print(f"FAIL  {path}: {len(problems)} problem(s)", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"OK    {path} is deployable")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
