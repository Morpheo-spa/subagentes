"""Document actors. The logic lives in the service; the actor only orchestrates."""

from __future__ import annotations

import logging
from uuid import UUID

import dramatiq

from app.services import documents
from app.tasks.broker import run, tenant_context

logger = logging.getLogger("estampa.tasks.documents")

QUEUE = "documents"


@dramatiq.actor(queue_name=QUEUE, max_retries=3)
def embed_document_qr(document_id: str, mm_id: str, site_id: str) -> None:
    """Stamp the QR into a natively uploaded PDF.

    Idempotent: the service does nothing once ``qr_embedded`` is set, so a
    redelivered message never rewrites the file twice.
    """
    ctx = tenant_context(mm_id, site_id)
    changed = run(lambda db: documents.stamp_qr(db, ctx, UUID(document_id)))
    logger.info("qr embed %s: %s", document_id, "done" if changed else "skipped")


@dramatiq.actor(queue_name=QUEUE, max_retries=3)
def withdraw_document(document_id: str, mm_id: str, site_id: str, reason: str) -> None:
    """Withdraw a file out of band. Idempotent: an already withdrawn row is left alone."""
    ctx = tenant_context(mm_id, site_id)
    run(lambda db: documents.withdraw(db, ctx, UUID(document_id), reason=reason))
    logger.info("withdrew document %s", document_id)
