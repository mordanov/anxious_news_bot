from __future__ import annotations

import logging
from decimal import Decimal

from telegram import Update
from telegram.ext import ContextTypes

from anxious_news_bot.preferences.domain import SupportedLanguage
from anxious_news_bot.preferences.ports import PreferenceRepositoryPort
from anxious_news_bot.preferences.services.language import UserLanguageService

LOGGER = logging.getLogger(__name__)

MESSAGES = {
    SupportedLanguage.RUSSIAN: {
        "empty": "У вас ещё нет предпочтений. Используйте /tune или /specify для настройки.",
        "header": "Ваши предпочтения ({count}):",
        "inactive": "{count} неактивных",
        "failed": "Не удалось загрузить предпочтения. Попробуйте позже.",
    },
    SupportedLanguage.ENGLISH: {
        "empty": "You have no preferences yet. Use /tune or /specify to get started.",
        "header": "Your preferences ({count}):",
        "inactive": "{count} inactive",
        "failed": "Could not load preferences. Please try again.",
    },
    SupportedLanguage.SPANISH: {
        "empty": "Aún no tienes preferencias. Usa /tune o /specify para empezar.",
        "header": "Tus preferencias ({count}):",
        "inactive": "{count} inactivas",
        "failed": "No se pudieron cargar las preferencias. Inténtalo de nuevo.",
    },
}


class MyTelegramAdapter:
    def __init__(
        self,
        repository: PreferenceRepositoryPort,
        language_service: UserLanguageService,
    ) -> None:
        self._repository = repository
        self._language_service = language_service

    async def command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        user = update.effective_user
        message = update.message
        if user is None or message is None:
            LOGGER.warning("my_command_missing_user_or_message")
            return

        language = await self._language_service.get(user.id, user.language_code)
        messages = MESSAGES[language]

        try:
            profile = await self._repository.load_profile(user.id)
        except Exception:
            LOGGER.exception("my_command_load_profile_failed")
            await message.reply_text(messages["failed"])
            return

        if profile is None or not profile.parameters:
            await message.reply_text(messages["empty"])
            return

        active = [p for p in profile.parameters if p.active]
        inactive_count = sum(1 for p in profile.parameters if not p.active)

        if not active:
            await message.reply_text(messages["empty"])
            return

        active_sorted = sorted(active, key=lambda p: (-abs(p.weight), p.name))

        lines = [messages["header"].format(count=len(active))]
        lines.append("")
        for param in active_sorted:
            sign = "+" if param.weight >= Decimal("0") else "-"
            lines.append(f"{sign}{abs(param.weight):.2f}  {param.name}")

        if inactive_count:
            lines.append("")
            lines.append(messages["inactive"].format(count=inactive_count))

        await message.reply_text("\n".join(lines))
