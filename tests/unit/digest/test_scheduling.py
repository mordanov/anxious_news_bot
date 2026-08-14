from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from anxious_news_bot.digest.infrastructure.scheduling import (
    DigestRetentionScheduler,
    DigestSchedulingAdapter,
)
from tests.fixtures.digest import FixedClock


def test_digest_scheduler_start_stop_are_idempotent():
    queue = MagicMock()
    job = MagicMock()
    queue.run_repeating.return_value = job
    adapter = DigestSchedulingAdapter(
        queue,
        AsyncMock(),
        FixedClock(),
        interval_seconds=60,
    )

    adapter.start()
    adapter.start()
    adapter.stop()
    adapter.stop()

    queue.run_repeating.assert_called_once()
    assert queue.run_repeating.call_args.kwargs["job_kwargs"] == {
        "coalesce": True,
        "misfire_grace_time": 60,
    }
    job.schedule_removal.assert_called_once()


async def test_digest_tick_invokes_only_due_and_retry_cycles():
    queue = MagicMock()
    service = AsyncMock()
    service.run_due_cycle.return_value = SimpleNamespace(
        claimed_count=0, completed_count=0, failed_count=0
    )
    service.retry_due.return_value = SimpleNamespace(
        retried_count=0, completed_count=0, failed_count=0
    )
    adapter = DigestSchedulingAdapter(queue, service, FixedClock())

    await adapter.tick(object())
    await adapter._cycle_task

    service.run_due_cycle.assert_awaited_once()
    service.retry_due.assert_awaited_once()
    assert [entry[0] for entry in service.mock_calls] == [
        "run_due_cycle",
        "retry_due",
    ]


def test_retention_scheduler_lifecycle_is_idempotent():
    queue = MagicMock()
    job = MagicMock()
    queue.run_repeating.return_value = job
    scheduler = DigestRetentionScheduler(queue, AsyncMock())

    scheduler.start()
    scheduler.start()
    scheduler.stop()
    scheduler.stop()

    queue.run_repeating.assert_called_once()
    job.schedule_removal.assert_called_once()


async def test_retention_tick_runs_cleanup():
    service = AsyncMock()
    scheduler = DigestRetentionScheduler(MagicMock(), service)

    await scheduler.tick(object())

    service.run_cleanup.assert_awaited_once_with()
