from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from telegram.error import BadRequest

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
    query.delete_message = AsyncMock()
    status_message = Mock(edit_text=AsyncMock())
    query.message = Mock(chat=Mock(send_message=AsyncMock(return_value=status_message)))
    update = Mock(
        callback_query=query,
        effective_user=Mock(id=123, language_code="en"),
    )
    await adapter.callback(update, Mock())
    query.answer.assert_awaited_once_with()
    status_message.edit_text.assert_awaited_once()


async def test_callback_replaces_question_with_processing_before_completion() -> None:
    service = Mock()
    service.answer = AsyncMock(
        return_value=TuneState(TuneStateKind.COMPLETED, questionnaire_id=None)
    )
    adapter = _adapter(service)
    status_message = Mock(edit_text=AsyncMock())
    chat = Mock(send_message=AsyncMock(return_value=status_message))
    query = Mock(data=f"{CALLBACK_PREFIX}opaque", message=Mock(chat=chat))
    query.answer = AsyncMock()
    query.delete_message = AsyncMock()
    update = Mock(
        callback_query=query,
        effective_user=Mock(id=123, language_code="en"),
    )

    await adapter.callback(update, Mock())

    query.delete_message.assert_awaited_once_with()
    chat.send_message.assert_awaited_once_with("Updating your preferences...")
    status_message.edit_text.assert_awaited_once_with(
        "Your news preferences have been updated."
    )


async def test_expired_callback_acknowledgement_does_not_discard_answer() -> None:
    service = Mock(
        answer=AsyncMock(
            return_value=TuneState(TuneStateKind.COMPLETED, questionnaire_id=None)
        )
    )
    adapter = _adapter(service)
    status_message = Mock(edit_text=AsyncMock())
    chat = Mock(send_message=AsyncMock(return_value=status_message))
    query = Mock(data=f"{CALLBACK_PREFIX}opaque", message=Mock(chat=chat))
    query.answer = AsyncMock(
        side_effect=BadRequest(
            "Query is too old and response timeout expired or query id is invalid"
        )
    )
    query.delete_message = AsyncMock()
    update = Mock(
        callback_query=query,
        effective_user=Mock(id=123, language_code="en"),
    )

    await adapter.callback(update, Mock())

    service.answer.assert_awaited_once_with(123, "opaque")
    status_message.edit_text.assert_awaited_once_with(
        "Your news preferences have been updated."
    )


async def test_unrelated_callback_bad_request_is_not_hidden() -> None:
    service = Mock(answer=AsyncMock())
    adapter = _adapter(service)
    query = Mock(data=f"{CALLBACK_PREFIX}opaque")
    query.answer = AsyncMock(side_effect=BadRequest("Message is not modified"))
    update = Mock(
        callback_query=query,
        effective_user=Mock(id=123, language_code="en"),
    )

    with pytest.raises(BadRequest, match="Message is not modified"):
        await adapter.callback(update, Mock())

    service.answer.assert_not_awaited()


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
