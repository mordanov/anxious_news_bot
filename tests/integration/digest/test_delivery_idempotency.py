from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from anxious_news_bot.digest.domain import (
    AttemptPhase,
    DeliveryPartClaim,
    DeliveryPartStatus,
    ExecutionStatus,
    RenderedPart,
    StructuredDigestItem,
)
from anxious_news_bot.digest.errors import StaleAttemptError
from anxious_news_bot.digest.infrastructure.models import (
    DigestDeliveryHistory,
    DigestDeliveryPart,
)
from anxious_news_bot.telegram.digest import render_digest

NOW = datetime(2026, 1, 15, 9, 1, tzinfo=UTC)


async def _ready_digest(
    repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
    *,
    count: int = 2,
    event_group_id=None,
    prepare_parts: bool = True,
):
    user = await provision_digest_user(telegram_user_id=51_001)
    await enable_digest_user(
        user.application_user.id,
        due_at=NOW - timedelta(minutes=1),
        digest_count=max(5, count),
    )
    occurrence = (await repository.claim_due(NOW, 1))[0]
    attempt = await repository.claim_attempt(
        occurrence.execution_id,
        AttemptPhase.PREPARE.value,
        NOW,
    )
    graph = await seed_digest_graph(
        user.application_user.id,
        count=count,
        event_group_id=event_group_id,
    )
    await repository.record_selection(
        occurrence.execution_id,
        count,
        graph.ranking_run_id,
        0,
    )
    items = tuple(
        StructuredDigestItem(
            position=index,
            article_id=article.article_id,
            article_analysis_id=article.analysis_id,
            event_group_id=article.event_group_id,
            ranking_run_id=graph.ranking_run_id,
            title=article.title,
            summary=article.summary,
            source_name=article.source_name,
            published_at=article.published_at,
            canonical_url=article.canonical_url,
            score=Decimal("0.80000000"),
        )
        for index, article in enumerate(graph.articles, start=1)
    )
    digest = await repository.record_items(occurrence.execution_id, items, NOW)
    parts = render_digest(digest, "1.0")
    if prepare_parts:
        await repository.prepare_delivery_parts(occurrence.execution_id, parts)
    return user, occurrence, attempt, digest, parts


async def test_part_is_claimed_before_ack_and_ack_writes_history_atomically(
    digest_database,
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
) -> None:
    user, occurrence, _, _, parts = await _ready_digest(
        digest_repository,
        provision_digest_user,
        enable_digest_user,
        seed_digest_graph,
    )
    claim = await digest_repository.claim_delivery_part(
        occurrence.execution_id,
        1,
        NOW,
    )
    assert claim is not None
    async with digest_database.session() as session:
        persisted = await session.scalar(
            select(DigestDeliveryPart).where(
                DigestDeliveryPart.execution_id == occurrence.execution_id,
                DigestDeliveryPart.ordinal == 1,
            )
        )
    assert persisted.status is DeliveryPartStatus.SENDING

    acknowledged = await digest_repository.acknowledge_delivery_part(
        claim,
        "provider-1",
        NOW + timedelta(seconds=1),
    )

    assert acknowledged.status is DeliveryPartStatus.SENT
    assert (
        await digest_repository.claim_delivery_part(
            occurrence.execution_id,
            1,
            NOW + timedelta(seconds=2),
        )
        is None
    )
    async with digest_database.session() as session:
        history_count = await session.scalar(
            select(func.count())
            .select_from(DigestDeliveryHistory)
            .where(DigestDeliveryHistory.user_id == user.application_user.id)
        )
    assert history_count == parts[0].last_item_position


async def test_repeated_identical_ack_is_idempotent(
    digest_database,
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
) -> None:
    _, occurrence, _, _, _ = await _ready_digest(
        digest_repository,
        provision_digest_user,
        enable_digest_user,
        seed_digest_graph,
        count=1,
    )
    claim = await digest_repository.claim_delivery_part(occurrence.execution_id, 1, NOW)
    await digest_repository.acknowledge_delivery_part(
        claim, "provider-1", NOW + timedelta(seconds=1)
    )
    await digest_repository.acknowledge_delivery_part(
        claim, "provider-1", NOW + timedelta(seconds=1)
    )

    async with digest_database.session() as session:
        count = await session.scalar(
            select(func.count()).select_from(DigestDeliveryHistory)
        )
    assert count == 1


async def test_content_hash_mismatch_rejects_stale_claim(
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
) -> None:
    _, occurrence, _, _, _ = await _ready_digest(
        digest_repository,
        provision_digest_user,
        enable_digest_user,
        seed_digest_graph,
        count=1,
    )
    claim = await digest_repository.claim_delivery_part(occurrence.execution_id, 1, NOW)
    stale = DeliveryPartClaim(
        execution_id=claim.execution_id,
        ordinal=claim.ordinal,
        content_hash="f" * 64,
        first_item_position=claim.first_item_position,
        last_item_position=claim.last_item_position,
    )

    with pytest.raises(StaleAttemptError, match="descriptor"):
        await digest_repository.acknowledge_delivery_part(stale, "provider-1", NOW)


async def test_stale_sending_becomes_terminal_unknown_and_never_reclaims(
    digest_database,
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
) -> None:
    digest_repository._sending_stale_seconds = 1
    _, occurrence, _, _, _ = await _ready_digest(
        digest_repository,
        provision_digest_user,
        enable_digest_user,
        seed_digest_graph,
        count=1,
    )
    await digest_repository.claim_delivery_part(occurrence.execution_id, 1, NOW)

    second = await digest_repository.claim_delivery_part(
        occurrence.execution_id,
        1,
        NOW + timedelta(seconds=2),
    )

    assert second is None
    snapshot = await digest_repository.get_execution(occurrence.execution_id)
    assert snapshot.status is ExecutionStatus.DELIVERY_UNKNOWN
    assert (
        await digest_repository.claim_delivery_part(
            occurrence.execution_id,
            1,
            NOW + timedelta(minutes=10),
        )
        is None
    )
    async with digest_database.session() as session:
        history = (await session.execute(select(DigestDeliveryHistory))).scalar_one()
    assert history.outcome.value == "uncertain"


async def test_transient_retry_skips_acknowledged_part_and_reclaims_only_pending(
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
) -> None:
    _, occurrence, attempt, _, _ = await _ready_digest(
        digest_repository,
        provision_digest_user,
        enable_digest_user,
        seed_digest_graph,
        count=2,
        prepare_parts=False,
    )
    from hashlib import sha256

    parts = (
        RenderedPart(1, 1, 1, "part one", sha256(b"part one").hexdigest()),
        RenderedPart(2, 2, 2, "part two", sha256(b"part two").hexdigest()),
    )
    await digest_repository.prepare_delivery_parts(occurrence.execution_id, parts)
    first = await digest_repository.claim_delivery_part(occurrence.execution_id, 1, NOW)
    await digest_repository.acknowledge_delivery_part(first, "provider-first", NOW)
    await digest_repository.claim_delivery_part(occurrence.execution_id, 2, NOW)
    retry_at = NOW + timedelta(minutes=1)
    await digest_repository.record_transient_failure(
        attempt,
        "send_transient",
        NOW,
        retry_at,
    )

    claimed_retries = await digest_repository.claim_retries(retry_at, 100)
    first_again = await digest_repository.claim_delivery_part(
        occurrence.execution_id, 1, retry_at
    )
    second_again = await digest_repository.claim_delivery_part(
        occurrence.execution_id, 2, retry_at
    )

    assert claimed_retries == (occurrence.execution_id,)
    assert first_again is None
    assert second_again is not None
