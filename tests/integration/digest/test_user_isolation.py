from __future__ import annotations

from datetime import UTC, datetime, timedelta

from anxious_news_bot.digest.errors import (
    AmbiguousDeliveryError,
    CompositionTransientError,
    PermanentDeliveryError,
)
from anxious_news_bot.digest.services.execute import DigestExecutionService
from tests.fixtures.digest import FakeComposer, FakeDelivery, FixedClock
from tests.integration.digest.test_scheduled_delivery import (
    SelectionByUser,
    _selection,
)

NOW = datetime(2026, 1, 15, 9, 1, tzinfo=UTC)


class FailLanguageComposer(FakeComposer):
    async def compose(self, execution_id, language, ranked_items):
        if language == "es":
            raise CompositionTransientError("temporary", code="model_transient")
        return await super().compose(execution_id, language, ranked_items)


class FailRecipientDelivery(FakeDelivery):
    def __init__(self, recipient, error):
        super().__init__()
        self.recipient = recipient
        self.error = error

    async def send(self, telegram_user_id, rendered_part):
        if telegram_user_id == self.recipient:
            raise self.error
        return await super().send(telegram_user_id, rendered_part)


async def _two_user_service(
    repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
    *,
    composer=None,
    delivery=None,
):
    first = await provision_digest_user(telegram_user_id=62_001, language_hint="es")
    second = await provision_digest_user(telegram_user_id=62_002, language_hint="en")
    for user in (first, second):
        await enable_digest_user(
            user.application_user.id,
            due_at=NOW - timedelta(minutes=1),
        )
    first_graph = await seed_digest_graph(first.application_user.id, count=1)
    second_graph = await seed_digest_graph(second.application_user.id, count=1)
    service = DigestExecutionService(
        repository,
        repository,
        SelectionByUser(
            {
                first.application_user.id: _selection(first_graph),
                second.application_user.id: _selection(second_graph),
            }
        ),
        composer or FakeComposer(),
        delivery or FakeDelivery(),
        None,
        FixedClock(NOW),
    )
    return first, second, service


async def test_model_failure_for_one_user_does_not_cancel_another(
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
) -> None:
    _, _, service = await _two_user_service(
        digest_repository,
        provision_digest_user,
        enable_digest_user,
        seed_digest_graph,
        composer=FailLanguageComposer(),
    )

    result = await service.run_due_cycle(NOW)

    assert (result.completed_count, result.failed_count) == (1, 1)


async def test_permanent_delivery_failure_is_isolated(
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
) -> None:
    first = await provision_digest_user(telegram_user_id=62_001, language_hint="es")
    delivery = FailRecipientDelivery(
        first.application_user.telegram_user_id,
        PermanentDeliveryError("blocked", code="forbidden"),
    )
    # The helper self-heals/reuses the already-created first user.
    _, _, service = await _two_user_service(
        digest_repository,
        provision_digest_user,
        enable_digest_user,
        seed_digest_graph,
        delivery=delivery,
    )

    result = await service.run_due_cycle(NOW)

    assert (result.completed_count, result.failed_count) == (1, 1)


async def test_ambiguous_delivery_is_terminal_and_isolated(
    digest_repository,
    provision_digest_user,
    enable_digest_user,
    seed_digest_graph,
) -> None:
    first = await provision_digest_user(telegram_user_id=62_001, language_hint="es")
    delivery = FailRecipientDelivery(
        first.application_user.telegram_user_id,
        AmbiguousDeliveryError("unknown", code="timeout_ambiguous"),
    )
    _, _, service = await _two_user_service(
        digest_repository,
        provision_digest_user,
        enable_digest_user,
        seed_digest_graph,
        delivery=delivery,
    )

    result = await service.run_due_cycle(NOW)

    assert (result.completed_count, result.failed_count) == (1, 1)
    retries = await digest_repository.claim_retries(
        NOW + timedelta(days=1),
        100,
    )
    assert retries == ()
