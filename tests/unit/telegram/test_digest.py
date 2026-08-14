"""Telegram digest rendering tests."""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut

from anxious_news_bot.digest.domain import StructuredDigest, StructuredDigestItem
from anxious_news_bot.digest.errors import (
    AmbiguousDeliveryError,
    DefiniteTransientDeliveryError,
    PermanentDeliveryError,
)
from anxious_news_bot.telegram.digest import (
    MAX_MESSAGE_LENGTH,
    TelegramDigestDelivery,
    render_digest,
)


def _make_item(
    position: int, title_len: int = 20, summary_len: int = 50
) -> StructuredDigestItem:
    return StructuredDigestItem(
        position=position,
        article_id=uuid4(),
        article_analysis_id=uuid4(),
        event_group_id=None,
        ranking_run_id=uuid4(),
        title="T" * title_len,
        summary="S" * summary_len,
        source_name="Source",
        published_at=datetime(2026, 1, 14, tzinfo=UTC),
        canonical_url=f"https://example.com/{position}",
        score=Decimal("0.85000000"),
    )


class TestRenderDigest:
    def test_empty_digest_no_parts(self):
        digest = StructuredDigest(
            execution_id=uuid4(), user_id=uuid4(), language="en", items=()
        )
        parts = render_digest(digest, "1.0")
        assert parts == ()

    def test_single_item_one_part(self):
        items = (_make_item(1),)
        digest = StructuredDigest(
            execution_id=uuid4(), user_id=uuid4(), language="en", items=items
        )
        parts = render_digest(digest, "1.0")
        assert len(parts) == 1
        assert "Your news digest" in parts[0].content
        assert parts[0].first_item_position == 1
        assert parts[0].last_item_position == 1

    def test_localized_header_russian(self):
        items = (_make_item(1),)
        digest = StructuredDigest(
            execution_id=uuid4(), user_id=uuid4(), language="ru", items=items
        )
        parts = render_digest(digest, "1.0")
        assert "Ваш новостной дайджест" in parts[0].content

    def test_localized_header_spanish(self):
        items = (_make_item(1),)
        digest = StructuredDigest(
            execution_id=uuid4(), user_id=uuid4(), language="es", items=items
        )
        parts = render_digest(digest, "1.0")
        assert "Tu resumen de noticias" in parts[0].content

    def test_parts_respect_length_limit(self):
        # Create items that will exceed 3900 chars
        items = tuple(
            _make_item(i, title_len=100, summary_len=400) for i in range(1, 11)
        )
        digest = StructuredDigest(
            execution_id=uuid4(), user_id=uuid4(), language="en", items=items
        )
        parts = render_digest(digest, "1.0")
        for part in parts:
            assert len(part.content) <= MAX_MESSAGE_LENGTH

    def test_item_order_preserved(self):
        items = tuple(_make_item(i) for i in range(1, 4))
        digest = StructuredDigest(
            execution_id=uuid4(), user_id=uuid4(), language="en", items=items
        )
        parts = render_digest(digest, "1.0")
        content = "".join(p.content for p in parts)
        assert content.index("1.") < content.index("2.") < content.index("3.")

    def test_deterministic_hash(self):
        items = (_make_item(1),)
        digest = StructuredDigest(
            execution_id=uuid4(), user_id=uuid4(), language="en", items=items
        )
        parts1 = render_digest(digest, "1.0")
        parts2 = render_digest(digest, "1.0")
        assert parts1[0].content_hash == parts2[0].content_hash
        assert (
            parts1[0].content_hash
            == hashlib.sha256(parts1[0].content.encode()).hexdigest()
        )

    def test_url_preserved(self):
        items = (_make_item(1),)
        digest = StructuredDigest(
            execution_id=uuid4(), user_id=uuid4(), language="en", items=items
        )
        parts = render_digest(digest, "1.0")
        assert "https://example.com/1" in parts[0].content

    def test_date_in_output(self):
        items = (_make_item(1),)
        digest = StructuredDigest(
            execution_id=uuid4(), user_id=uuid4(), language="en", items=items
        )
        parts = render_digest(digest, "1.0")
        assert "2026-01-14" in parts[0].content

    def test_header_appears_only_in_first_part_and_ranges_do_not_overlap(self):
        items = tuple(
            _make_item(i, title_len=200, summary_len=500) for i in range(1, 21)
        )
        digest = StructuredDigest(
            execution_id=uuid4(), user_id=uuid4(), language="en", items=items
        )

        parts = render_digest(digest, "1.0")

        assert len(parts) > 1
        assert parts[0].content.startswith("Your news digest")
        assert all("Your news digest" not in part.content for part in parts[1:])
        assert parts[0].first_item_position == 1
        for previous, current in zip(parts, parts[1:], strict=False):
            assert current.first_item_position == previous.last_item_position + 1
        assert parts[-1].last_item_position == 20

    def test_normalizes_display_whitespace_without_changing_url(self):
        item = _make_item(1)
        item = StructuredDigestItem(
            position=item.position,
            article_id=item.article_id,
            article_analysis_id=item.article_analysis_id,
            event_group_id=None,
            ranking_run_id=item.ranking_run_id,
            title="Title\n with\tspaces",
            summary="Summary\n\nwith\tspaces",
            source_name="Source\nName",
            published_at=item.published_at,
            canonical_url="https://example.com/a%20b?x=1",
            score=item.score,
        )
        digest = StructuredDigest(
            execution_id=uuid4(), user_id=uuid4(), language="en", items=(item,)
        )

        content = render_digest(digest, "1.0")[0].content

        assert "Title with spaces" in content
        assert "Summary with spaces" in content
        assert "Source Name" in content
        assert "https://example.com/a%20b?x=1" in content


def _part():
    digest = StructuredDigest(
        execution_id=uuid4(),
        user_id=uuid4(),
        language="en",
        items=(_make_item(1),),
    )
    return render_digest(digest, "1.0")[0]


async def test_delivery_returns_provider_acknowledgement():
    accepted_at = datetime(2026, 1, 15, tzinfo=UTC)
    bot = AsyncMock()
    bot.send_message.return_value = SimpleNamespace(message_id=99, date=accepted_at)

    result = await TelegramDigestDelivery(bot).send(123, _part())

    assert result.provider_message_id == "99"
    assert result.accepted_at == accepted_at


@pytest.mark.parametrize("error", [BadRequest("bad"), Forbidden("blocked")])
async def test_delivery_classifies_permanent_rejections(error):
    bot = AsyncMock()
    bot.send_message.side_effect = error

    with pytest.raises(PermanentDeliveryError):
        await TelegramDigestDelivery(bot).send(123, _part())


async def test_delivery_classifies_rate_limit_as_definite_transient():
    bot = AsyncMock()
    bot.send_message.side_effect = RetryAfter(3)

    with pytest.raises(DefiniteTransientDeliveryError) as caught:
        await TelegramDigestDelivery(bot).send(123, _part())
    assert caught.value.code == "rate_limited"


@pytest.mark.parametrize(
    "error",
    [
        TimedOut("timed out"),
        httpx.ReadTimeout("read timed out"),
    ],
)
async def test_delivery_classifies_post_transmission_uncertainty(error):
    bot = AsyncMock()
    bot.send_message.side_effect = error

    with pytest.raises(AmbiguousDeliveryError):
        await TelegramDigestDelivery(bot).send(123, _part())


async def test_delivery_classifies_connect_failure_as_definite_transient():
    bot = AsyncMock()
    bot.send_message.side_effect = httpx.ConnectError("connect failed")

    with pytest.raises(DefiniteTransientDeliveryError):
        await TelegramDigestDelivery(bot).send(123, _part())
