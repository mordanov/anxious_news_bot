from unittest.mock import AsyncMock, Mock

import anxious_news_bot.app as app_module
from anxious_news_bot.config import Settings
from anxious_news_bot.news.domain import AggregationResult, AggregationStatus
from anxious_news_bot.news.infrastructure.scheduling import AggregationScheduler


async def test_scheduler_registers_recurring_tick_and_calls_only_aggregator() -> None:
    aggregator = AsyncMock()
    aggregator.run_cycle.return_value = AggregationResult(AggregationStatus.COMPLETED)
    job = Mock()
    job_queue = Mock()
    job_queue.run_repeating.return_value = job
    scheduler = AggregationScheduler(job_queue, aggregator, interval_seconds=60)

    scheduler.start()
    callback = job_queue.run_repeating.call_args.args[0]
    await callback(Mock())
    await scheduler._cycle_task
    scheduler.stop()

    job_queue.run_repeating.assert_called_once()
    assert job_queue.run_repeating.call_args.kwargs["job_kwargs"] == {
        "coalesce": True,
        "misfire_grace_time": 60,
    }
    aggregator.run_cycle.assert_awaited_once_with()
    job.schedule_removal.assert_called_once_with()


async def test_scheduler_treats_already_running_as_normal_tick_result() -> None:
    aggregator = AsyncMock()
    aggregator.run_cycle.return_value = AggregationResult(
        AggregationStatus.ALREADY_RUNNING
    )
    job_queue = Mock()
    job_queue.run_repeating.return_value = Mock()
    scheduler = AggregationScheduler(job_queue, aggregator, interval_seconds=10)
    scheduler.start()

    callback = job_queue.run_repeating.call_args.args[0]
    await callback(Mock())
    await scheduler._cycle_task

    aggregator.run_cycle.assert_awaited_once_with()


async def test_application_starts_scheduler_and_closes_resources(monkeypatch) -> None:
    database = Mock()
    database.engine = Mock()
    database.close = AsyncMock()
    client = Mock()
    client.aclose = AsyncMock()
    scheduler = Mock()
    monkeypatch.setattr(app_module, "Database", Mock(return_value=database))
    monkeypatch.setattr(app_module.httpx, "AsyncClient", Mock(return_value=client))
    monkeypatch.setattr(
        app_module, "AggregationScheduler", Mock(return_value=scheduler)
    )
    application = app_module.build_application(Settings(telegram_bot_token="123:ABC"))

    assert application.post_init is not None
    assert application.post_shutdown is not None
    await application.post_init(application)
    await application.post_shutdown(application)

    scheduler.start.assert_called_once_with()
    scheduler.stop.assert_called_once_with()
    client.aclose.assert_awaited_once_with()
    database.close.assert_awaited_once_with()
