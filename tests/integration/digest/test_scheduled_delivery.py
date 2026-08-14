from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from anxious_news_bot.digest.domain import ExecutionStatus, RetrySchedule
from anxious_news_bot.digest.infrastructure.models import (
    DigestConfiguration,
    DigestDeliveryHistory,
    DigestExecution,
    DigestItem,
)
from anxious_news_bot.digest.services.execute import DigestExecutionService
from tests.fixtures.digest import FakeComposer, FakeDelivery, FixedClock

NOW = datetime(2026, 1, 15, 9, 1, tzinfo=UTC)


class SelectionByUser:
    def __init__(self, values):
        self.values = values
        self.calls = []

    async def select_for_user(
        self,
        user_id,
        request_id,
        count,
        candidate_limit,
        candidate_filter,
    ):
        self.calls.append(
            (user_id, request_id, count, candidate_limit, candidate_filter)
        )
        return self.values[user_id]


def _selection(graph):
    return {
        "ranking_run_id": graph.ranking_run_id,
        "profile_revision": 0,
        "items": [
            {
                "position": index,
                "article_id": article.article_id,
                "article_analysis_id": article.analysis_id,
                "event_group_id": article.event_group_id,
                "ranking_run_id": graph.ranking_run_id,
                "title": article.title,
                "summary": article.summary,
                "normalized_text": article.normalized_text,
                "source_name": article.source_name,
                "published_at": article.published_at,
                "canonical_url": article.canonical_url,
                "score": Decimal("0.80000000"),
            }
            for index, article in enumerate(graph.articles, start=1)
        ],
    }


def _service(repository, selector, *, composer=None, delivery=None):
    return DigestExecutionService(
        repository,
        repository,
        selector,
        composer or FakeComposer(),
        delivery or FakeDelivery(),
        None,
        FixedClock(NOW),
        retry_schedule=RetrySchedule(60, 900, 3),
        user_concurrency=5,
        candidate_limit=100,
    )


async def test_due_cycle_delivers_three_without_filler_for_count_ten(
    digest_database,
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
) -> None:
    due_user = await provision_digest_user(
        telegram_user_id=61_001,
        language_hint="es",
    )
    await enable_digest_user(
        due_user.application_user.id,
        due_at=NOW - timedelta(minutes=1),
        digest_count=10,
    )
    disabled_user = await provision_digest_user(telegram_user_id=61_002)
    not_due_user = await provision_digest_user(telegram_user_id=61_003)
    await enable_digest_user(
        not_due_user.application_user.id,
        due_at=NOW + timedelta(hours=1),
    )
    graph = await seed_digest_graph(due_user.application_user.id, count=3)
    delivery = FakeDelivery()
    composer = FakeComposer()
    service = _service(
        digest_repository,
        SelectionByUser({due_user.application_user.id: _selection(graph)}),
        composer=composer,
        delivery=delivery,
    )

    result = await service.run_due_cycle(NOW)

    assert result.claimed_count == 1
    assert result.completed_count == 1
    assert result.failed_count == 0
    assert len(delivery.sent_parts) == 1
    assert composer.calls[0][1] == "es"
    async with digest_database.session() as session:
        executions = (await session.execute(select(DigestExecution))).scalars().all()
        item_count = await session.scalar(select(func.count()).select_from(DigestItem))
        history_count = await session.scalar(
            select(func.count()).select_from(DigestDeliveryHistory)
        )
        due_config = await session.get(
            DigestConfiguration,
            due_user.application_user.id,
        )
        disabled_config = await session.get(
            DigestConfiguration,
            disabled_user.application_user.id,
        )
    assert len(executions) == 1
    assert executions[0].status is ExecutionStatus.COMPLETED
    assert executions[0].digest_count == 10
    assert executions[0].selected_count == 3
    assert executions[0].language_code == "es"
    assert item_count == history_count == 3
    assert due_config.last_success_execution_id == executions[0].id
    assert disabled_config.enabled is False


async def test_zero_suitable_items_completes_without_delivery(
    digest_database,
    digest_repository,
    provision_digest_user,
    enable_digest_user,
) -> None:
    user = await provision_digest_user(telegram_user_id=61_004)
    await enable_digest_user(
        user.application_user.id,
        due_at=NOW - timedelta(minutes=1),
    )
    delivery = FakeDelivery()
    service = _service(
        digest_repository,
        SelectionByUser(
            {
                user.application_user.id: {
                    "ranking_run_id": None,
                    "profile_revision": 0,
                    "items": [],
                }
            }
        ),
        delivery=delivery,
    )

    result = await service.run_due_cycle(NOW)

    assert result.completed_count == 1
    assert delivery.sent_parts == []
    async with digest_database.session() as session:
        execution = (await session.execute(select(DigestExecution))).scalar_one()
    assert execution.status is ExecutionStatus.COMPLETED
    assert execution.selected_count == 0
