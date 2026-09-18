"""Password hashing, JWT issuing and public share tokens."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings
from app.errors import DomainError

_hasher = PasswordHasher()
TokenType = Literal["access", "refresh"]

#: Named so the token kind never reads as a credential, to humans or to scanners.
ACCESS: Final[TokenType] = "access"
REFRESH: Final[TokenType] = "refresh"


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, raw)
    except (VerifyMismatchError, ValueError):
        return False


def needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)


def create_token(
    *,
    user_id: uuid.UUID,
    mm_id: uuid.UUID,
    site_id: uuid.UUID | None,
    site_prefix: str | None,
    permissions: set[str],
    is_superuser: bool,
    locale: str,
    token_type: TokenType = ACCESS,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    lifetime = (
        timedelta(minutes=settings.access_token_minutes)
        if token_type == ACCESS
        else timedelta(days=settings.refresh_token_days)
    )
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "mm_id": str(mm_id),
        "tenant_id": str(site_id) if site_id else None,
        "site_prefix": site_prefix,
        "permissions": sorted(permissions),
        "is_superuser": is_superuser,
        "locale": locale,
        "type": token_type,
        "jti": secrets.token_urlsafe(16),
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(  # noqa: S107 (a token kind, not a secret)
    token: str, *, expected_type: TokenType = ACCESS
) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise DomainError("TOKEN_EXPIRED", status_code=401) from exc
    except jwt.InvalidTokenError as exc:
        raise DomainError("TOKEN_INVALID", status_code=401) from exc
    if payload.get("type") != expected_type:
        raise DomainError("TOKEN_INVALID", status_code=401)
    return payload


def new_share_token() -> str:
    """The secret published in a QR code. Unguessable and unrelated to the GUID."""
    return secrets.token_urlsafe(24)


def hash_ip(ip: str | None) -> str | None:
    """One-way hash of a visitor IP, so the access log is auditable but not personal."""
    if not ip:
        return None
    salt = get_settings().access_log_ip_salt.encode()
    return hmac.new(salt, ip.encode(), hashlib.sha256).hexdigest()


def _fernet() -> Fernet:
    return Fernet(get_settings().storage_secret_key.encode())


def encrypt_secret(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt_secret(ciphertext: bytes) -> str:
    try:
        return _fernet().decrypt(ciphertext).decode()
    except InvalidToken as exc:
        raise DomainError("STORAGE_SECRET_UNREADABLE", status_code=500) from exc
