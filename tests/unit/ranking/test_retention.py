from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

import anxious_news_bot.app as app_module
from anxious_news_bot.config import Settings
from anxious_news_bot.ranking.domain import RankingRetentionResult, RetentionPolicy
from tests.fixtures.preferences import FixedClock


class Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[object, RetentionPolicy]] = []
        self._running = asyncio.Event()
        self._release = asyncio.Event()
        self.fail_once = False

    async def cleanup(self, now, policy):
        self.calls.append((now, policy))
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("cleanup failed")
        self._running.set()
        await self._release.wait()
        return RankingRetentionResult(
            raw_texts_removed=1,
            raw_responses_removed=2,
            evaluation_details_removed=3,
            ranking_details_removed=4,
            compact_audit_rows_preserved=5,
        )


async def test_service_passes_now_and_policy_and_allows_disabled_retention() -> None:
    from anxious_news_bot.ranking.services.retention import RankingRetentionService

    repository = Repository()
    service = RankingRetentionService(
        repository,
        FixedClock(),
        raw_response_days=0,
        detail_days=0,
        batch_size=50,
    )

    task = asyncio.create_task(service.run_once())
    await repository._running.wait()
    repository._release.set()
    result = await task

    assert result.raw_texts_removed == 1
    assert repository.calls == [
        (
            FixedClock.value,
            RetentionPolicy(raw_response_days=0, detail_days=0, batch_size=50),
        )
    ]


async def test_service_suppresses_overlap_and_returns_already_running() -> None:
    from anxious_news_bot.ranking.services.retention import RankingRetentionService

    repository = Repository()
    service = RankingRetentionService(
        repository,
        FixedClock(),
        raw_response_days=30,
        detail_days=90,
        batch_size=25,
    )

    first = asyncio.create_task(service.run_once())
    await repository._running.wait()
    overlapping = await service.run_once()
    repository._release.set()
    completed = await first

    assert overlapping.already_running is True
    assert completed.raw_responses_removed == 2
    assert len(repository.calls) == 1


async def test_service_recovers_after_failure_and_releases_lock() -> None:
    from anxious_news_bot.ranking.services.retention import RankingRetentionService

    repository = Repository()
    repository.fail_once = True
    service = RankingRetentionService(
        repository,
        FixedClock(),
        raw_response_days=30,
        detail_days=90,
        batch_size=25,
    )

    with pytest.raises(RuntimeError, match="cleanup failed"):
        await service.run_once()

    next_task = asyncio.create_task(service.run_once())
    await repository._running.wait()
    repository._release.set()
    recovered = await next_task

    assert recovered.already_running is False
    assert len(repository.calls) == 2


async def test_scheduler_registration_is_idempotent_and_logs_result_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import anxious_news_bot.ranking.infrastructure.retention as retention_module

    RankingRetentionScheduler = retention_module.RankingRetentionScheduler

    service = AsyncMock()
    service.run_once.return_value = RankingRetentionResult(
        raw_texts_removed=1,
        raw_responses_removed=2,
        evaluation_details_removed=3,
        ranking_details_removed=4,
        compact_audit_rows_preserved=5,
    )
    job = Mock()
    job_queue = Mock()
    job_queue.run_repeating.return_value = job
    scheduler = RankingRetentionScheduler(job_queue, service, interval_seconds=60)
    logger = Mock()
    monkeypatch.setattr(retention_module, "LOGGER", logger)

    scheduler.start()
    scheduler.start()
    callback = job_queue.run_repeating.call_args.args[0]
    await callback(Mock())
    scheduler.stop()
    scheduler.stop()

    job_queue.run_repeating.assert_called_once()
    service.run_once.assert_awaited_once_with()
    job.schedule_removal.assert_called_once_with()
    logger.info.assert_called_once()
    assert logger.info.call_args.args[0] == "ranking_retention_completed"
    assert logger.info.call_args.kwargs["extra"] == {
        "already_running": False,
        "raw_texts_removed": 1,
        "raw_responses_removed": 2,
        "evaluation_details_removed": 3,
        "ranking_details_removed": 4,
        "compact_audit_rows_preserved": 5,
    }


async def test_application_registers_and_stops_ranking_retention_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Mock()
    database.engine = Mock()
    database.close = AsyncMock()
    client = Mock()
    client.aclose = AsyncMock()
    aggregation_scheduler = Mock()
    preference_scheduler = Mock()
    ranking_scheduler = Mock()

    monkeypatch.setattr(app_module, "Database", Mock(return_value=database))
    monkeypatch.setattr(app_module.httpx, "AsyncClient", Mock(return_value=client))
    monkeypatch.setattr(
        app_module,
        "AggregationScheduler",
        Mock(return_value=aggregation_scheduler),
    )
    monkeypatch.setattr(
        app_module,
        "PreferenceRetentionScheduler",
        Mock(return_value=preference_scheduler),
    )
    monkeypatch.setattr(
        app_module,
        "RankingRetentionScheduler",
        Mock(return_value=ranking_scheduler),
        raising=False,
    )

    application = app_module.build_application(Settings(telegram_bot_token="123:ABC"))

    await application.post_init(application)
    await application.post_shutdown(application)

    ranking_scheduler.start.assert_called_once_with()
    ranking_scheduler.stop.assert_called_once_with()
