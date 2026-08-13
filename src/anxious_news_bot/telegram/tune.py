from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from anxious_news_bot.preferences.domain import TuneState, TuneStateKind
from anxious_news_bot.preferences.errors import AnswerRejected
from anxious_news_bot.preferences.services.tune import PreferenceTuningService

LOGGER = logging.getLogger(__name__)
CALLBACK_PREFIX = "t:"


class TuneTelegramAdapter:
    def __init__(self, service: PreferenceTuningService) -> None:
        self._service = service

    async def command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if update.effective_user is None or update.message is None:
            LOGGER.warning("tune_command_missing_user_or_message")
            return
        state = await self._service.start_or_resume(
            update.effective_user.id,
            update.effective_user.language_code,
        )
        await self._render_message(update.message.reply_text, state)

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
            await query.edit_message_text("This preference option is invalid.")
            return
        try:
            state = await self._service.answer(
                user.id, data.removeprefix(CALLBACK_PREFIX)
            )
        except AnswerRejected:
            await query.edit_message_text(
                "This option is stale. Send /tune to resume your questionnaire."
            )
            return
        await self._render_message(query.edit_message_text, state)

    @staticmethod
    async def _render_message(reply, state: TuneState) -> None:
        if state.kind is TuneStateKind.QUESTION:
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
                f"Question {state.ordinal}/10\n\n{state.question}",
                reply_markup=keyboard,
            )
            return
        messages = {
            TuneStateKind.GENERATING: "Creating your preference questionnaire...",
            TuneStateKind.PROCESSING: "Updating your preferences...",
            TuneStateKind.COMPLETED: "Your news preferences have been updated.",
            TuneStateKind.FAILED: (
                state.message or "Preference tuning failed. Send /tune to try again."
            ),
        }
        await reply(messages[state.kind])
