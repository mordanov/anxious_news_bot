from datetime import UTC, datetime
from time import perf_counter

from anxious_news_bot.preferences.domain import TuneStateKind
from tests.integration.preferences.helpers import completed_answers


async def test_locally_accepted_answer_state_is_returned_within_two_seconds(
    preference_repository,
) -> None:
    _, state, tokens = await completed_answers(preference_repository)
    assert state.kind is TuneStateKind.PROCESSING
    started = perf_counter()
    replay = await preference_repository.record_answer(
        100, tokens[-1][0], datetime.now(UTC)
    )
    assert perf_counter() - started < 2
    assert replay.kind is TuneStateKind.PROCESSING
