"""Retention actors. Scheduled, tenant-wide, and safe to run twice.

The schedule lives in ``app/tasks/scheduler.py``; this module is what it
enqueues. Overlapping runs are serialised by a Redis lease
(``app/tasks/locks.py``), so a second scheduler, a manual run from the runbook
or a redelivered message never sweeps the same batch twice at the same time.
"""

from __future__ import annotations

import logging

import dramatiq

from app.services import retention
from app.tasks.broker import run
from app.tasks.locks import LockedRun, locked

logger = logging.getLogger("estampa.tasks.retention")

QUEUE = "retention"
DEFAULT_BATCH = 500

SWEEP_LOCK = "retention:sweep"
#: Above the longest honest sweep (500 storage deletes), well below a day.
SWEEP_LOCK_TTL_SECONDS = 15 * 60


def run_sweep(*, limit: int = DEFAULT_BATCH) -> LockedRun[int]:
    """The sweep itself, callable without a broker.

    Returns whether this run held the lock and, if so, how many documents it
    acted on. Idempotent twice over: a document already handled no longer
    matches the query, and two runs that overlap are serialised by the lease.
    """
    outcome = locked(
        SWEEP_LOCK,
        ttl_seconds=SWEEP_LOCK_TTL_SECONDS,
        operation=lambda: run(lambda db: retention.apply_due(db, limit=limit)),
    )
    if not outcome.acquired:
        logger.info("retention sweep skipped: another sweep holds the lock")
    else:
        logger.info(
            "retention sweep processed %s documents",
            outcome.result,
            extra={"processed": outcome.result, "limit": limit},
        )
    return outcome


@dramatiq.actor(queue_name=QUEUE, max_retries=0)
def sweep_expired(limit: int = DEFAULT_BATCH) -> None:
    """Withdraw every document whose retention period is up."""
    run_sweep(limit=limit)
