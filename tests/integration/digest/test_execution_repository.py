from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from anxious_news_bot.digest.domain import (
    AttemptPhase,
    ExecutionStatus,
    StructuredDigestItem,
)
from anxious_news_bot.digest.errors import (
    ExecutionBusyError,
    ExecutionTerminalError,
)
from anxious_news_bot.digest.infrastructure.models import (
    DigestConfiguration,
    DigestExecution,
    DigestItem,
)

NOW = datetime(2026, 1, 15, 9, 1, tzinfo=UTC)


async def _claim_one(
    repository,
    provision_digest_user,
    enable_digest_user,
    *,
    telegram_user_id: int = 31_001,
    language_hint: str = "es",
):
    user = await provision_digest_user(
        telegram_user_id=telegram_user_id,
        language_hint=language_hint,
    )
    await enable_digest_user(
        user.application_user.id, due_at=NOW - timedelta(minutes=1)
    )
    occurrences = await repository.claim_due(NOW, 100)
    assert len(occurrences) == 1
    return user, occurrences[0]


async def test_overlapping_due_claims_create_one_stable_occurrence(
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    digest_database,
) -> None:
    user = await provision_digest_user(language_hint="es")
    await enable_digest_user(
        user.application_user.id,
        due_at=NOW - timedelta(minutes=1),
        digest_count=12,
    )

    claims = await asyncio.gather(
        digest_repository.claim_due(NOW, 100),
        digest_repository.claim_due(NOW, 100),
    )

    occurrences = tuple(item for batch in claims for item in batch)
    assert len(occurrences) == 1
    occurrence = occurrences[0]
    assert occurrence.user_id == user.application_user.id
    assert occurrence.telegram_user_id == user.application_user.telegram_user_id
    assert occurrence.digest_count == 12
    assert occurrence.language_code == "es"
    async with digest_database.session() as session:
        execution_count = await session.scalar(
            select(func.count()).select_from(DigestExecution)
        )
        configuration = await session.get(
            DigestConfiguration,
            user.application_user.id,
        )
    assert execution_count == 1
    assert configuration is not None
    assert configuration.next_due_at > NOW


async def test_attempt_claim_is_compare_and_set_and_rejects_concurrency(
    digest_repository,
    provision_digest_user,
    enable_digest_user,
) -> None:
    _, occurrence = await _claim_one(
        digest_repository,
        provision_digest_user,
        enable_digest_user,
    )

    first = await digest_repository.claim_attempt(
        occurrence.execution_id,
        AttemptPhase.PREPARE.value,
        NOW,
    )
    with pytest.raises(ExecutionBusyError):
        await digest_repository.claim_attempt(
            occurrence.execution_id,
            AttemptPhase.PREPARE.value,
            NOW,
        )

    retry_at = NOW + timedelta(minutes=1)
    snapshot = await digest_repository.record_transient_failure(
        first,
        "model_transient",
        NOW,
        retry_at,
    )
    assert snapshot.status is ExecutionStatus.RETRYING
    assert snapshot.next_retry_at == retry_at


async def test_item_insertion_validates_exact_count_before_any_write(
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    digest_database,
) -> None:
    _, occurrence = await _claim_one(
        digest_repository,
        provision_digest_user,
        enable_digest_user,
    )
    await digest_repository.claim_attempt(
        occurrence.execution_id,
        AttemptPhase.PREPARE.value,
        NOW,
    )
    await digest_repository.record_selection(
        occurrence.execution_id,
        selected_count=2,
        ranking_run_id=uuid4(),
        profile_revision=0,
    )
    only_item = StructuredDigestItem(
        position=1,
        article_id=uuid4(),
        article_analysis_id=uuid4(),
        event_group_id=None,
        ranking_run_id=uuid4(),
        title="Title",
        summary="Summary",
        source_name="Source",
        published_at=NOW,
        canonical_url="https://example.com/one",
        score=Decimal("0.80000000"),
    )

    with pytest.raises(ValueError, match="selected_count"):
        await digest_repository.record_items(
            occurrence.execution_id,
            (only_item,),
            NOW,
        )

    async with digest_database.session() as session:
        item_count = await session.scalar(
            select(func.count())
            .select_from(DigestItem)
            .where(DigestItem.execution_id == occurrence.execution_id)
        )
    assert item_count == 0


async def test_terminal_execution_rejects_new_attempts(
    digest_repository,
    provision_digest_user,
    enable_digest_user,
) -> None:
    _, occurrence = await _claim_one(
        digest_repository,
        provision_digest_user,
        enable_digest_user,
    )
    await digest_repository.claim_attempt(
        occurrence.execution_id,
        AttemptPhase.PREPARE.value,
        NOW,
    )
    await digest_repository.record_selection(
        occurrence.execution_id,
        selected_count=0,
        ranking_run_id=None,
        profile_revision=0,
    )
    completed = await digest_repository.complete_execution(
        occurrence.execution_id,
        NOW,
    )
    assert completed.status is ExecutionStatus.COMPLETED

    with pytest.raises(ExecutionTerminalError):
        await digest_repository.claim_attempt(
            occurrence.execution_id,
            AttemptPhase.PREPARE.value,
            NOW + timedelta(seconds=1),
        )


async def test_terminal_configuration_summaries_are_monotonic(
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    digest_database,
) -> None:
    user, occurrence = await _claim_one(
        digest_repository,
        provision_digest_user,
        enable_digest_user,
    )
    await digest_repository.record_success(
        occurrence.execution_id,
        NOW + timedelta(hours=2),
    )
    await digest_repository.record_success(
        occurrence.execution_id,
        NOW + timedelta(hours=1),
    )
    await digest_repository.record_failure(
        occurrence.execution_id,
        "newer_failure",
        NOW + timedelta(hours=4),
    )
    await digest_repository.record_failure(
        occurrence.execution_id,
        "older_failure",
        NOW + timedelta(hours=3),
    )

    async with digest_database.session() as session:
        configuration = await session.get(
            DigestConfiguration,
            user.application_user.id,
        )
    assert configuration is not None
    assert configuration.last_success_at == NOW + timedelta(hours=2)
    assert configuration.last_failure_at == NOW + timedelta(hours=4)
    assert configuration.last_failure_code == "newer_failure"
