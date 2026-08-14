"""Telegram /count command tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from anxious_news_bot.preferences.domain import SupportedLanguage
from anxious_news_bot.telegram.count import (
    GUIDANCE_MESSAGES,
    CountTelegramAdapter,
)


@pytest.fixture
def adapter():
    config_service = AsyncMock()
    language_service = AsyncMock()
    language_service.get = AsyncMock(return_value=SupportedLanguage.ENGLISH)
    return CountTelegramAdapter(config_service, language_service)


@pytest.fixture
def update():
    u = MagicMock()
    u.effective_user.id = 123
    u.effective_user.language_code = "en"
    u.message.text = "/count 10"
    u.message.reply_text = AsyncMock()
    return u


class TestCountCommand:
    @pytest.mark.asyncio
    async def test_valid_count_5(self, adapter, update):
        update.message.text = "/count 5"
        await adapter.command(update, MagicMock())
        update.message.reply_text.assert_awaited_once_with("Digest size: 5.")

    @pytest.mark.asyncio
    async def test_valid_count_20(self, adapter, update):
        update.message.text = "/count 20"
        await adapter.command(update, MagicMock())
        update.message.reply_text.assert_awaited_once_with("Digest size: 20.")

    @pytest.mark.asyncio
    async def test_below_range(self, adapter, update):
        update.message.text = "/count 4"
        await adapter.command(update, MagicMock())
        update.message.reply_text.assert_awaited_once_with(
            GUIDANCE_MESSAGES[SupportedLanguage.ENGLISH]
        )

    @pytest.mark.asyncio
    async def test_above_range(self, adapter, update):
        update.message.text = "/count 21"
        await adapter.command(update, MagicMock())
        update.message.reply_text.assert_awaited_once_with(
            GUIDANCE_MESSAGES[SupportedLanguage.ENGLISH]
        )

    @pytest.mark.asyncio
    async def test_non_numeric(self, adapter, update):
        update.message.text = "/count abc"
        await adapter.command(update, MagicMock())
        update.message.reply_text.assert_awaited_once_with(
            GUIDANCE_MESSAGES[SupportedLanguage.ENGLISH]
        )

    @pytest.mark.asyncio
    async def test_missing_argument(self, adapter, update):
        update.message.text = "/count"
        await adapter.command(update, MagicMock())
        update.message.reply_text.assert_awaited_once_with(
            GUIDANCE_MESSAGES[SupportedLanguage.ENGLISH]
        )

    @pytest.mark.asyncio
    async def test_russian_confirmation(self, adapter, update):
        adapter._language_service.get = AsyncMock(
            return_value=SupportedLanguage.RUSSIAN
        )
        update.message.text = "/count 10"
        await adapter.command(update, MagicMock())
        update.message.reply_text.assert_awaited_once_with("Размер дайджеста: 10.")

    @pytest.mark.asyncio
    async def test_spanish_confirmation(self, adapter, update):
        adapter._language_service.get = AsyncMock(
            return_value=SupportedLanguage.SPANISH
        )
        update.message.text = "/count 10"
        await adapter.command(update, MagicMock())
        update.message.reply_text.assert_awaited_once_with("Tamano del resumen: 10.")

    @pytest.mark.asyncio
    async def test_no_user(self, adapter):
        update = MagicMock()
        update.effective_user = None
        update.message = MagicMock()
        await adapter.command(update, MagicMock())
        # When user is None, message.reply_text is not called

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "text",
        ["/count 5 extra", "/count +5", "/count -5", "/count 5.0", "/count ５"],
    )
    async def test_requires_exactly_one_ascii_decimal_integer(
        self, adapter, update, text
    ):
        update.message.text = text

        await adapter.command(update, MagicMock())

        adapter._service.set_count.assert_not_awaited()
        update.message.reply_text.assert_awaited_once_with(
            GUIDANCE_MESSAGES[SupportedLanguage.ENGLISH]
        )

    @pytest.mark.asyncio
    async def test_invalid_input_never_calls_configuration_service(
        self, adapter, update
    ):
        update.message.text = "/count nope"

        await adapter.command(update, MagicMock())

        adapter._service.set_count.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_message_is_ignored(self, adapter):
        update = MagicMock()
        update.effective_user = MagicMock(id=1, language_code="en")
        update.message = None

        await adapter.command(update, MagicMock())

        adapter._service.set_count.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_persistence_failure_uses_localized_generic_message(
        self, adapter, update
    ):
        adapter._service.set_count.side_effect = RuntimeError("database unavailable")

        await adapter.command(update, MagicMock())

        update.message.reply_text.assert_awaited_once_with(
            "I couldn't prepare your news selection. Please try again later."
        )
