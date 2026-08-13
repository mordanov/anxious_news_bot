from unittest.mock import AsyncMock

from anxious_news_bot.app import START_MESSAGE, start


async def test_start_replies_with_readiness_message() -> None:
    message = AsyncMock()
    update = AsyncMock(message=message)

    await start(update, AsyncMock())

    message.reply_text.assert_awaited_once_with(START_MESSAGE)


async def test_start_without_message_does_not_reply() -> None:
    update = AsyncMock()
    update.message = None

    await start(update, AsyncMock())
