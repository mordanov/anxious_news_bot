from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from anxious_news_bot.preferences.domain import (
    SpecifyState,
    SpecifyStateKind,
    SupportedLanguage,
)
from anxious_news_bot.preferences.services.language import UserLanguageService
from anxious_news_bot.preferences.services.specify import ExplicitPreferenceService

LOGGER = logging.getLogger(__name__)

MESSAGES = {
    SupportedLanguage.RUSSIAN: {
        "empty": "Расскажите, какие новости вам интересны. Например: /specify Новости из Кирова",
        "processing": "Обрабатываю ваше предпочтение...",
        "invalid": "Я не смог преобразовать это в безопасное изменение предпочтений.",
        "failed": "Обновление предпочтений не удалось. Попробуйте позже.",
        "applied": "Ваше явное предпочтение сохранено.",
        "no_change": "Ваши текущие предпочтения уже охватывают этот запрос.",
        "stale_retry": "Ваш профиль изменился во время обработки, поэтому я повторяю попытку.",
        "length_exceeded": "Пожалуйста, держите запросы /specify в пределах {max_length} символов.",
    },
    SupportedLanguage.ENGLISH: {
        "empty": "Tell me what news you want, for example: /specify News from Kirov",
        "processing": "Interpreting your explicit preference...",
        "invalid": "I couldn't convert that into a safe preference change.",
        "failed": "Preference update failed. Please try again soon.",
        "applied": "Saved your explicit preference.",
        "no_change": "Your current preferences already cover this request.",
        "stale_retry": "Your profile changed while I was working, so I'm retrying once.",
        "length_exceeded": "Please keep /specify requests within {max_length} characters.",
    },
    SupportedLanguage.SPANISH: {
        "empty": "Cuéntame qué noticias te interesan, por ejemplo: /specify Noticias de Kírov",
        "processing": "Interpretando tu preferencia explícita...",
        "invalid": "No pude convertir eso en un cambio de preferencia seguro.",
        "failed": "La actualización de preferencias falló. Inténtalo de nuevo más tarde.",
        "applied": "Tu preferencia explícita se ha guardado.",
        "no_change": "Tus preferencias actuales ya cubren esta solicitud.",
        "stale_retry": "Tu perfil cambió mientras estaba trabajando, así que estoy reintentando.",
        "length_exceeded": "Por favor, mantén las solicitudes /specify dentro de {max_length} caracteres.",
    },
}


class SpecifyTelegramAdapter:
    def __init__(
        self,
        service: ExplicitPreferenceService,
        language_service: UserLanguageService,
        *,
        max_text_length: int = 1000,
    ) -> None:
        self._service = service
        self._language_service = language_service
        self._max_text_length = max_text_length

    async def command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        user = update.effective_user
        message = update.message
        if user is None or message is None:
            LOGGER.warning(
                "specify_command_missing_user_or_message",
                extra={"update_id": getattr(update, "update_id", None)},
            )
            return

        language = await self._language_service.get(user.id, user.language_code)
        messages = MESSAGES[language]

        statement = self._extract_statement(message.text)
        if not statement:
            LOGGER.warning(
                "specify_command_missing_statement",
                extra={
                    "update_id": update.update_id,
                    "telegram_user_id": user.id,
                },
            )
            await message.reply_text(messages["empty"])
            return
        if len(statement) > self._max_text_length:
            LOGGER.warning(
                "specify_command_too_long",
                extra={
                    "update_id": update.update_id,
                    "telegram_user_id": user.id,
                    "length": len(statement),
                },
            )
            await message.reply_text(
                messages["length_exceeded"].format(max_length=self._max_text_length)
            )
            return

        await message.reply_text(messages["processing"])
        state = await self._service.specify(
            user.id,
            update.update_id,
            statement,
            user.language_code,
        )
        if state.kind is SpecifyStateKind.PROCESSING:
            return
        await self._render_message(message.reply_text, state, language)

    @staticmethod
    async def _render_message(
        reply,
        state: SpecifyState,
        language: SupportedLanguage = SupportedLanguage.ENGLISH,
    ) -> None:
        messages = MESSAGES[language]
        state_messages = {
            SpecifyStateKind.PROCESSING: messages["processing"],
            SpecifyStateKind.APPLIED: state.message or messages["applied"],
            SpecifyStateKind.NO_CHANGE: state.message or messages["no_change"],
            SpecifyStateKind.INVALID: state.message or messages["invalid"],
            SpecifyStateKind.STALE_RETRY: state.message or messages["stale_retry"],
            SpecifyStateKind.FAILED: state.message or messages["failed"],
        }
        await reply(state_messages[state.kind])

    @staticmethod
    def _extract_statement(text: str | None) -> str:
        if not text:
            return ""
        parts = text.split(maxsplit=1)
        if len(parts) == 1:
            return ""
        return parts[1].strip()
