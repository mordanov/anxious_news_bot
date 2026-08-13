from __future__ import annotations

import logging
from typing import Any

from telegram.ext import JobQueue

from anxious_news_bot.ranking.services.retention import RankingRetentionService

LOGGER = logging.getLogger(__name__)


class RankingRetentionScheduler:
    def __init__(
        self,
        job_queue: JobQueue,
        service: RankingRetentionService,
        *,
        interval_seconds: int,
    ) -> None:
        self._job_queue = job_queue
        self._service = service
        self._interval_seconds = interval_seconds
        self._job: Any | None = None

    def start(self) -> None:
        if self._job is not None:
            return
        self._job = self._job_queue.run_repeating(
            self._tick,
            interval=self._interval_seconds,
            first=self._interval_seconds,
            name="ranking-retention",
        )

    def stop(self) -> None:
        if self._job is not None:
            self._job.schedule_removal()
            self._job = None

    async def _tick(self, context: object) -> None:
        del context
        result = await self._service.run_once()
        LOGGER.info(
            "ranking_retention_completed",
            extra={
                "already_running": result.already_running,
                "raw_texts_removed": result.raw_texts_removed,
                "raw_responses_removed": result.raw_responses_removed,
                "evaluation_details_removed": result.evaluation_details_removed,
                "ranking_details_removed": result.ranking_details_removed,
                "compact_audit_rows_preserved": result.compact_audit_rows_preserved,
            },
        )
