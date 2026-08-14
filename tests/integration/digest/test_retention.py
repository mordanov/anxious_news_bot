from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text

from anxious_news_bot.digest.infrastructure.models import (
    DigestDeliveryHistory,
    DigestDeliveryPart,
    DigestExecutionAttempt,
    DigestItem,
)
from anxious_news_bot.digest.services.retention import DigestRetentionService
from tests.fixtures.digest import FixedClock
from tests.integration.digest.test_delivery_idempotency import _ready_digest

NOW = datetime(2026, 3, 1, 9, tzinfo=UTC)
OLD = NOW - timedelta(days=60)


async def test_retention_removes_only_expired_confirmed_terminal_history_and_details(
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
    claim = await digest_repository.claim_delivery_part(occurrence.execution_id, 1, OLD)
    await digest_repository.acknowledge_delivery_part(claim, "retention-1", OLD)
    await digest_repository.complete_execution(occurrence.execution_id, OLD)
    async with digest_database.session() as session:
        await session.execute(
            text(
                "UPDATE digest_delivery_history SET delivered_at = :old "
                "WHERE execution_id = :execution_id"
            ),
            {"old": OLD, "execution_id": occurrence.execution_id},
        )
        await session.execute(
            text(
                "UPDATE digest_executions SET completed_at = :old "
                "WHERE id = :execution_id"
            ),
            {"old": OLD, "execution_id": occurrence.execution_id},
        )

    deleted = await DigestRetentionService(
        digest_repository,
        FixedClock(NOW),
        history_retention_days=30,
    ).run_cleanup()

    assert deleted >= 3
    async with digest_database.session() as session:
        history_count = await session.scalar(
            select(func.count()).select_from(DigestDeliveryHistory)
        )
        attempt_count = await session.scalar(
            select(func.count()).select_from(DigestExecutionAttempt)
        )
        part_count = await session.scalar(
            select(func.count()).select_from(DigestDeliveryPart)
        )
        item_count = await session.scalar(select(func.count()).select_from(DigestItem))
    assert (history_count, attempt_count, part_count, item_count) == (0, 0, 0, 0)


async def test_retention_preserves_unknown_delivery_evidence(
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
    claim = await digest_repository.claim_delivery_part(occurrence.execution_id, 1, OLD)
    await digest_repository.record_delivery_unknown(
        claim,
        "timeout_ambiguous",
        OLD,
    )

    await DigestRetentionService(
        digest_repository,
        FixedClock(NOW),
        history_retention_days=30,
    ).run_cleanup()

    async with digest_database.session() as session:
        history_count = await session.scalar(
            select(func.count()).select_from(DigestDeliveryHistory)
        )
        part_count = await session.scalar(
            select(func.count()).select_from(DigestDeliveryPart)
        )
    assert (history_count, part_count) == (1, 1)


async def test_retention_preserves_active_retry_attempts(
    digest_database,
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
        count=1,
    )
    await digest_repository.record_transient_failure(
        attempt,
        "send_transient",
        OLD,
        OLD + timedelta(minutes=1),
    )

    await DigestRetentionService(
        digest_repository,
        FixedClock(NOW),
        history_retention_days=30,
    ).run_cleanup()

    async with digest_database.session() as session:
        attempt_count = await session.scalar(
            select(func.count()).select_from(DigestExecutionAttempt)
        )
        part_count = await session.scalar(
            select(func.count()).select_from(DigestDeliveryPart)
        )
    assert (attempt_count, part_count) == (1, 1)
