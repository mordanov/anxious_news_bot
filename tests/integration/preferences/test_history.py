from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from anxious_news_bot.preferences.infrastructure.models import (
    PreferenceChangeAudit,
    PreferenceChangeHistory,
    PreferenceUpdateBatch,
)
from tests.integration.preferences.helpers import (
    completed_answers,
    create_proposal,
)


async def test_every_applied_change_has_full_and_compact_audit(
    preference_repository, preference_database
) -> None:
    _, state, _ = await completed_answers(preference_repository)
    await preference_repository.load_interpretation_input(state.questionnaire_id)
    await preference_repository.apply_changes(
        state.questionnaire_id,
        create_proposal(state.questionnaire_id),
        datetime.now(UTC),
    )
    async with preference_database.session() as session:
        history = tuple(await session.scalars(select(PreferenceChangeHistory)))
        audits = tuple(await session.scalars(select(PreferenceChangeAudit)))
        batch = await session.scalar(select(PreferenceUpdateBatch))
    assert len(history) == len(audits) == batch.change_count == 1
    assert history[0].id == audits[0].id
    assert batch.history_digest


async def test_compact_audit_rows_are_database_immutable(
    preference_repository, preference_database
) -> None:
    _, state, _ = await completed_answers(preference_repository)
    await preference_repository.load_interpretation_input(state.questionnaire_id)
    await preference_repository.apply_changes(
        state.questionnaire_id,
        create_proposal(state.questionnaire_id),
        datetime.now(UTC),
    )
    with pytest.raises(DBAPIError):
        async with preference_database.session() as session:
            await session.execute(
                text("UPDATE preference_change_audit SET reason_hash = repeat('0', 64)")
            )
