"""Retention actors. Scheduled, tenant-wide, and safe to run twice."""

from __future__ import annotations

import logging

import dramatiq

from app.services import retention
from app.tasks.broker import run

logger = logging.getLogger("estampa.tasks.retention")

QUEUE = "retention"
DEFAULT_BATCH = 500


@dramatiq.actor(queue_name=QUEUE, max_retries=0)
def sweep_expired(limit: int = DEFAULT_BATCH) -> None:
    """Withdraw every document whose retention period is up.

    Idempotent: a document already handled no longer matches the sweep, so
    running this twice in a row processes nothing the second time.
    """
    processed = run(lambda db: retention.apply_due(db, limit=limit))
    logger.info("retention sweep processed %s documents", processed)
