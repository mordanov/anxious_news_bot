from __future__ import annotations

from uuid import uuid4

from anxious_news_bot.preferences.domain import (
    ProfileSnapshot,
    QuestionnaireContext,
    TuneState,
    TuneStateKind,
)
from anxious_news_bot.preferences.errors import QuestionnaireGenerationFailed
from anxious_news_bot.preferences.services.apply_changes import (
    DeterministicPreferenceChangeValidator,
)
from anxious_news_bot.preferences.services.questionnaire_quality import (
    DeterministicQuestionnaireQualityValidator,
)
from anxious_news_bot.preferences.services.tokens import SecureCallbackTokenFactory
from anxious_news_bot.preferences.services.tune import PreferenceTuningService
from tests.fixtures.preferences import FakeModel, FixedClock, generated_questionnaire


class Repository:
    def __init__(self):
        self.questionnaire_id = uuid4()
        self.profile = ProfileSnapshot(uuid4(), 0, ())
        self.stored = None
        self.failed = None
        self.applied = None

    async def start_or_resume(self, telegram_user_id, language_code):
        del telegram_user_id
        return (
            QuestionnaireContext(self.profile, language_code),
            TuneState(TuneStateKind.GENERATING, self.questionnaire_id),
        )

    async def store_generated(self, questionnaire_id, questionnaire, token_hashes):
        self.stored = questionnaire, token_hashes
        return TuneState(
            TuneStateKind.QUESTION,
            questionnaire_id,
            ordinal=1,
            question=questionnaire.questions[0].text,
        )

    async def record_answer(self, telegram_user_id, callback_token, answered_at):
        del telegram_user_id, callback_token, answered_at
        return TuneState(TuneStateKind.PROCESSING, self.questionnaire_id)

    async def load_interpretation_input(self, questionnaire_id):
        del questionnaire_id
        return self.profile, tuple((f"q{i}", f"a{i}") for i in range(10))

    async def apply_changes(self, questionnaire_id, proposal, applied_at):
        del applied_at
        self.applied = proposal
        return TuneState(TuneStateKind.COMPLETED, questionnaire_id)

    async def fail(self, questionnaire_id, error_code, failed_at):
        del failed_at
        self.failed = error_code
        return TuneState(TuneStateKind.FAILED, questionnaire_id)


def _service(repository, model):
    return PreferenceTuningService(
        repository,
        model,
        DeterministicQuestionnaireQualityValidator(),
        DeterministicPreferenceChangeValidator(),
        SecureCallbackTokenFactory(),
        FixedClock(),
    )


async def test_generates_and_stores_complete_questionnaire() -> None:
    repository = Repository()
    result = await _service(
        repository, FakeModel(generated_questionnaire())
    ).start_or_resume(123, "en")
    assert result.kind is TuneStateKind.QUESTION
    candidate, hashes = repository.stored
    assert len(candidate.questions) == 10
    assert [len(options) for options in hashes] == [4] * 10
    assert all(len(token) == 43 for options in hashes for token in options)


async def test_answer_ten_interprets_and_applies_once() -> None:
    repository = Repository()
    proposal = {
        "schema_version": "1.0",
        "questionnaire_id": repository.questionnaire_id,
        "base_profile_revision": 0,
        "changes": [
            {
                "action": "create",
                "semantic_key": "local_news",
                "name": "Local news",
                "description": "Local reporting",
                "evaluation_instructions": "Prefer local reporting",
                "target_weight": "0.50",
                "reason": "Questionnaire evidence",
            }
        ],
    }
    result = await _service(
        repository, FakeModel(generated_questionnaire(), proposal)
    ).answer(123, "opaque")
    assert result.kind is TuneStateKind.COMPLETED
    assert repository.applied.changes[0].weight.as_tuple().exponent == -2


class FailedModel(FakeModel):
    async def generate(self, context):
        del context
        raise QuestionnaireGenerationFailed("unavailable")


async def test_provider_failure_becomes_controlled_failed_state() -> None:
    repository = Repository()
    result = await _service(
        repository, FailedModel(generated_questionnaire())
    ).start_or_resume(123, "en")
    assert result.kind is TuneStateKind.FAILED
    assert repository.failed == "generation_failed"
