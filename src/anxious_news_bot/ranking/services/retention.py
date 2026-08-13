from __future__ import annotations

from asyncio import Lock

from anxious_news_bot.ranking.domain import RankingRetentionResult, RetentionPolicy
from anxious_news_bot.ranking.ports import Clock, RankingRetentionRepository


class RankingRetentionService:
    def __init__(
        self,
        repository: RankingRetentionRepository,
        clock: Clock,
        *,
        raw_response_days: int,
        detail_days: int,
        batch_size: int,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._raw_response_days = raw_response_days
        self._detail_days = detail_days
        self._batch_size = batch_size
        self._lock = Lock()

    async def run_once(self) -> RankingRetentionResult:
        if self._lock.locked():
            return RankingRetentionResult(already_running=True)
        async with self._lock:
            return await self._repository.cleanup(
                self._clock.now(),
                RetentionPolicy(
                    raw_response_days=self._raw_response_days,
                    detail_days=self._detail_days,
                    batch_size=self._batch_size,
                ),
            )
