"""Localized /count Telegram command adapter."""

from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from anxious_news_bot.digest.domain import DIGEST_COUNT_MAX, DIGEST_COUNT_MIN
from anxious_news_bot.digest.services.configuration import DigestConfigurationService
from anxious_news_bot.preferences.domain import (
    SupportedLanguage,
    normalize_language_code,
)
from anxious_news_bot.preferences.services.language import UserLanguageService

LOGGER = logging.getLogger(__name__)

CONFIRMATION_MESSAGES = {
    SupportedLanguage.RUSSIAN: "Размер дайджеста: {count}.",
    SupportedLanguage.ENGLISH: "Digest size: {count}.",
    SupportedLanguage.SPANISH: "Tamano del resumen: {count}.",
}

GUIDANCE_MESSAGES = {
    SupportedLanguage.RUSSIAN: "Используйте /count с числом от 5 до 20.",
    SupportedLanguage.ENGLISH: "Use /count with a number from 5 to 20.",
    SupportedLanguage.SPANISH: "Usa /count con un numero del 5 al 20.",
}

CURRENT_COUNT_MESSAGES = {
    SupportedLanguage.RUSSIAN: "Текущий размер дайджеста: {count}.\n{guidance}",
    SupportedLanguage.ENGLISH: "Current digest size: {count}.\n{guidance}",
    SupportedLanguage.SPANISH: "Tamaño actual del resumen: {count}.\n{guidance}",
}

_DECIMAL_INTEGER = re.compile(r"^[0-9]+$")


class CountTelegramAdapter:
    def __init__(
        self,
        configuration_service: DigestConfigurationService,
        language_service: UserLanguageService,
    ) -> None:
        self._service = configuration_service
        self._language_service = language_service

    async def command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        user = update.effective_user
        message = update.message
        if user is None or message is None:
            LOGGER.warning("count_command_missing_user_or_message")
            return

        try:
            language = await self._language_service.get(user.id, user.language_code)
        except Exception:
            language = normalize_language_code(user.language_code)
            LOGGER.error("count_command_language_lookup_failed")
            from anxious_news_bot.telegram.news import MESSAGES

            await message.reply_text(MESSAGES[language]["failed"])
            return

        # Parse argument
        text = (message.text or "").strip()
        parts = text.split()
        # parts[0] is /count or /count@BotName
        if len(parts) != 2:
            # No argument provided, show current count
            try:
                current_config = await self._service.get_current(
                    user.id, user.language_code
                )
                current_count = current_config.digest_count if current_config else None
                if current_count is None:
                    await message.reply_text(GUIDANCE_MESSAGES[language])
                else:
                    help_text = CURRENT_COUNT_MESSAGES[language].format(
                        count=current_count,
                        guidance=GUIDANCE_MESSAGES[language],
                    )
                    await message.reply_text(help_text)
            except Exception:
                LOGGER.error("count_command_get_current_failed")
                await message.reply_text(GUIDANCE_MESSAGES[language])
            return

        if _DECIMAL_INTEGER.fullmatch(parts[1]) is None:
            await message.reply_text(GUIDANCE_MESSAGES[language])
            return
        value = int(parts[1])

        if value < DIGEST_COUNT_MIN or value > DIGEST_COUNT_MAX:
            await message.reply_text(GUIDANCE_MESSAGES[language])
            return

        try:
            await self._service.set_count(
                telegram_user_id=user.id,
                language_hint=user.language_code,
                count=value,
            )
        except Exception:
            LOGGER.error("count_command_persistence_failed")
            from anxious_news_bot.telegram.news import MESSAGES

            fail_msg = MESSAGES.get(language, MESSAGES[SupportedLanguage.ENGLISH])
            await message.reply_text(fail_msg.get("failed", "An error occurred."))
            return

        await message.reply_text(CONFIRMATION_MESSAGES[language].format(count=value))
