from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from anxious_news_bot.preferences.domain import SupportedLanguage
from anxious_news_bot.preferences.services.language import UserLanguageService

LOGGER = logging.getLogger(__name__)
CALLBACK_PREFIX = "lang:"
LANGUAGE_LABELS = {
    SupportedLanguage.RUSSIAN: "Русский",
    SupportedLanguage.ENGLISH: "English",
    SupportedLanguage.SPANISH: "Español",
}
SELECT_LANGUAGE = {
    SupportedLanguage.RUSSIAN: "Выберите язык:",
    SupportedLanguage.ENGLISH: "Choose a language:",
    SupportedLanguage.SPANISH: "Elige un idioma:",
}
LANGUAGE_CHANGED = {
    SupportedLanguage.RUSSIAN: "Язык изменён на Русский. Отправьте /tune, чтобы начать.",
    SupportedLanguage.ENGLISH: "Language changed to English. Send /tune to begin.",
    SupportedLanguage.SPANISH: "Idioma cambiado a Español. Envía /tune para comenzar.",
}


class LanguageTelegramAdapter:
    def __init__(self, service: UserLanguageService) -> None:
        self._service = service

    async def command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if update.effective_user is None or update.message is None:
            LOGGER.warning("language_command_missing_user_or_message")
            return
        language = await self._service.get(
            update.effective_user.id,
            update.effective_user.language_code,
        )
        await update.message.reply_text(
            SELECT_LANGUAGE[language],
            reply_markup=self._keyboard(),
        )

    async def callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        del context
        query = update.callback_query
        user = update.effective_user
        if query is None:
            LOGGER.warning("language_callback_missing_query")
            return
        await query.answer()
        data = query.data
        if (
            user is None
            or not isinstance(data, str)
            or not data.startswith(CALLBACK_PREFIX)
        ):
            await query.edit_message_text("Invalid language selection.")
            return
        code = data.removeprefix(CALLBACK_PREFIX)
        if code not in {language.value for language in SupportedLanguage}:
            await query.edit_message_text("Invalid language selection.")
            return
        language = await self._service.set(user.id, code)
        await query.edit_message_text(LANGUAGE_CHANGED[language])

    @staticmethod
    def _keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        label,
                        callback_data=f"{CALLBACK_PREFIX}{language.value}",
                    )
                ]
                for language, label in LANGUAGE_LABELS.items()
            ]
        )
