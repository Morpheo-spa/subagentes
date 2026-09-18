"""Production logs: JSON, one line per event, a request id, and never a secret.

The redaction has two layers and both are exercised: the filter scrubs
``extra`` by key, the formatter scrubs the final line by pattern. The access
log is checked end to end through the app: the viewer route is written as
``/v/{token}``, the query string is never written.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest

from app.logging import (
    REDACTED,
    AccessLogMiddleware,
    JsonFormatter,
    TextFormatter,
    access_logger,
    build_handler,
    redact_text,
    request_id_var,
    route_template,
)

#: Assembled at runtime on purpose: a key-shaped literal in the source trips
#: GitHub's push protection, and the filter under test only sees the value.
FAKE_STRIPE_KEY = "sk_live_" + "Q" * 24


@pytest.fixture
def json_log() -> Iterator[tuple[logging.Logger, io.StringIO]]:
    """A logger of its own with the production handler on a buffer."""
    buffer = io.StringIO()
    logger = logging.getLogger("estampa.test.redaction")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handler = build_handler(environment="production", stream=buffer)
    logger.addHandler(handler)
    try:
        yield logger, buffer
    finally:
        logger.removeHandler(handler)


def _lines(buffer: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]


# --- Format ------------------------------------------------------------------


def test_production_is_one_json_object_per_line_with_the_fixed_fields(
    json_log: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, buffer = json_log
    token = request_id_var.set("req-123")
    try:
        logger.info("estampa starting", extra={"environment": "production"})
        logger.warning("second line")
    finally:
        request_id_var.reset(token)

    lines = _lines(buffer)
    assert len(lines) == 2
    first = lines[0]
    assert set(first) >= {"timestamp", "level", "logger", "message", "request_id"}
    assert first["level"] == "INFO"
    assert first["logger"] == "estampa.test.redaction"
    assert first["message"] == "estampa starting"
    assert first["request_id"] == "req-123"
    assert first["environment"] == "production"
    assert first["timestamp"].endswith("Z")
    assert lines[1]["level"] == "WARNING"


def test_local_is_readable_text_and_production_is_json() -> None:
    assert isinstance(build_handler(environment="local").formatter, TextFormatter)
    assert isinstance(build_handler(environment="production").formatter, JsonFormatter)
    assert isinstance(build_handler(environment="staging").formatter, JsonFormatter)


def test_request_id_is_null_outside_a_request(
    json_log: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, buffer = json_log
    logger.info("no request here")
    assert _lines(buffer)[0]["request_id"] is None


# --- Redaction ---------------------------------------------------------------


def test_an_authorization_header_in_extra_is_redacted(
    json_log: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, buffer = json_log
    logger.info(
        "login attempt",
        extra={
            "headers": {
                "Authorization": "Bearer xxx",
                "Cookie": "estampa_refresh=abc.def.ghi",
                "Accept": "text/html",
            }
        },
    )

    raw = buffer.getvalue()
    assert "xxx" not in raw
    assert "abc.def.ghi" not in raw
    headers = _lines(buffer)[0]["headers"]
    assert headers["Authorization"] == REDACTED
    assert headers["Cookie"] == REDACTED
    assert headers["Accept"] == "text/html", "harmless headers survive"


def test_a_password_and_a_token_in_nested_extra_are_redacted(
    json_log: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, buffer = json_log
    logger.info(
        "signup",
        extra={
            "payload": {
                "email": "ana@example.com",
                "password": "hunter2",
                "tokens": {"access_token": "eyJabc.def.ghi", "refresh_token": "r-1"},
            },
            "share_token": "N0pRpi4lYlXsA5iDJ8f9wmFqlbZ6b4bN",
        },
    )

    raw = buffer.getvalue()
    for secret in ("hunter2", "eyJabc.def.ghi", "r-1", "N0pRpi4lYlXsA5iDJ8f9wmFqlbZ6b4bN"):
        assert secret not in raw
    payload = _lines(buffer)[0]["payload"]
    assert payload["email"] == "ana@example.com"
    assert payload["password"] == REDACTED
    assert payload["tokens"] == REDACTED


def test_a_credential_written_into_the_message_is_redacted(
    json_log: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, buffer = json_log
    logger.info("upstream said: Authorization: Bearer secret-token-value, retrying")
    logger.info("stripe key %s rejected", FAKE_STRIPE_KEY)
    logger.info("bad jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcDEF-ghi")

    raw = buffer.getvalue()
    assert "secret-token-value" not in raw
    assert FAKE_STRIPE_KEY not in raw
    assert "eyJhbGciOiJIUzI1NiJ9" not in raw
    assert raw.count(REDACTED) >= 3


def test_an_exception_message_carrying_a_secret_is_redacted(
    json_log: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, buffer = json_log
    try:
        raise RuntimeError("refused with password=hunter2")
    except RuntimeError:
        logger.exception("unhandled")

    raw = buffer.getvalue()
    assert "hunter2" not in raw
    assert "RuntimeError" in _lines(buffer)[0]["exception"]


def test_the_text_formatter_redacts_too() -> None:
    buffer = io.StringIO()
    logger = logging.getLogger("estampa.test.text")
    logger.propagate = False
    handler = build_handler(environment="local", stream=buffer)
    logger.addHandler(handler)
    try:
        logger.info("login", extra={"headers": {"Authorization": "Bearer xxx"}})
    finally:
        logger.removeHandler(handler)

    raw = buffer.getvalue()
    assert "xxx" not in raw
    assert REDACTED in raw
    assert "login" in raw


@pytest.mark.parametrize(
    ("text", "hidden"),
    [
        ("GET /v/N0pRpi4lYlXsA5iDJ8f9wmFqlbZ6b4bN 200", "N0pRpi4lYlXsA5iDJ8f9wmFqlbZ6b4bN"),
        ("Set-Cookie: estampa_refresh=abc; HttpOnly", "abc"),
        ('{"password": "hunter2"}', "hunter2"),
        ("token=abc123&next=/docs", "abc123"),
        ("whsec_1234567890abcdef", "1234567890abcdef"),
    ],
)
def test_redact_text_patterns(text: str, hidden: str) -> None:
    assert hidden not in redact_text(text)


def test_redact_text_leaves_ordinary_text_alone() -> None:
    line = "retention sweep processed 12 documents"
    assert redact_text(line) == line


def test_redacting_a_json_line_keeps_it_json() -> None:
    line = json.dumps({"message": 'body was {"password": "hunter2", "token": "t-1"}', "n": 1})
    scrubbed = json.loads(redact_text(line))
    assert "hunter2" not in scrubbed["message"]
    assert "t-1" not in scrubbed["message"]
    assert scrubbed["n"] == 1


# --- Access log --------------------------------------------------------------


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def access_records() -> Iterator[list[logging.LogRecord]]:
    capture = _Capture()
    access_logger.addHandler(capture)
    access_logger.setLevel(logging.INFO)
    try:
        yield capture.records
    finally:
        access_logger.removeHandler(capture)


async def test_the_viewer_is_logged_as_its_route_template_never_the_token(
    client: Any, access_records: list[logging.LogRecord]
) -> None:
    token = "N0pRpi4lYlXsA5iDJ8f9wmFqlbZ6b4bN"

    response = await client.get(f"/v/{token}?next=secret-query")

    assert response.status_code == 404
    assert len(access_records) == 1
    record = access_records[0]
    assert record.route == "/v/{token}"  # type: ignore[attr-defined]
    assert record.method == "GET"  # type: ignore[attr-defined]
    assert record.status == 404  # type: ignore[attr-defined]
    assert isinstance(record.duration_ms, float)  # type: ignore[attr-defined]
    assert record.request_id == response.headers["X-Request-ID"]  # type: ignore[attr-defined]
    rendered = JsonFormatter().format(record)
    assert token not in rendered
    assert "secret-query" not in rendered
    assert "/v/{token}" in rendered


async def test_health_probes_are_not_logged(
    client: Any, access_records: list[logging.LogRecord]
) -> None:
    await client.get("/health/live")
    await client.get("/health/ready")
    assert access_records == []


async def test_the_query_string_never_reaches_the_access_log(
    client: Any, access_records: list[logging.LogRecord]
) -> None:
    await client.get("/api/v1/auth/me?access_token=leaked")
    assert len(access_records) == 1
    assert "leaked" not in JsonFormatter().format(access_records[0])


def test_route_template_substitutes_every_path_parameter() -> None:
    scope = {
        "path": "/api/v1/documents/9b0e/file",
        "path_params": {"document_id": "9b0e"},
    }
    assert route_template(scope) == "/api/v1/documents/{document_id}/file"
    assert route_template({"path": "/nowhere", "path_params": {}}) == "/nowhere"


def test_the_middleware_is_the_outermost_layer() -> None:
    from app.main import app

    assert app.user_middleware[0].cls is AccessLogMiddleware
