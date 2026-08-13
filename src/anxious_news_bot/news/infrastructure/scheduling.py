from __future__ import annotations

import logging
from typing import Any

from telegram.ext import JobQueue

from anxious_news_bot.news.domain import AggregationStatus
from anxious_news_bot.news.ports import NewsAggregator

LOGGER = logging.getLogger(__name__)


class AggregationScheduler:
    def __init__(
        self,
        job_queue: JobQueue,
        aggregator: NewsAggregator,
        *,
        interval_seconds: int,
    ) -> None:
        self._job_queue = job_queue
        self._aggregator = aggregator
        self._interval_seconds = interval_seconds
        self._job: Any | None = None

    def start(self) -> None:
        if self._job is not None:
            return
        self._job = self._job_queue.run_repeating(
            self._tick,
            interval=self._interval_seconds,
            first=self._interval_seconds,
            name="news-aggregation",
        )

    def stop(self) -> None:
        if self._job is not None:
            self._job.schedule_removal()
            self._job = None

    async def _tick(self, context: object) -> None:
        del context
        result = await self._aggregator.run_cycle()
        if result.status is AggregationStatus.ALREADY_RUNNING:
            LOGGER.info("news_cycle_already_running")
