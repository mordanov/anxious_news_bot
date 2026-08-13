import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import update

from anxious_news_bot.preferences.errors import StaleProfileRevision
from anxious_news_bot.preferences.infrastructure.models import PreferenceProfile
from tests.integration.preferences.helpers import completed_answers, create_proposal


async def test_stale_revision_rejects_whole_application(
    preference_repository, preference_database
) -> None:
    _, state, _ = await completed_answers(preference_repository)
    await preference_repository.load_interpretation_input(state.questionnaire_id)
    async with preference_database.session() as session:
        await session.execute(update(PreferenceProfile).values(revision=1))
    with pytest.raises(StaleProfileRevision):
        await preference_repository.apply_changes(
            state.questionnaire_id,
            create_proposal(state.questionnaire_id),
            datetime.now(UTC),
        )


async def test_concurrent_tune_claims_resolve_to_one_active_questionnaire(
    preference_repository,
) -> None:
    first, second = await asyncio.gather(
        preference_repository.start_or_resume(900, "en"),
        preference_repository.start_or_resume(900, "en"),
    )
    assert first[1].questionnaire_id == second[1].questionnaire_id
