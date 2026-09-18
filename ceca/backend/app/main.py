"""Application composition: middlewares, error handling, routers."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.deps import negotiate_language
from app.errors import DomainError, error_detail, localised_message
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

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001, ANN201
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings.require_billing_config()
    logger.info(
        "estampa starting", extra={"environment": settings.environment,
                                   "billing_enabled": settings.billing_enabled}
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url=None if settings.is_production else "/docs",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.public_base_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Content-Disposition"],
    )

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        language = negotiate_language(request.headers.get("Accept-Language"))
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": error_detail(exc, language)},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
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

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

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
