from __future__ import annotations

from datetime import UTC, datetime

from anxious_news_bot.preferences.schemas import (
    PreferenceChangesSchema,
    QuestionnaireGenerationSchema,
)
from tests.fixtures.preferences import generated_questionnaire


async def completed_answers(repository, telegram_user_id: int = 100):
    context, state = await repository.start_or_resume(telegram_user_id, "en")
    questionnaire = QuestionnaireGenerationSchema.model_validate(
        generated_questionnaire(), strict=True
    )
    tokens = tuple(
        tuple(f"token-{question}-{option}" for option in range(4))
        for question in range(10)
    )
    state = await repository.store_generated(
        state.questionnaire_id, questionnaire, tokens
    )
    for question in range(10):
        state = await repository.record_answer(
            telegram_user_id, tokens[question][0], datetime.now(UTC)
        )
    return context, state, tokens


def create_proposal(questionnaire_id, revision=0):
    return PreferenceChangesSchema.model_validate(
        {
            "schema_version": "1.0",
            "questionnaire_id": questionnaire_id,
            "base_profile_revision": revision,
            "changes": [
                {
                    "action": "create",
                    "semantic_key": "local_news",
                    "name": "Local news",
                    "description": "Local reporting",
                    "evaluation_instructions": "Prefer local reporting",
                    "target_weight": "0.50",
                    "reason": "Questionnaire answer evidence",
                }
            ],
        },
        strict=True,
    )
