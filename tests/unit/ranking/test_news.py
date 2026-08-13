from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from anxious_news_bot.ranking.domain import (
    DeliveryArticle,
    EvaluationStatus,
    SelectionOutcome,
    SelectionReason,
)
from anxious_news_bot.ranking.services.news import PersonalNewsService
from tests.fixtures.ranking import (
    FixedClock,
    StaticRankingConfigurationProvider,
    ranking_record,
)


async def test_evaluates_candidates_ranks_and_returns_selected_articles() -> None:
    user_id = uuid4()
    article_ids = (uuid4(), uuid4())
    repository = SimpleNamespace()
    repository.resolve_user_id = _async_result(user_id)
    repository.prepare_delivery_candidates = _async_result(article_ids)
    repository.has_active_nonzero_preferences = _async_result(True)
    repository.load_delivery_articles = _async_result(
        tuple(
            DeliveryArticle(
                article_id=article_id,
                title=f"Article {index}",
                summary=None,
                canonical_url=f"https://example.com/{index}",
                source_name="Example",
                published_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
            for index, article_id in enumerate(article_ids, start=1)
        )
    )
    evaluator = SimpleNamespace(
        evaluate=_async_result(SimpleNamespace(status=EvaluationStatus.COMPLETE))
    )
    records = tuple(
        ranking_record(
            article_id=article_id,
            final_score=f"0.{9 - index}0000000",
            selection=SelectionOutcome(
                selected=True,
                reason=SelectionReason.SELECTED,
                position=index,
                diversity_pass=1,
            ),
        )
        for index, article_id in enumerate(article_ids, start=1)
    )
    ranker = SimpleNamespace(rank=_async_result(SimpleNamespace(records=records)))

    result = await PersonalNewsService(
        repository,
        evaluator,
        ranker,
        StaticRankingConfigurationProvider(),
        FixedClock(),
        candidate_limit=10,
    ).top(123, "request-1", count=10)

    assert [item.article.article_id for item in result] == list(article_ids)
    assert [item.position for item in result] == [1, 2]
    assert all(isinstance(item.score, Decimal) for item in result)
    assert evaluator.evaluate.call_count == 2
    ranker.rank.assert_awaited_once()


def _async_result(value):
    from unittest.mock import AsyncMock

    return AsyncMock(return_value=value)
