"""Digest retention service."""

from __future__ import annotations

import logging
from datetime import timedelta

from anxious_news_bot.digest.ports import Clock

LOGGER = logging.getLogger(__name__)


class DigestRetentionService:
    def __init__(
        self,
        repository: object,
        clock: Clock,
        *,
        history_retention_days: int = 30,
        batch_size: int = 500,
    ) -> None:
        if history_retention_days < 1:
            raise ValueError("history_retention_days must be positive")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._repository = repository
        self._clock = clock
        self._history_retention_days = history_retention_days
        self._batch_size = batch_size

    async def run_cleanup(self) -> int:
        now = self._clock.now()
        cutoff = now - timedelta(days=self._history_retention_days)
        deleted_history = await self._repository.delete_expired_history(
            cutoff, self._batch_size
        )
        deleted_details = await self._repository.delete_expired_details(
            cutoff,
            self._batch_size,
        )
        deleted = deleted_history + deleted_details
        if deleted > 0:
            LOGGER.info(
                "digest_retention_cleanup",
                extra={"digest": {"deleted_count": deleted}},
            )
        return deleted
