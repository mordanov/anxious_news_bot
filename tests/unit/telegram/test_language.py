from __future__ import annotations

from unittest.mock import AsyncMock, Mock

from anxious_news_bot.preferences.domain import SupportedLanguage
from anxious_news_bot.telegram.language import (
    CALLBACK_PREFIX,
    LanguageTelegramAdapter,
)


async def test_language_command_lists_supported_languages() -> None:
    service = Mock()
    service.get = AsyncMock(return_value=SupportedLanguage.ENGLISH)
    reply = AsyncMock()
    update = Mock(
        effective_user=Mock(id=123, language_code="en"),
        message=Mock(reply_text=reply),
    )

    await LanguageTelegramAdapter(service).command(update, Mock())

    keyboard = reply.await_args.kwargs["reply_markup"].inline_keyboard
    assert [row[0].text for row in keyboard] == ["Русский", "English", "Español"]
    assert [row[0].callback_data for row in keyboard] == [
        f"{CALLBACK_PREFIX}ru",
        f"{CALLBACK_PREFIX}en",
        f"{CALLBACK_PREFIX}es",
    ]


async def test_language_callback_persists_selection() -> None:
    service = Mock()
    service.set = AsyncMock(return_value=SupportedLanguage.RUSSIAN)
    query = Mock(data=f"{CALLBACK_PREFIX}ru")
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = Mock(callback_query=query, effective_user=Mock(id=123))

    await LanguageTelegramAdapter(service).callback(update, Mock())

    service.set.assert_awaited_once_with(123, "ru")
    query.edit_message_text.assert_awaited_once()
