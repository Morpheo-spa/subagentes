"""The retention scheduler fires the sweep at RETENTION_SWEEP_HOUR_UTC, once a day."""

from __future__ import annotations

from typing import Any

import pytest

from app.config import get_settings
from app.tasks import scheduler as scheduler_module


class _Sent:
    def __init__(self) -> None:
        self.count = 0

    def send(self) -> Any:
        self.count += 1
        return type("Message", (), {"message_id": f"msg-{self.count}"})()


def test_the_job_follows_the_configured_hour_in_utc() -> None:
    settings = get_settings()

    scheduler = scheduler_module.build_scheduler(settings)
    job = scheduler.get_job(scheduler_module.JOB_ID)

    assert job is not None
    fields = {field.name: str(field) for field in job.trigger.fields}
    assert fields["hour"] == str(settings.retention_sweep_hour_utc)
    assert fields["minute"] == "0"
    assert fields["day"] == "*"
    assert str(job.trigger.timezone) == "UTC"
    assert job.misfire_grace_time == scheduler_module.MISFIRE_GRACE_SECONDS
    assert job.max_instances == 1
    assert len(scheduler.get_jobs()) == 1


def test_once_enqueues_a_sweep_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _Sent()
    monkeypatch.setattr(scheduler_module, "sweep_expired", sent)

    assert scheduler_module.main(["--once"]) == 0

    assert sent.count == 1


def test_the_scheduled_job_enqueues_through_the_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _Sent()
    monkeypatch.setattr(scheduler_module, "sweep_expired", sent)

    scheduler_module.enqueue_sweep()

    assert sent.count == 1
