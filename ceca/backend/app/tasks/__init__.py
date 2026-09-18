"""Dramatiq actors. Importing this package registers every actor on the broker.

The dramatiq CLI imports this module by name (``dramatiq app.tasks``), so this
is also where the worker's logging is configured: the CLI's own
``basicConfig`` runs first and is replaced here, so the worker logs in the same
JSON shape as the API.
"""

from app.config import get_settings
from app.logging import configure_logging
from app.tasks.broker import broker, run, tenant_context
from app.tasks.documents import embed_document_qr, withdraw_document
from app.tasks.retention import sweep_expired

_settings = get_settings()
configure_logging(environment=_settings.environment, level=_settings.log_level)

__all__ = [
    "broker",
    "embed_document_qr",
    "run",
    "sweep_expired",
    "tenant_context",
    "withdraw_document",
]
