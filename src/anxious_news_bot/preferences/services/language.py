from __future__ import annotations

from anxious_news_bot.preferences.domain import (
    SupportedLanguage,
    normalize_language_code,
)
from anxious_news_bot.preferences.ports import Clock, PreferenceRepositoryPort


class UserLanguageService:
    def __init__(self, repository: PreferenceRepositoryPort, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    async def get(
        self,
        telegram_user_id: int,
        telegram_language_code: str | None = None,
    ) -> SupportedLanguage:
        return await self._repository.get_or_create_language(
            telegram_user_id,
            telegram_language_code,
        )

    async def set(
        self,
        telegram_user_id: int,
        language_code: str,
    ) -> SupportedLanguage:
        language = normalize_language_code(language_code)
        await self._repository.set_language(
            telegram_user_id,
            language,
            self._clock.now(),
        )
        return language
