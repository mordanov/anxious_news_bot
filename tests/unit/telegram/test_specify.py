from __future__ import annotations

import logging
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from anxious_news_bot.preferences.domain import (
    SpecifyState,
    SpecifyStateKind,
    SupportedLanguage,
)
from anxious_news_bot.telegram.specify import SpecifyTelegramAdapter


async def test_extracts_text_update_identity_and_language_before_calling_service() -> (
    None
):
    service = Mock()
    service.specify = AsyncMock(
        return_value=SpecifyState(
            SpecifyStateKind.APPLIED,
            request_id=uuid4(),
            message="Saved your explicit preference for Kirov city news.",
        )
    )
    language_service = AsyncMock()
    language_service.get = AsyncMock(return_value=SupportedLanguage.RUSSIAN)
    adapter = SpecifyTelegramAdapter(service, language_service, max_text_length=1000)
    message = Mock(text="/specify   More Kirov city news   ")
    message.reply_text = AsyncMock()
    update = Mock(
        update_id=77,
        effective_user=Mock(id=123, language_code="ru"),
        message=message,
    )

    await adapter.command(update, Mock())

    service.specify.assert_awaited_once_with(123, 77, "More Kirov city news", "ru")
    assert message.reply_text.await_args_list[0].args == (
        "Обрабатываю ваше предпочтение...",
    )
    assert message.reply_text.await_args_list[-1].args == (
        "Saved your explicit preference for Kirov city news.",
    )


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (
            SpecifyState(SpecifyStateKind.PROCESSING, request_id=uuid4()),
            "Interpreting your explicit preference...",
        ),
        (
            SpecifyState(
                SpecifyStateKind.APPLIED,
                request_id=uuid4(),
                message="Saved your explicit preference for Kirov city news.",
            ),
            "Saved your explicit preference for Kirov city news.",
        ),
        (
            SpecifyState(
                SpecifyStateKind.NO_CHANGE,
                request_id=uuid4(),
                message="Your current preferences already cover Kirov city news.",
            ),
            "Your current preferences already cover Kirov city news.",
        ),
        (
            SpecifyState(
                SpecifyStateKind.INVALID,
                request_id=uuid4(),
                message="I couldn't convert that into a safe preference change.",
            ),
            "I couldn't convert that into a safe preference change.",
        ),
        (
            SpecifyState(
                SpecifyStateKind.STALE_RETRY,
                request_id=uuid4(),
                message="Your profile changed while I was working, so I'm retrying once.",
            ),
            "Your profile changed while I was working, so I'm retrying once.",
        ),
        (
            SpecifyState(
                SpecifyStateKind.FAILED,
                request_id=uuid4(),
                message="Preference update failed. Please try again soon.",
            ),
            "Preference update failed. Please try again soon.",
        ),
    ],
)
async def test_renders_all_specify_states(state: SpecifyState, expected: str) -> None:
    reply = AsyncMock()
    await SpecifyTelegramAdapter._render_message(
        reply, state, SupportedLanguage.ENGLISH
    )
    reply.assert_awaited_once_with(expected)


async def test_missing_user_or_message_is_ignored() -> None:
    service = Mock()
    service.specify = AsyncMock()
    language_service = AsyncMock()
    language_service.get = AsyncMock(return_value=SupportedLanguage.ENGLISH)
    await SpecifyTelegramAdapter(service, language_service).command(
        Mock(update_id=77, effective_user=None, message=None),
        Mock(),
    )
    service.specify.assert_not_awaited()


async def test_blank_and_over_limit_text_return_controlled_messages() -> None:
    service = Mock()
    service.specify = AsyncMock()
    language_service = AsyncMock()
    language_service.get = AsyncMock(return_value=SupportedLanguage.ENGLISH)
    adapter = SpecifyTelegramAdapter(service, language_service, max_text_length=10)

    blank_message = Mock(text="/specify    ")
    blank_message.reply_text = AsyncMock()
    await adapter.command(
        Mock(
            update_id=1,
            effective_user=Mock(id=123, language_code="en"),
            message=blank_message,
        ),
        Mock(),
    )
    blank_message.reply_text.assert_awaited_once_with(
        "Tell me what news you want, for example: /specify News from Kirov"
    )

    long_message = Mock(text="/specify " + "x" * 11)
    long_message.reply_text = AsyncMock()
    await adapter.command(
        Mock(
            update_id=2,
            effective_user=Mock(id=123, language_code="en"),
            message=long_message,
        ),
        Mock(),
    )
    long_message.reply_text.assert_awaited_once_with(
        "Please keep /specify requests within 10 characters."
    )
    service.specify.assert_not_awaited()


async def test_logs_exclude_raw_statement_text(caplog) -> None:
    logger = logging.getLogger("anxious_news_bot.telegram.specify")
    logger.disabled = False
    caplog.set_level(logging.WARNING, logger=logger.name)

    service = Mock()
    service.specify = AsyncMock()
    language_service = AsyncMock()
    language_service.get = AsyncMock(return_value=SupportedLanguage.ENGLISH)
    adapter = SpecifyTelegramAdapter(service, language_service, max_text_length=10)
    raw_text = "/specify Very sensitive Kirov statement"
    message = Mock(text=raw_text)
    message.reply_text = AsyncMock()

    await adapter.command(
        Mock(
            update_id=5,
            effective_user=Mock(id=123, language_code="en"),
            message=message,
        ),
        Mock(),
    )

    assert raw_text not in caplog.text
