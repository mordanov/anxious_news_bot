from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError

from anxious_news_bot.preferences.domain import PreferenceOrigin
from anxious_news_bot.preferences.errors import PreferenceProposalInvalid
from anxious_news_bot.preferences.infrastructure.models import PreferenceParameter
from anxious_news_bot.preferences.schemas import PreferenceChangesSchema
from tests.integration.preferences.helpers import completed_answers


async def test_forbidden_mixed_batch_leaves_protected_parameter_unchanged(
    preference_repository, preference_database
) -> None:
    context, state, _ = await completed_answers(preference_repository)
    explicit = PreferenceParameter(
        user_id=context.profile.user_id,
        semantic_key="explicit_topic",
        name="Explicit topic",
        description="User-authored preference",
        evaluation_instructions="Preserve exactly",
        weight=Decimal("0.40"),
        origin=PreferenceOrigin.EXPLICIT,
        active=True,
    )
    async with preference_database.session() as session:
        session.add(explicit)
        await session.flush()
        explicit_id = explicit.id
    await preference_repository.load_interpretation_input(state.questionnaire_id)
    proposal = PreferenceChangesSchema.model_validate(
        {
            "schema_version": "1.0",
            "questionnaire_id": state.questionnaire_id,
            "base_profile_revision": 0,
            "changes": [
                {
                    "action": "adjust",
                    "parameter_id": explicit_id,
                    "target_weight": "0.90",
                    "reason": "questionnaire",
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
        persisted = await session.scalar(
            select(PreferenceParameter).where(PreferenceParameter.id == explicit_id)
        )
    assert persisted.weight == Decimal("0.40")
    assert persisted.origin is PreferenceOrigin.EXPLICIT


async def test_parameter_origin_is_database_immutable(
    preference_repository, preference_database
) -> None:
    context, _ = await preference_repository.start_or_resume(800, "en")
    parameter = PreferenceParameter(
        user_id=context.profile.user_id,
        semantic_key="explicit_origin",
        name="Explicit origin",
        description="User-authored preference",
        evaluation_instructions="Preserve exactly",
        weight=Decimal("0.40"),
        origin=PreferenceOrigin.EXPLICIT,
        active=True,
    )
    async with preference_database.session() as session:
        session.add(parameter)
        await session.flush()
        parameter_id = parameter.id
    with pytest.raises(DBAPIError):
        async with preference_database.session() as session:
            await session.execute(
                update(PreferenceParameter)
                .where(PreferenceParameter.id == parameter_id)
                .values(origin=PreferenceOrigin.QUESTIONNAIRE)
            )
