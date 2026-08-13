from __future__ import annotations

from unittest.mock import AsyncMock, Mock

from anxious_news_bot.preferences.domain import (
    SupportedLanguage,
    TuneOption,
    TuneState,
    TuneStateKind,
)
from anxious_news_bot.preferences.errors import AnswerRejected
from anxious_news_bot.telegram.tune import CALLBACK_PREFIX, TuneTelegramAdapter


def _adapter(service) -> TuneTelegramAdapter:
    language_service = Mock()
    language_service.get = AsyncMock(return_value=SupportedLanguage.ENGLISH)
    return TuneTelegramAdapter(service, language_service)


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
    adapter = _adapter(service)
    query = Mock(data=f"{CALLBACK_PREFIX}opaque")
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = Mock(
        callback_query=query,
        effective_user=Mock(id=123, language_code="en"),
    )
    await adapter.callback(update, Mock())
    query.answer.assert_awaited_once_with()
    query.edit_message_text.assert_awaited_once()


async def test_command_without_user_or_message_is_ignored() -> None:
    service = Mock()
    service.start_or_resume = AsyncMock()
    await _adapter(service).command(Mock(effective_user=None, message=None), Mock())
    service.start_or_resume.assert_not_awaited()


async def test_question_heading_uses_selected_language() -> None:
    reply = AsyncMock()
    state = TuneState(
        TuneStateKind.QUESTION,
        ordinal=1,
        question="¿Qué temas prefieres?",
        options=tuple(TuneOption(f"Opción {i}", f"token{i}") for i in range(4)),
    )
    await TuneTelegramAdapter._render_message(
        reply,
        state,
        SupportedLanguage.SPANISH,
    )
    assert reply.await_args.args[0].startswith("Pregunta 1/10")
