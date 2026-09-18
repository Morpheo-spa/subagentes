"""Application composition: middlewares, error handling, routers."""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from app import cache
from app.config import get_settings
from app.db import engine
from app.deps import negotiate_language
from app.errors import DomainError, error_detail, localised_message
from app.logging import AccessLogMiddleware, configure_logging, request_id_var
from app.routers import (
    auth,
    billing,
    deca,
    documents,
    printing,
    public,
    retention,
    sites,
    storage,
    users,
)

logger = logging.getLogger("estampa")
settings = get_settings()


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Tags every request so a user-visible error can be traced in the logs."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        # Every log line written while this request runs carries the id.
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response


PUBLIC_VIEWER_PREFIX = "/v/"

#: Applied to every public-viewer response, success or failure. An error page is
#: just as indexable as a document page, so the headers cannot live in the router.
PUBLIC_VIEWER_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}


class PublicViewerHeadersMiddleware(BaseHTTPMiddleware):
    """Keeps the QR viewer out of search engines and caches, including on 404."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith(PUBLIC_VIEWER_PREFIX):
            response.headers.update(PUBLIC_VIEWER_HEADERS)
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings.require_billing_config()
    logger.info(
        "estampa starting",
        extra={"environment": settings.environment, "billing_enabled": settings.billing_enabled},
    )
    try:
        yield
    finally:
        await cache.close_redis()


# --- Health ------------------------------------------------------------------
#
# Kubernetes semantics. /health/live answers whenever the process can run a
# coroutine: it looks at nothing, so a dependency outage never gets the API
# restarted. /health/ready looks at everything a request needs, each check
# under its own short timeout: a readiness probe that hangs takes the whole
# rollout with it, one that fails just keeps traffic away.
#
# The body never names versions, hosts or the exception: "ok" or "failed" per
# check is all a probe needs and all an outsider gets. The reason goes to the
# log, with the request id.

#: Per check. Well above a healthy round trip, well below any probe timeout.
READINESS_CHECK_TIMEOUT_SECONDS = 1.5

Check = Callable[[], Coroutine[Any, Any, bool]]


async def _check_database() -> bool:
    async with engine.connect() as connection:
        await connection.execute(select(1))
    return True


async def _check_redis() -> bool:
    return bool(await cache.get_redis().ping())


def _probe_storage_root(root: str) -> bool:
    """The directory exists and a file can be created in it. A real write, not
    ``os.access``: a volume mounted read-only passes the mode check and fails
    the first upload."""
    path = Path(root)
    if not path.is_dir():
        return False
    with tempfile.NamedTemporaryFile(dir=path, prefix=".readiness-", suffix=".probe"):
        pass
    return True


async def _check_storage() -> bool:
    return await asyncio.to_thread(_probe_storage_root, settings.local_storage_root)


async def _guarded(name: str, check: Check) -> tuple[str, str]:
    try:
        healthy = await asyncio.wait_for(check(), timeout=READINESS_CHECK_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.warning("readiness check %s timed out", name)
        return name, "failed"
    except Exception:
        logger.warning("readiness check %s failed", name, exc_info=True)
        return name, "failed"
    return name, "ok" if healthy else "failed"


async def readiness() -> JSONResponse:
    checks: dict[str, str] = dict(
        await asyncio.gather(
            _guarded("database", _check_database),
            _guarded("redis", _check_redis),
            _guarded("storage", _check_storage),
        )
    )
    ready = all(state == "ok" for state in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
        headers={"Cache-Control": "no-store"},
    )


async def liveness() -> dict[str, str]:
    return {"status": "ok"}


def create_app() -> FastAPI:
    configure_logging(environment=settings.environment, level=settings.log_level)
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url=None if settings.is_production else "/docs",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(PublicViewerHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.public_base_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-Request-ID",
            "Content-Disposition",
            # A truncated export is only honest if the SPA can read that it was.
            "X-Export-Total",
            "X-Export-Row-Limit",
            "X-Export-Truncated",
        ],
    )
    # Added last, so it wraps everything above: the duration it logs is the
    # whole request, and the status is the one that actually left.
    app.add_middleware(AccessLogMiddleware)

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        language = negotiate_language(request.headers.get("Accept-Language"))
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": error_detail(exc, language)},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        language = negotiate_language(request.headers.get("Accept-Language"))
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "VALIDATION_ERROR",
                    "message": localised_message("VALIDATION_ERROR", language, {}),
                    "fields": [
                        {
                            "field": ".".join(str(part) for part in err["loc"][1:]),
                            "message": err["msg"],
                        }
                        for err in exc.errors()
                    ],
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.exception("unhandled error", extra={"request_id": request_id})
        language = negotiate_language(request.headers.get("Accept-Language"))
        return JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "code": "INTERNAL_ERROR",
                    "message": localised_message("INTERNAL_ERROR", language, {}),
                    "request_id": request_id,
                }
            },
        )

    app.add_api_route("/health/live", liveness, methods=["GET"], tags=["ops"])
    app.add_api_route("/health/ready", readiness, methods=["GET"], tags=["ops"])
    # Alias of /health/live, kept so an existing healthcheck keeps working.
    app.add_api_route("/health", liveness, methods=["GET"], tags=["ops"], include_in_schema=False)

    prefix = settings.api_prefix
    app.include_router(auth.router, prefix=prefix)
    app.include_router(sites.router, prefix=prefix)
    app.include_router(users.router, prefix=prefix)
    app.include_router(documents.router, prefix=prefix)
    app.include_router(deca.router, prefix=prefix)
    app.include_router(printing.router, prefix=prefix)
    app.include_router(storage.router, prefix=prefix)
    app.include_router(retention.router, prefix=prefix)
    app.include_router(billing.router, prefix=prefix)
    # The public QR viewer is deliberately outside /api/v1: short URLs fit on a label.
    app.include_router(public.router)

    return app


app = create_app()
