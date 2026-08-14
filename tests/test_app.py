from unittest.mock import AsyncMock

from anxious_news_bot.app import START_MESSAGE, build_application, start
from anxious_news_bot.config import Settings


async def test_start_replies_with_readiness_message() -> None:
    message = AsyncMock()
    update = AsyncMock(message=message)

    await start(update, AsyncMock())

    message.reply_text.assert_awaited_once_with(START_MESSAGE)


async def test_start_without_message_does_not_reply() -> None:
    update = AsyncMock()
    update.message = None

    await start(update, AsyncMock())


def test_build_application_registers_count_and_digest_services() -> None:
    application = build_application(Settings(telegram_bot_token="123456:ABCDEF"))

    commands = {
        command
        for handler in application.handlers[0]
        for command in (getattr(handler, "commands", ()) or ())
    }
    assert {"start", "language", "news", "tune", "specify", "count"} <= commands
    assert "digest_repository" in application.bot_data
    assert "digest_execution_service" in application.bot_data
    assert "digest_configuration_service" in application.bot_data
