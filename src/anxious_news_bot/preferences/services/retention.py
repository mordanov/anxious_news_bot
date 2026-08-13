from __future__ import annotations

from asyncio import Lock
from datetime import timedelta

from anxious_news_bot.preferences.domain import RetentionResult
from anxious_news_bot.preferences.infrastructure.repository import (
    SQLAlchemyPreferenceRepository,
)
from anxious_news_bot.preferences.ports import Clock


class PreferenceRetentionService:
    def __init__(
        self,
        repository: SQLAlchemyPreferenceRepository,
        clock: Clock,
        *,
        questionnaire_days: int,
        history_days: int,
        batch_size: int,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._questionnaire_days = questionnaire_days
        self._history_days = history_days
        self._batch_size = batch_size
        self._lock = Lock()

    async def run_once(self) -> RetentionResult:
        if self._lock.locked():
            return RetentionResult(already_running=True)
        async with self._lock:
            now = self._clock.now()
            history_cutoff = (
                None
                if self._history_days == 0
                else now - timedelta(days=self._history_days)
            )
            return await self._repository.compact_retention(
                questionnaire_cutoff=now - timedelta(days=self._questionnaire_days),
                history_cutoff=history_cutoff,
                batch_size=self._batch_size,
            )
