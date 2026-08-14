"""Digest count validation and configuration service."""

from __future__ import annotations

from anxious_news_bot.digest.domain import (
    DigestConfigurationSnapshot,
    validate_digest_count,
)
from anxious_news_bot.digest.ports import Clock, DigestConfigurationRepository


class DigestConfigurationService:
    def __init__(
        self,
        repository: DigestConfigurationRepository,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._clock = clock

    async def set_count(
        self,
        *,
        telegram_user_id: int,
        language_hint: str | None,
        count: int,
    ) -> DigestConfigurationSnapshot:
        validate_digest_count(count)
        now = self._clock.now()
        return await self._repository.set_count(
            telegram_user_id, language_hint, count, now
        )

    async def get_current(
        self,
        telegram_user_id: int,
        language_hint: str | None,
    ) -> DigestConfigurationSnapshot:
        return await self._repository.get_current(telegram_user_id, language_hint)
