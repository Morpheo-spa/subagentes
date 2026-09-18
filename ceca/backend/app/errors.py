"""Domain errors and their translation into API payloads.

Services raise :class:`DomainError` with a stable code and interpolation params.
Routers never build error prose: the code is looked up in ``app/i18n/errors.json``
and rendered in the caller's language.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_ERRORS_PATH = Path(__file__).parent / "i18n" / "errors.json"
_FALLBACK_LANGUAGE = "es"


@lru_cache
def _catalog() -> dict[str, dict[str, str]]:
    with _ERRORS_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)["byCode"]


class DomainError(Exception):
    """A business rule was violated.

    ``code`` must exist in ``app/i18n/errors.json``. ``params`` are interpolated
    into the localised message.
    """

    def __init__(self, code: str, *, status_code: int = 400, **params: Any) -> None:
        self.code = code
        self.status_code = status_code
        self.params = params
        super().__init__(code)


class NotFoundError(DomainError):
    def __init__(self, code: str, **params: Any) -> None:
        super().__init__(code, status_code=404, **params)


class PermissionDeniedError(DomainError):
    def __init__(self, code: str = "PERMISSION_DENIED", **params: Any) -> None:
        super().__init__(code, status_code=403, **params)


class QuotaExceededError(DomainError):
    def __init__(self, code: str, **params: Any) -> None:
        super().__init__(code, status_code=402, **params)


class ConflictError(DomainError):
    def __init__(self, code: str, **params: Any) -> None:
        super().__init__(code, status_code=409, **params)


def localised_message(code: str, language: str, params: dict[str, Any]) -> str:
    entry = _catalog().get(code)
    if entry is None:
        return code
    template = entry.get(language) or entry.get(_FALLBACK_LANGUAGE) or code
    try:
        return template.format(**params)
    except (KeyError, IndexError):
        # A missing param must never mask the underlying error.
        return template


def error_detail(exc: DomainError, language: str = _FALLBACK_LANGUAGE) -> dict[str, Any]:
    """The only shape an API error body may take."""
    detail: dict[str, Any] = {
        "code": exc.code,
        "message": localised_message(exc.code, language, exc.params),
    }
    if exc.params:
        detail["params"] = exc.params
    return detail


def known_codes() -> set[str]:
    return set(_catalog())
