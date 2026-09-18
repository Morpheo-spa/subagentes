"""Production logging: one JSON object per line, a request id on every event,
and no secret in any of them.

Three pieces, each usable on its own:

- :func:`configure_logging` installs a single root handler. Outside ``local``
  the formatter is JSON, one line per event, with the fixed keys ``timestamp``,
  ``level``, ``logger``, ``message`` and ``request_id``; in ``local`` it is
  readable text. Whatever uvicorn or dramatiq configured before is replaced, so
  every process of the stack logs the same way.
- :class:`RedactionFilter` and :func:`redact_text` make sure a token, a password,
  a cookie or an ``Authorization`` header never reaches the output, whether it
  was passed in ``extra`` or written into the message. The filter redacts by
  key; the formatter redacts the final line by pattern. Both run, so a handler
  that gets one without the other is still covered.
- :class:`AccessLogMiddleware` writes one line per request with method, route
  template, status, duration and request id. The route is the *template*: the
  public viewer is logged as ``/v/{token}``, never with the token, and the
  query string is never written.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, TextIO

from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Set by ``RequestIdMiddleware`` for the duration of a request, so a log line
#: written deep inside a service carries the id without anyone passing it.
request_id_var: ContextVar[str | None] = ContextVar("estampa_request_id", default=None)

REDACTED = "[REDACTED]"

#: Keys whose value is never written, wherever they appear inside ``extra``.
#: Compared after lower-casing and turning ``-`` into ``_``.
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "authorization",
        "proxy_authorization",
        "cookie",
        "set_cookie",
        "x_api_key",
        "stripe_signature",
        "password",
        "passwd",
        "hashed_password",
        "new_password",
        "current_password",
        "token",
        "access_token",
        "refresh_token",
        "share_token",
        "session_token",
        "secret",
        "client_secret",
        "secret_key",
        "secret_access_key",
        "api_key",
        "credentials",
        "private_key",
    }
)
#: Any key containing one of these is treated as sensitive too. Over-matching
#: costs a counter in a log line; under-matching costs a credential.
SENSITIVE_MARKERS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "cookie",
    "authorization",
    "api_key",
    "credential",
    "private_key",
)

#: ``key=value`` / ``key: value`` / ``"key": "value"``: the value goes, the
#: quoting stays, so a JSON line stays a JSON line after redaction.
_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|secret|token|access_token|refresh_token|"
    r"api_key|apikey|client_secret|authorization)\b"
    r"((?:\\?[\"'])?\s*[=:]\s*)"
    # A value quoted with escaped quotes (a JSON string inside a JSON string)
    # ends at the next escaped quote; a plainly quoted one at the next quote.
    r"(\\\"(?:[^\"\\]|\\[^\"])*\\\"|\"(?:[^\"\\]|\\.)*\"|'[^']*'|[^\s,;&\"'}\]\\]+)"
)


def _redact_assignment(match: re.Match[str]) -> str:
    value = match.group(3)
    if value.startswith('\\"'):
        quote = '\\"'  # a JSON string inside a JSON string stays one
    elif value[:1] in ('"', "'"):
        quote = value[0]
    else:
        quote = ""
    return f"{match.group(1)}{match.group(2)}{quote}{REDACTED}{quote}"


_PATTERNS: tuple[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]], ...] = (
    # HTTP credentials in free text: "Authorization: Bearer eyJ..." / "Basic dXNl..."
    (re.compile(r"(?i)\b(bearer|basic|digest)\s+[A-Za-z0-9\-._~+/=]{4,}"), rf"\1 {REDACTED}"),
    # A whole cookie header, stopping before anything that would break a JSON line.
    (re.compile(r"(?i)\b(cookie|set-cookie)\s*[:=]\s*[^\r\n\"\\]+"), rf"\1: {REDACTED}"),
    (_ASSIGNMENT, _redact_assignment),
    # JWTs, wherever they appear.
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"), REDACTED),
    # Stripe keys and webhook secrets.
    (re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{8,}\b"), REDACTED),
    (re.compile(r"\bwhsec_[A-Za-z0-9]{8,}\b"), REDACTED),
    # The public viewer token, should a raw path ever be logged.
    (re.compile(r"(/v/)[A-Za-z0-9_-]{16,}"), r"\1{token}"),
)

_STANDARD_ATTRS: frozenset[str] = frozenset(
    logging.LogRecord("", logging.INFO, "", 0, "", (), None).__dict__
) | frozenset({"message", "asctime", "taskName"})


# --- Redaction ---------------------------------------------------------------


def is_sensitive_key(key: object) -> bool:
    name = str(key).lower().replace("-", "_")
    return name in SENSITIVE_KEYS or any(marker in name for marker in SENSITIVE_MARKERS)


def redact_text(text: str) -> str:
    """Scrub credentials written into free text."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_value(value: Any, key: object = None) -> Any:
    """Scrub a structured value recursively. Sensitive keys lose their value whole."""
    if key is not None and is_sensitive_key(key):
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {str(k): redact_value(v, k) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [redact_value(item) for item in value]
    if isinstance(value, bytes):
        return REDACTED
    return value


class RedactionFilter(logging.Filter):
    """Scrubs the message and every ``extra`` attribute before any handler sees them."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            message = str(record.msg)
        record.msg = redact_text(message)
        record.args = ()
        for key in list(record.__dict__):
            if key in _STANDARD_ATTRS:
                continue
            record.__dict__[key] = redact_value(record.__dict__[key], key)
        if record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        return True


# --- Formatters --------------------------------------------------------------


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: redact_value(value, key)
        for key, value in record.__dict__.items()
        if key not in _STANDARD_ATTRS and key != "request_id"
    }


def _request_id(record: logging.LogRecord) -> str | None:
    explicit = getattr(record, "request_id", None)
    return str(explicit) if explicit else request_id_var.get()


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Fixed keys first, ``extra`` after, redacted."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
            "request_id": _request_id(record),
        }
        for key, value in _extras(record).items():
            payload.setdefault(key, value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        elif record.exc_text:
            payload["exception"] = record.exc_text
        if record.stack_info:
            payload["stack"] = record.stack_info
        line = json.dumps(payload, default=str, ensure_ascii=False, separators=(",", ":"))
        return redact_text(line)


class TextFormatter(logging.Formatter):
    """Readable output for a terminal. Same fields, same redaction."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-8s %(name)s [%(request_id)s] %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = _request_id(record) or "-"
        extras = " ".join(f"{key}={value!r}" for key, value in _extras(record).items())
        line = super().format(record)
        if extras:
            line = f"{line} {extras}"
        return redact_text(line)


# --- Configuration -----------------------------------------------------------


def build_handler(*, environment: str, stream: TextIO | None = None) -> logging.Handler:
    """A handler with the right formatter for the environment and the filter attached."""
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(TextFormatter() if environment == "local" else JsonFormatter())
    handler.addFilter(RedactionFilter())
    return handler


def configure_logging(
    *, environment: str, level: str, stream: TextIO | None = None
) -> logging.Handler:
    """Install the one root handler every process of the stack uses.

    Idempotent and deliberately forceful: uvicorn and the dramatiq CLI both
    call ``logging.basicConfig`` before importing the application, and their
    handlers are removed here so nothing is logged twice or in another format.
    uvicorn's own access log is silenced: :class:`AccessLogMiddleware` writes
    the line, without the query string and with the route template instead of
    the path.
    """
    handler = build_handler(environment=environment, stream=stream)
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "dramatiq", "apscheduler"):
        third_party = logging.getLogger(name)
        third_party.handlers.clear()
        third_party.propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    return handler


# --- Access log --------------------------------------------------------------

access_logger = logging.getLogger("estampa.access")


def route_template(scope: Scope) -> str:
    """The matched route with its parameters as placeholders, e.g. ``/v/{token}``.

    Starlette leaves the resolved ``path_params`` in the scope; every segment
    equal to a parameter value is replaced by its name. A path that matched no
    route is logged as received, minus the query string, and the viewer
    pattern in :func:`redact_text` still masks a token on it.
    """
    path = str(scope.get("path", ""))
    params: Mapping[str, Any] = scope.get("path_params") or {}
    if not params:
        return path
    by_value = {str(value): name for name, value in params.items()}
    return "/".join(
        f"{{{by_value[segment]}}}" if segment in by_value else segment
        for segment in path.split("/")
    )


class AccessLogMiddleware:
    """One log line per request. Method, route template, status, duration, request id.

    Pure ASGI, so the duration covers a streamed PDF to its last byte. Paths
    under ``skip_prefixes`` (the health probes) are not logged: a readiness
    probe every ten seconds is noise, not an audit trail.
    """

    def __init__(self, app: ASGIApp, *, skip_prefixes: Sequence[str] = ("/health",)) -> None:
        self.app = app
        self.skip_prefixes = tuple(skip_prefixes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status = 500
        request_id: str | None = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status, request_id
            if message["type"] == "http.response.start":
                status = int(message["status"])
                for name, value in message.get("headers", []):
                    if name.lower() == b"x-request-id":
                        request_id = value.decode("latin-1")
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = str(scope.get("path", ""))
            if not path.startswith(self.skip_prefixes):
                route = route_template(scope)
                method = str(scope.get("method", "-"))
                duration_ms = round((time.perf_counter() - started) * 1000, 1)
                access_logger.info(
                    "%s %s %s",
                    method,
                    route,
                    status,
                    extra={
                        "method": method,
                        "route": route,
                        "status": status,
                        "duration_ms": duration_ms,
                        "request_id": request_id or request_id_var.get(),
                    },
                )
