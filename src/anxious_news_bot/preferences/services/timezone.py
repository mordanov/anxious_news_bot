from __future__ import annotations

from anxious_news_bot.preferences.ports import PreferenceRepositoryPort


class UserTimezoneService:
    def __init__(self, repository: PreferenceRepositoryPort) -> None:
        self._repository = repository

    async def get(self, telegram_user_id: int) -> int:
        return await self._repository.get_utc_offset(telegram_user_id)

    async def set(self, telegram_user_id: int, offset_hours: int) -> None:
        await self._repository.set_utc_offset(telegram_user_id, offset_hours)
