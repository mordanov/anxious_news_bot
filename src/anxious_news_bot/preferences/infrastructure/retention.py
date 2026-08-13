from __future__ import annotations

import logging
from typing import Any

from telegram.ext import JobQueue

from anxious_news_bot.preferences.services.retention import (
    PreferenceRetentionService,
)

LOGGER = logging.getLogger(__name__)


class PreferenceRetentionScheduler:
    def __init__(
        self,
        job_queue: JobQueue,
        service: PreferenceRetentionService,
        *,
        interval_seconds: int,
    ) -> None:
        self._job_queue = job_queue
        self._service = service
        self._interval_seconds = interval_seconds
        self._job: Any | None = None

    def start(self) -> None:
        if self._job is None:
            self._job = self._job_queue.run_repeating(
                self._tick,
                interval=self._interval_seconds,
                first=self._interval_seconds,
                name="preference-retention",
            )

    def stop(self) -> None:
        if self._job is not None:
            self._job.schedule_removal()
            self._job = None

    async def _tick(self, context: object) -> None:
        del context
        result = await self._service.run_once()
        LOGGER.info(
            "preference_retention_completed",
            extra={
                "already_running": result.already_running,
                "questionnaire_details_removed": (result.questionnaire_details_removed),
                "failed_questionnaires_removed": (result.failed_questionnaires_removed),
                "full_history_rows_removed": result.full_history_rows_removed,
                "compact_audit_rows_preserved": (result.compact_audit_rows_preserved),
            },
        )
