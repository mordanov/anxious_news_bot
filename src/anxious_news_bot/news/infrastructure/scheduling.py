from __future__ import annotations

import asyncio
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
        self._cycle_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._job is not None:
            return
        self._job = self._job_queue.run_repeating(
            self._tick,
            interval=self._interval_seconds,
            first=self._interval_seconds,
            name="news-aggregation",
            job_kwargs={
                "coalesce": True,
                "misfire_grace_time": self._interval_seconds,
            },
        )

    def stop(self) -> None:
        if self._job is not None:
            self._job.schedule_removal()
            self._job = None
        if self._cycle_task is not None and not self._cycle_task.done():
            self._cycle_task.cancel()
        self._cycle_task = None

    async def _tick(self, context: object) -> None:
        del context
        if self._cycle_task is not None and not self._cycle_task.done():
            LOGGER.info("news_cycle_already_running")
            return
        self._cycle_task = asyncio.create_task(self._run_cycle())

    async def _run_cycle(self) -> None:
        try:
            result = await self._aggregator.run_cycle()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("news_cycle_error")
            return
        if result.status is AggregationStatus.ALREADY_RUNNING:
            LOGGER.info("news_cycle_already_running")
