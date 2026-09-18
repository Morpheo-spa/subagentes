"""The refresh-token cookie.

The SPA is forbidden from keeping a token in browser storage, so the refresh
token never reaches JavaScript at all: it travels in a cookie the browser
attaches on its own and the page cannot read.

That choice trades an XSS exposure for a CSRF one, so the cookie is locked down
on both axes: ``HttpOnly`` keeps script away from it, ``SameSite=strict`` stops
another site from triggering a refresh, ``Path`` keeps it off every request
that does not need it, and :func:`require_same_origin` rejects a cross-origin
caller outright.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request, Response

from app.config import Settings, get_settings
from app.errors import DomainError

REFRESH_COOKIE = "estampa_refresh"


def _cookie_path(settings: Settings) -> str:
    """Scope the cookie to the auth routes, the only ones that consume it."""
    return f"{settings.api_prefix}/auth"


def set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        path=_cookie_path(settings),
        httponly=True,
        # Plain HTTP is only tolerable on a developer's machine.
        secure=settings.environment != "local",
        samesite="strict",
    )


def clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        REFRESH_COOKIE,
        path=_cookie_path(settings),
        httponly=True,
        secure=settings.environment != "local",
        samesite="strict",
    )


def read_refresh_cookie(request: Request) -> str:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise DomainError("NOT_AUTHENTICATED", status_code=401)
    return token


def _origin_of(request: Request) -> str | None:
    """The requesting site, from Origin, falling back to Referer."""
    origin = request.headers.get("Origin")
    if origin:
        return origin
    referer = request.headers.get("Referer")
    if not referer:
        return None
    parts = urlsplit(referer)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def require_same_origin(request: Request) -> None:
    """Refuse a cookie-authenticated call that came from another site.

    A missing Origin is allowed: same-origin GETs and non-browser clients omit
    it, and SameSite already covers the cross-site case. A *mismatched* Origin
    is never allowed, which is the case SameSite cannot be relied on for when a
    browser or proxy downgrades it.
    """
    origin = _origin_of(request)
    if origin is None:
        return
    if origin.rstrip("/") != get_settings().public_base_url.rstrip("/"):
        raise DomainError("CROSS_ORIGIN_REJECTED", status_code=403)
