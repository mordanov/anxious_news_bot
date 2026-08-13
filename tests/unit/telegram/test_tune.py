from __future__ import annotations

from unittest.mock import AsyncMock, Mock

from anxious_news_bot.preferences.domain import (
    TuneOption,
    TuneState,
    TuneStateKind,
)
from anxious_news_bot.preferences.errors import AnswerRejected
from anxious_news_bot.telegram.tune import CALLBACK_PREFIX, TuneTelegramAdapter


async def test_question_renders_four_opaque_buttons() -> None:
    reply = AsyncMock()
    state = TuneState(
        TuneStateKind.QUESTION,
        ordinal=3,
        question="Which reporting depth do you prefer?",
        options=tuple(TuneOption(f"Option {i}", f"token{i}") for i in range(4)),
    )
    await TuneTelegramAdapter._render_message(reply, state)
    kwargs = reply.await_args.kwargs
    keyboard = kwargs["reply_markup"].inline_keyboard
    assert len(keyboard) == 4
    assert all(row[0].callback_data.startswith(CALLBACK_PREFIX) for row in keyboard)


async def test_callback_is_acknowledged_before_controlled_stale_response() -> None:
    service = Mock()
    service.answer = AsyncMock(side_effect=AnswerRejected("stale"))
    adapter = TuneTelegramAdapter(service)
    query = Mock(data=f"{CALLBACK_PREFIX}opaque")
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = Mock(callback_query=query, effective_user=Mock(id=123))
    await adapter.callback(update, Mock())
    query.answer.assert_awaited_once_with()
    query.edit_message_text.assert_awaited_once()


async def test_command_without_user_or_message_is_ignored() -> None:
    service = Mock()
    service.start_or_resume = AsyncMock()
    await TuneTelegramAdapter(service).command(
        Mock(effective_user=None, message=None), Mock()
    )
    service.start_or_resume.assert_not_awaited()
