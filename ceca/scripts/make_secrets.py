#!/usr/bin/env python3
"""Fill every CHANGE_ME placeholder in a .env with freshly generated secrets.

    python scripts/make_secrets.py            # edits ./.env, creating it from .env.example
    python scripts/make_secrets.py .env.prod  # any other file

Portable on purpose: ``make secrets`` calls this, and on Windows there is no
``make``, so this is the one command that works everywhere. Only ``cryptography``
is optional: without it the Fernet key is still 32 url-safe base64 bytes, which
is exactly what Fernet wants.
"""

from __future__ import annotations

import base64
import os
import re
import secrets
import shutil
import sys
from pathlib import Path


def fernet_key() -> str:
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return base64.urlsafe_b64encode(os.urandom(32)).decode()
    return Fernet.generate_key().decode()


def fill(body: str, key: str, value: str) -> str:
    return re.sub(rf"(?m)^{key}=CHANGE_ME.*$", f"{key}={value}", body)


def fill_secrets(text: str) -> str:
    postgres_password = secrets.token_urlsafe(24)
    redis_password = secrets.token_urlsafe(24)
    text = fill(text, "JWT_SECRET_KEY", secrets.token_urlsafe(48))
    text = fill(text, "STORAGE_SECRET_KEY", fernet_key())
    text = fill(text, "ACCESS_LOG_IP_SALT", secrets.token_urlsafe(24))
    text = fill(text, "POSTGRES_PASSWORD", postgres_password)
    text = fill(text, "REDIS_PASSWORD", redis_password)
    text = fill(text, "MINIO_ROOT_USER", "estampa-" + secrets.token_hex(4))
    text = fill(text, "MINIO_ROOT_PASSWORD", secrets.token_urlsafe(24))
    # The connection URLs carry the same passwords; check_env.py compares them.
    text = re.sub(
        r"(?m)^DATABASE_URL=(postgresql\+asyncpg://[^:@/]+:)CHANGE_ME[^@]*@",
        rf"DATABASE_URL=\g<1>{postgres_password}@",
        text,
    )
    return re.sub(
        r"(?m)^REDIS_URL=(rediss?://[^:@/]*:)CHANGE_ME[^@]*@",
        rf"REDIS_URL=\g<1>{redis_password}@",
        text,
    )


def main(argv: list[str]) -> int:
    target = Path(argv[1] if len(argv) > 1 else ".env")
    if not target.exists():
        template = target.with_name(".env.example")
        if not template.exists():
            print(f"{target} does not exist and there is no {template} to copy", file=sys.stderr)
            return 1
        shutil.copyfile(template, target)
        print(f"{target} created from {template.name}")
    text = target.read_text(encoding="utf-8")
    if not re.search(r"(?m)^[A-Z_]+=.*CHANGE_ME", text):
        print(f"{target}: nothing to fill, no CHANGE_ME placeholder left")
        return 0
    target.write_text(fill_secrets(text), encoding="utf-8")
    print(f"secrets written to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
