from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from anxious_news_bot.preferences.domain import (
    SupportedLanguage,
    TuneState,
    TuneStateKind,
)
from anxious_news_bot.preferences.errors import AnswerRejected
from anxious_news_bot.preferences.services.language import UserLanguageService
from anxious_news_bot.preferences.services.tune import PreferenceTuningService

LOGGER = logging.getLogger(__name__)
CALLBACK_PREFIX = "t:"
MESSAGES = {
    SupportedLanguage.RUSSIAN: {
        "question": "Вопрос",
        "invalid": "Этот вариант ответа недействителен.",
        "stale": "Этот вариант устарел. Отправьте /tune, чтобы продолжить.",
        "generating": "Создаю анкету предпочтений...",
        "processing": "Обновляю ваши предпочтения...",
        "completed": "Ваши новостные предпочтения обновлены.",
        "failed": "Настройка предпочтений не удалась. Отправьте /tune ещё раз.",
    },
    SupportedLanguage.ENGLISH: {
        "question": "Question",
        "invalid": "This preference option is invalid.",
        "stale": "This option is stale. Send /tune to resume your questionnaire.",
        "generating": "Creating your preference questionnaire...",
        "processing": "Updating your preferences...",
        "completed": "Your news preferences have been updated.",
        "failed": "Preference tuning failed. Send /tune to try again.",
    },
    SupportedLanguage.SPANISH: {
        "question": "Pregunta",
        "invalid": "Esta opción de preferencia no es válida.",
        "stale": "Esta opción ha caducado. Envía /tune para continuar.",
        "generating": "Creando tu cuestionario de preferencias...",
        "processing": "Actualizando tus preferencias...",
        "completed": "Tus preferencias de noticias se han actualizado.",
        "failed": "No se pudieron ajustar las preferencias. Envía /tune de nuevo.",
    },
}


class TuneTelegramAdapter:
    def __init__(
        self,
        service: PreferenceTuningService,
        language_service: UserLanguageService,
    ) -> None:
        self._service = service
        self._language_service = language_service

    async def command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if update.effective_user is None or update.message is None:
            LOGGER.warning("tune_command_missing_user_or_message")
            return
        language = await self._language_service.get(
            update.effective_user.id,
            update.effective_user.language_code,
        )
        state = await self._service.start_or_resume(
            update.effective_user.id,
            language.value,
        )
        await self._render_message(update.message.reply_text, state, language)

    async def callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        query = update.callback_query
        if query is None:
            LOGGER.warning("tune_callback_missing_query")
            return
        await query.answer()
        user = update.effective_user
        data = query.data
        if (
            user is None
            or not isinstance(data, str)
            or not data.startswith(CALLBACK_PREFIX)
        ):
            await query.edit_message_text(
                MESSAGES[SupportedLanguage.ENGLISH]["invalid"]
            )
            return
        language = await self._language_service.get(user.id, user.language_code)
        try:
            state = await self._service.answer(
                user.id, data.removeprefix(CALLBACK_PREFIX)
            )
        except AnswerRejected:
            await query.edit_message_text(MESSAGES[language]["stale"])
            return

        # If still asking a question, edit the message
        if state.kind is TuneStateKind.QUESTION:
            await self._render_message(query.edit_message_text, state, language)
        else:
            # Delete the question and send a new message for processing/completed states
            await query.delete_message()
            state_messages = {
                TuneStateKind.GENERATING: MESSAGES[language]["generating"],
                TuneStateKind.PROCESSING: MESSAGES[language]["processing"],
                TuneStateKind.COMPLETED: MESSAGES[language]["completed"],
                TuneStateKind.FAILED: MESSAGES[language]["failed"],
            }
            await query.message.chat.send_message(state_messages[state.kind])

    @staticmethod
    async def _render_message(
        reply,
        state: TuneState,
        language: SupportedLanguage = SupportedLanguage.ENGLISH,
    ) -> None:
        # This method only handles QUESTION states
        if state.kind is not TuneStateKind.QUESTION:
            LOGGER.warning(
                "_render_message called with non-question state: %s", state.kind
            )
            return

        messages = MESSAGES[language]
        if state.ordinal is None or state.question is None:
            raise RuntimeError("question state is incomplete")
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        option.label,
                        callback_data=f"{CALLBACK_PREFIX}{option.callback_token}",
                    )
                ]
                for option in state.options
            ]
        )
        await reply(
            f"{messages['question']} {state.ordinal}/10\n\n{state.question}",
            reply_markup=keyboard,
        )
