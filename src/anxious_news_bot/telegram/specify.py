from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from anxious_news_bot.preferences.domain import SpecifyState, SpecifyStateKind
from anxious_news_bot.preferences.services.specify import ExplicitPreferenceService

LOGGER = logging.getLogger(__name__)
EMPTY_MESSAGE = "Tell me what news you want, for example: /specify News from Kirov"
PROCESSING_MESSAGE = "Interpreting your explicit preference..."
INVALID_MESSAGE = "I couldn't convert that into a safe preference change."
FAILED_MESSAGE = "Preference update failed. Please try again soon."


class SpecifyTelegramAdapter:
    def __init__(
        self,
        service: ExplicitPreferenceService,
        *,
        max_text_length: int = 1000,
    ) -> None:
        self._service = service
        self._max_text_length = max_text_length

    async def command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if update.effective_user is None or update.message is None:
            LOGGER.warning(
                "specify_command_missing_user_or_message",
                extra={"update_id": getattr(update, "update_id", None)},
            )
            return
        statement = self._extract_statement(update.message.text)
        if not statement:
            LOGGER.warning(
                "specify_command_missing_statement",
                extra={
                    "update_id": update.update_id,
                    "telegram_user_id": update.effective_user.id,
                },
            )
            await update.message.reply_text(EMPTY_MESSAGE)
            return
        if len(statement) > self._max_text_length:
            LOGGER.warning(
                "specify_command_too_long",
                extra={
                    "update_id": update.update_id,
                    "telegram_user_id": update.effective_user.id,
                    "length": len(statement),
                },
            )
            await update.message.reply_text(
                f"Please keep /specify requests within {self._max_text_length} characters."
            )
            return

        await update.message.reply_text(PROCESSING_MESSAGE)
        state = await self._service.specify(
            update.effective_user.id,
            update.update_id,
            statement,
            update.effective_user.language_code,
        )
        if state.kind is SpecifyStateKind.PROCESSING:
            return
        await self._render_message(update.message.reply_text, state)

    @staticmethod
    async def _render_message(reply, state: SpecifyState) -> None:
        messages = {
            SpecifyStateKind.PROCESSING: PROCESSING_MESSAGE,
            SpecifyStateKind.APPLIED: state.message
            or "Saved your explicit preference.",
            SpecifyStateKind.NO_CHANGE: (
                state.message or "Your current preferences already cover this request."
            ),
            SpecifyStateKind.INVALID: state.message or INVALID_MESSAGE,
            SpecifyStateKind.STALE_RETRY: (
                state.message
                or "Your profile changed while I was working, so I'm retrying once."
            ),
            SpecifyStateKind.FAILED: state.message or FAILED_MESSAGE,
        }
        await reply(messages[state.kind])

    @staticmethod
    def _extract_statement(text: str | None) -> str:
        if not text:
            return ""
        parts = text.split(maxsplit=1)
        if len(parts) == 1:
            return ""
        return parts[1].strip()
