"""The clock that enqueues the retention sweep. Run it as its own service.

Dramatiq has no cron: without this process nothing ever calls
``sweep_expired`` and the retention policy is decorative. See ADR-007 in
``docs/DECISIONES.md`` for why this is APScheduler in a separate process
rather than a Dramatiq add-on.

The scheduler does not sweep. It sends one message a day, at
``RETENTION_SWEEP_HOUR_UTC``, and the worker does the work under the Redis
lease in ``app/tasks/locks.py``. Run one replica: a second one would enqueue a
second message, which the lease turns into a logged skip, not a double sweep.

    python -m app.tasks.scheduler          # serve the schedule, forever
    python -m app.tasks.scheduler --once   # enqueue a sweep now and exit
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from typing import Any

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings, get_settings
from app.logging import configure_logging
from app.tasks.retention import sweep_expired

logger = logging.getLogger("estampa.tasks.scheduler")

JOB_ID = "retention-sweep"
#: If the scheduler was down at the scheduled minute (a deploy, a restart) and
#: comes back within this window, the sweep still fires. Beyond it, the run is
#: skipped and the next night catches up: a sweep is never urgent, and the
#: runbook has the manual trigger.
MISFIRE_GRACE_SECONDS = 6 * 60 * 60


def enqueue_sweep() -> None:
    message = sweep_expired.send()
    logger.info("retention sweep enqueued", extra={"message_id": message.message_id})


def build_scheduler(settings: Settings) -> Any:
    """A blocking scheduler with the one job, wired from the settings."""
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        enqueue_sweep,
        CronTrigger(hour=settings.retention_sweep_hour_utc, minute=0, timezone="UTC"),
        id=JOB_ID,
        name="retention sweep",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
        replace_existing=True,
    )
    return scheduler


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Estampa retention scheduler")
    parser.add_argument(
        "--once",
        action="store_true",
        help="enqueue one retention sweep right now and exit",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(environment=settings.environment, level=settings.log_level)

    if args.once:
        enqueue_sweep()
        return 0

    scheduler = build_scheduler(settings)
    logger.info(
        "scheduler starting",
        extra={
            "job": JOB_ID,
            "hour_utc": settings.retention_sweep_hour_utc,
            "environment": settings.environment,
        },
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("scheduler stopping")
    return 0


if __name__ == "__main__":
    sys.exit(main())
