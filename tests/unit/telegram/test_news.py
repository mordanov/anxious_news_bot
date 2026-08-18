from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from sqlalchemy.exc import OperationalError

from anxious_news_bot.preferences.domain import SupportedLanguage
from anxious_news_bot.ranking.domain import DeliveryArticle, RankedNewsItem
from anxious_news_bot.telegram.news import NewsTelegramAdapter
from anxious_news_bot.telegram.news_translation import NewsTranslationError


async def test_news_command_renders_ranked_articles() -> None:
    item = RankedNewsItem(
        article=DeliveryArticle(
            article_id=uuid4(),
            title="Important update",
            summary="Summary",
            canonical_url="https://example.com/story",
            source_name="Example News",
            published_at=datetime(2026, 8, 13, 10, 30, tzinfo=UTC),
        ),
        position=1,
        score=Decimal("0.90000000"),
    )
    service = Mock(top=AsyncMock(return_value=(item,)))
    language_service = Mock(get=AsyncMock(return_value=SupportedLanguage.ENGLISH))
    translator = Mock(
        translate=AsyncMock(return_value=("Important translated update",))
    )
    configuration_service = Mock(
        get_current=AsyncMock(return_value=Mock(digest_count=7))
    )
    timezone_service = Mock(get=AsyncMock(return_value=0))
    status_message = Mock(edit_text=AsyncMock())
    reply = AsyncMock(return_value=status_message)
    update = Mock(
        update_id=99,
        effective_user=Mock(id=123, language_code="en"),
        message=Mock(reply_text=reply),
    )

    await NewsTelegramAdapter(
        service,
        language_service,
        translator,
        configuration_service,
        timezone_service,
    ).command(update, Mock())

    service.top.assert_awaited_once_with(
        123,
        "telegram-news:99",
        count=7,
    )
    rendered = status_message.edit_text.await_args.args[0]
    translator.translate.assert_awaited_once_with(
        ("Important update",),
        SupportedLanguage.ENGLISH,
    )
    assert "1. Important translated update" in rendered
    assert "https://example.com/story" in rendered
    assert reply.await_args_list[1].args == (
        "Only 1 of 7 news items were available. "
        "Run /tune to review or update your preferences.",
    )


async def test_news_command_reports_translation_failure() -> None:
    item = RankedNewsItem(
        article=DeliveryArticle(
            article_id=uuid4(),
            title="Important update",
            summary=None,
            canonical_url="https://example.com/story",
            source_name="Example News",
            published_at=datetime(2026, 8, 13, tzinfo=UTC),
        ),
        position=1,
        score=Decimal("0.90000000"),
    )
    service = Mock(top=AsyncMock(return_value=(item,)))
    language_service = Mock(get=AsyncMock(return_value=SupportedLanguage.SPANISH))
    translator = Mock(translate=AsyncMock(side_effect=NewsTranslationError("failed")))
    configuration_service = Mock(
        get_current=AsyncMock(return_value=Mock(digest_count=10))
    )
    timezone_service = Mock(get=AsyncMock(return_value=0))
    status_message = Mock(edit_text=AsyncMock())
    update = Mock(
        update_id=100,
        effective_user=Mock(id=123, language_code="es"),
        message=Mock(reply_text=AsyncMock(return_value=status_message)),
    )

    await NewsTelegramAdapter(
        service,
        language_service,
        translator,
        configuration_service,
        timezone_service,
    ).command(update, Mock())

    status_message.edit_text.assert_awaited_once_with(
        "No pude preparar tus noticias. Inténtalo de nuevo más tarde."
    )


async def test_news_command_reports_configuration_failure() -> None:
    service = Mock(top=AsyncMock())
    language_service = Mock(get=AsyncMock(return_value=SupportedLanguage.ENGLISH))
    translator = Mock()
    configuration_service = Mock(
        get_current=AsyncMock(
            side_effect=OperationalError("lookup", {}, RuntimeError("database"))
        )
    )
    timezone_service = Mock(get=AsyncMock(return_value=0))
    status_message = Mock(edit_text=AsyncMock())
    update = Mock(
        update_id=101,
        effective_user=Mock(id=123, language_code="en"),
        message=Mock(
            reply_text=AsyncMock(return_value=status_message),
        ),
    )

    await NewsTelegramAdapter(
        service,
        language_service,
        translator,
        configuration_service,
        timezone_service,
    ).command(update, Mock())

    service.top.assert_not_awaited()
    status_message.edit_text.assert_awaited_once_with(
        "I couldn't prepare your news selection. Please try again later."
    )


def test_news_chunks_stay_within_telegram_limit() -> None:
    items = tuple(
        RankedNewsItem(
            article=DeliveryArticle(
                article_id=uuid4(),
                title="A" * 240,
                summary=None,
                canonical_url=f"https://example.com/{index}/" + "x" * 900,
                source_name="Example",
                published_at=datetime(2026, 8, 13, tzinfo=UTC),
            ),
            position=index,
            score=Decimal("0.50000000"),
        )
        for index in range(1, 11)
    )
    chunks = NewsTelegramAdapter._chunks("Top news", items)
    assert len(chunks) > 1
    assert all(len(chunk) <= 3900 for chunk in chunks)
