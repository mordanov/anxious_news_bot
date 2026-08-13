from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select

from anxious_news_bot.preferences.errors import PreferenceProposalInvalid
from anxious_news_bot.preferences.infrastructure.models import (
    PreferenceChangeAudit,
    PreferenceChangeHistory,
    PreferenceUpdateBatch,
)
from anxious_news_bot.preferences.schemas import PreferenceChangesSchema
from tests.integration.preferences.helpers import completed_answers


async def test_invalid_batch_rolls_back_batch_history_and_audit(
    preference_repository, preference_database
) -> None:
    _, state, _ = await completed_answers(preference_repository)
    await preference_repository.load_interpretation_input(state.questionnaire_id)
    proposal = PreferenceChangesSchema.model_validate(
        {
            "schema_version": "1.0",
            "questionnaire_id": state.questionnaire_id,
            "base_profile_revision": 0,
            "changes": [
                {
                    "action": "adjust",
                    "parameter_id": UUID("00000000-0000-0000-0000-000000000001"),
                    "target_weight": "0.50",
                    "reason": "invalid target",
                }
            ],
        },
        strict=True,
    )
    with pytest.raises(PreferenceProposalInvalid):
        await preference_repository.apply_changes(
            state.questionnaire_id, proposal, datetime.now(UTC)
        )
    async with preference_database.session() as session:
        counts = [
            await session.scalar(select(func.count(model.id)))
            for model in (
                PreferenceUpdateBatch,
                PreferenceChangeHistory,
                PreferenceChangeAudit,
            )
        ]
    assert counts == [0, 0, 0]
