from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anxious_news_bot.preferences.domain import SupportedLanguage, TuneStateKind
from anxious_news_bot.preferences.errors import AnswerRejected
from anxious_news_bot.preferences.infrastructure.persistence import (
    SQLAlchemyPreferenceRepository,
)
from anxious_news_bot.preferences.schemas import QuestionnaireGenerationSchema
from tests.fixtures.preferences import generated_questionnaire


async def test_atomic_storage_duplicate_replay_and_restart_resume(
    preference_repository,
    preference_database,
) -> None:
    _, state = await preference_repository.start_or_resume(123, "en")
    candidate = QuestionnaireGenerationSchema.model_validate(
        generated_questionnaire(), strict=True
    )
    tokens = tuple(
        tuple(f"q{question}-o{option}" for option in range(4)) for question in range(10)
    )
    state = await preference_repository.store_generated(
        state.questionnaire_id, candidate, tokens
    )
    assert state.kind is TuneStateKind.QUESTION
    assert len(state.options) == 4

    for question in range(9):
        state = await preference_repository.record_answer(
            123, tokens[question][0], datetime.now(UTC)
        )
        assert state.ordinal == question + 2
    restarted = SQLAlchemyPreferenceRepository(preference_database)
    _, state = await restarted.start_or_resume(123, "en")
    assert state.ordinal == 10
    state = await restarted.record_answer(123, tokens[9][0], datetime.now(UTC))
    assert state.kind is TuneStateKind.PROCESSING
    replay = await restarted.record_answer(123, tokens[9][0], datetime.now(UTC))
    assert replay.kind is TuneStateKind.PROCESSING


async def test_rejects_raced_or_wrong_user_options(preference_repository) -> None:
    _, state = await preference_repository.start_or_resume(123, "en")
    candidate = QuestionnaireGenerationSchema.model_validate(
        generated_questionnaire(), strict=True
    )
    tokens = tuple(
        tuple(f"r{question}-o{option}" for option in range(4)) for question in range(10)
    )
    await preference_repository.store_generated(
        state.questionnaire_id, candidate, tokens
    )
    with pytest.raises(AnswerRejected):
        await preference_repository.record_answer(456, tokens[0][0], datetime.now(UTC))
    with pytest.raises(AnswerRejected):
        await preference_repository.record_answer(123, tokens[1][0], datetime.now(UTC))


async def test_language_selection_is_persisted_and_restarts_active_questionnaire(
    preference_repository,
) -> None:
    context, original = await preference_repository.start_or_resume(789, "en-US")
    assert context.language_code == "en"

    await preference_repository.set_language(
        789,
        SupportedLanguage.ENGLISH,
        datetime.now(UTC),
    )
    _, unchanged = await preference_repository.start_or_resume(789, "ru")
    assert unchanged.questionnaire_id == original.questionnaire_id

    await preference_repository.set_language(
        789,
        SupportedLanguage.SPANISH,
        datetime.now(UTC),
    )

    assert await preference_repository.get_or_create_language(789, "en-US") == (
        SupportedLanguage.SPANISH
    )
    context, replacement = await preference_repository.start_or_resume(789, "en-US")
    assert context.language_code == "es"
    assert replacement.questionnaire_id != original.questionnaire_id
