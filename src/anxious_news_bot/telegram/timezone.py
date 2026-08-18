from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from anxious_news_bot.preferences.domain import SupportedLanguage
from anxious_news_bot.preferences.services.language import UserLanguageService
from anxious_news_bot.preferences.services.timezone import UserTimezoneService

LOGGER = logging.getLogger(__name__)

_MIN_OFFSET = -12
_MAX_OFFSET = 14

MESSAGES = {
    SupportedLanguage.RUSSIAN: {
        "current": "Ваш часовой пояс: {tz}.",
        "changed": "Часовой пояс изменён на {tz}.",
        "invalid": (
            "Неверное значение. Используйте: /timezone +3 или /timezone -5 "
            f"(от {_MIN_OFFSET} до +{_MAX_OFFSET})."
        ),
    },
    SupportedLanguage.ENGLISH: {
        "current": "Your timezone: {tz}.",
        "changed": "Timezone set to {tz}.",
        "invalid": (
            "Invalid value. Use: /timezone +3 or /timezone -5 "
            f"(from {_MIN_OFFSET} to +{_MAX_OFFSET})."
        ),
    },
    SupportedLanguage.SPANISH: {
        "current": "Tu zona horaria: {tz}.",
        "changed": "Zona horaria establecida a {tz}.",
        "invalid": (
            "Valor inválido. Usa: /timezone +3 o /timezone -5 "
            f"(de {_MIN_OFFSET} a +{_MAX_OFFSET})."
        ),
    },
}


def _tz_label(offset: int) -> str:
    if offset == 0:
        return "UTC"
    sign = "+" if offset > 0 else ""
    return f"UTC{sign}{offset}"


class TimezoneTelegramAdapter:
    def __init__(
        self,
        timezone_service: UserTimezoneService,
        language_service: UserLanguageService,
    ) -> None:
        self._timezone_service = timezone_service
        self._language_service = language_service

    async def command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        message = update.message
        if user is None or message is None:
            LOGGER.warning("timezone_command_missing_user_or_message")
            return
        language = await self._language_service.get(user.id, user.language_code)
        text = MESSAGES[language]

        if not context.args:
            offset = await self._timezone_service.get(user.id)
            await message.reply_text(text["current"].format(tz=_tz_label(offset)))
            return

        raw = context.args[0]
        try:
            offset = int(raw.lstrip("+")) if raw.startswith("+") else int(raw)
        except ValueError:
            await message.reply_text(text["invalid"])
            return

        if not _MIN_OFFSET <= offset <= _MAX_OFFSET:
            await message.reply_text(text["invalid"])
            return

        await self._timezone_service.set(user.id, offset)
        await message.reply_text(text["changed"].format(tz=_tz_label(offset)))
