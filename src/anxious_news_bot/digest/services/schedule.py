"""Daily timezone occurrence resolution and due-cycle draining."""

from __future__ import annotations

import time as time_module
from datetime import datetime

from anxious_news_bot.digest.domain import DueOccurrence
from anxious_news_bot.digest.observability import log_digest_event
from anxious_news_bot.digest.ports import Clock, DigestConfigurationRepository


class DigestScheduleService:
    def __init__(
        self,
        config_repository: DigestConfigurationRepository,
        clock: Clock,
        *,
        claim_batch_size: int = 100,
        max_claims_per_tick: int = 1000,
        claim_time_budget_seconds: int = 30,
    ) -> None:
        if claim_batch_size < 1:
            raise ValueError("claim_batch_size must be positive")
        if max_claims_per_tick < claim_batch_size:
            raise ValueError("max_claims_per_tick must not be below claim_batch_size")
        if claim_time_budget_seconds <= 0:
            raise ValueError("claim_time_budget_seconds must be positive")
        self._config_repository = config_repository
        self._clock = clock
        self._claim_batch_size = claim_batch_size
        self._max_claims_per_tick = max_claims_per_tick
        self._claim_time_budget_seconds = claim_time_budget_seconds

    async def claim_due_batch(self, now: datetime) -> tuple[DueOccurrence, ...]:
        """Drain due configurations in multiple batches."""
        total_claimed = 0
        all_occurrences: list[DueOccurrence] = []
        start_time = time_module.monotonic()

        while total_claimed < self._max_claims_per_tick:
            elapsed = time_module.monotonic() - start_time
            if elapsed >= self._claim_time_budget_seconds:
                break
            remaining = self._max_claims_per_tick - total_claimed
            batch = await self._config_repository.claim_due(
                now,
                min(self._claim_batch_size, remaining),
            )
            if not batch:
                break
            all_occurrences.extend(batch)
            total_claimed += len(batch)

        if total_claimed > 0:
            log_digest_event(
                "due_cycle_claimed",
                phase="schedule",
                status="claimed",
                fields={"claimed_count": total_claimed},
            )
        return tuple(all_occurrences)
