"""Execution service tests."""

from uuid import uuid4

import pytest

from anxious_news_bot.digest.domain import ExecutionStatus, RetrySchedule
from anxious_news_bot.digest.errors import (
    CompositionPermanentError,
    CompositionTransientError,
)
from anxious_news_bot.digest.services.execute import DigestExecutionService
from tests.fixtures.digest import (
    FakeComposer,
    FakeDelivery,
    FakeDigestConfigurationRepository,
    FakeDigestExecutionRepository,
    FakeNewsSelector,
    FixedClock,
    make_ranked_items,
    make_test_occurrence,
)


def _make_service(items=None, *, composer_error=None, max_attempts=3):
    config_repo = FakeDigestConfigurationRepository()
    exec_repo = FakeDigestExecutionRepository()
    news_items = items if items is not None else make_ranked_items(3)
    selector = FakeNewsSelector(news_items)
    composer = FakeComposer(error=composer_error)
    delivery = FakeDelivery()
    clock = FixedClock()
    service = DigestExecutionService(
        config_repository=config_repo,
        execution_repository=exec_repo,
        personal_news_selector=selector,
        composer=composer,
        delivery=delivery,
        candidate_filter=None,
        clock=clock,
        retry_schedule=RetrySchedule(
            base_seconds=60,
            max_seconds=900,
            max_attempts=max_attempts,
        ),
    )
    return service, config_repo, exec_repo, composer, delivery


class TestExecutionService:
    @pytest.mark.asyncio
    async def test_successful_execution(self):
        service, config_repo, exec_repo, composer, delivery = _make_service()
        occ = make_test_occurrence()
        result = await service.execute(occ)
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_zero_item_execution(self):
        service, config_repo, exec_repo, composer, delivery = _make_service(items=[])
        occ = make_test_occurrence()
        result = await service.execute(occ)
        assert result.status == ExecutionStatus.COMPLETED
        assert delivery.sent_parts == []

    @pytest.mark.asyncio
    async def test_composer_called_with_items(self):
        service, _, _, composer, _ = _make_service()
        occ = make_test_occurrence(digest_count=5)
        await service.execute(occ)
        assert len(composer.calls) == 1

    @pytest.mark.asyncio
    async def test_delivery_sends_parts(self):
        service, _, _, _, delivery = _make_service()
        occ = make_test_occurrence()
        await service.execute(occ)
        assert len(delivery.sent_parts) > 0

    @pytest.mark.asyncio
    async def test_uses_captured_language_and_forwards_candidate_filter(self):
        service, _, _, composer, _ = _make_service()
        filter_marker = object()
        service._candidate_filter = filter_marker
        occ = make_test_occurrence(language_code="es")

        await service.execute(occ)

        assert composer.calls[0][1] == "es"
        assert service._news_selector.calls[0][-1] is filter_marker

    @pytest.mark.asyncio
    async def test_transient_failure_records_the_actual_attempt_claim(self):
        service, _, exec_repo, _, _ = _make_service(
            composer_error=CompositionTransientError(
                "temporary",
                code="model_transient",
            )
        )
        occ = make_test_occurrence()

        result = await service.execute(occ)

        assert result.status is ExecutionStatus.RETRYING
        assert exec_repo.transient_failures
        claim, code, _, _ = exec_repo.transient_failures[0]
        assert claim == exec_repo.last_attempt
        assert claim.execution_id == occ.execution_id
        assert code == "model_transient"

    @pytest.mark.asyncio
    async def test_permanent_failure_records_the_actual_attempt_claim(self):
        service, _, exec_repo, _, _ = _make_service(
            composer_error=CompositionPermanentError(
                "invalid",
                code="validation_failed",
            )
        )
        occ = make_test_occurrence()

        result = await service.execute(occ)

        assert result.status is ExecutionStatus.FAILED
        claim, code, _ = exec_repo.permanent_failures[0]
        assert claim == exec_repo.last_attempt
        assert code == "validation_failed"

    @pytest.mark.asyncio
    async def test_last_transient_attempt_becomes_terminal(self):
        service, _, exec_repo, _, _ = _make_service(
            composer_error=CompositionTransientError(
                "temporary",
                code="model_transient",
            ),
            max_attempts=3,
        )
        exec_repo.attempt_count = 2
        occ = make_test_occurrence()

        result = await service.execute(occ)

        assert result.status is ExecutionStatus.FAILED
        assert not exec_repo.transient_failures
        assert exec_repo.permanent_failures[0][1] == "exhausted_model_transient"

    @pytest.mark.asyncio
    async def test_retry_loads_persisted_recipient_context(self):
        service, _, exec_repo, _, delivery = _make_service()
        occ = make_test_occurrence(execution_id=uuid4(), language_code="ru")
        exec_repo.occurrences[occ.execution_id] = occ
        exec_repo.retry_ids = (occ.execution_id,)

        result = await service.retry_due(service._clock.now())

        assert result.retried_count == 1
        assert result.completed_count == 1
        assert delivery.sent_parts

    @pytest.mark.asyncio
    async def test_retry_with_persisted_digest_skips_recomposition(self):
        service, _, exec_repo, composer, delivery = _make_service()
        occ = make_test_occurrence()
        initial = make_ranked_items(1)
        merged_service, _, initial_repo, _, _ = _make_service(items=initial)
        await merged_service.execute(occ)
        exec_repo.digests[occ.execution_id] = initial_repo.digests[occ.execution_id]

        result = await service.execute(occ)

        assert result.status is ExecutionStatus.COMPLETED
        assert composer.calls == []
        assert delivery.sent_parts
