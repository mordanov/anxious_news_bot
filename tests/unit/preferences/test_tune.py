from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

from anxious_news_bot.preferences.domain import (
    PreferenceOrigin,
    PreferenceParameter,
    ProfileSnapshot,
    QuestionDimensionContext,
    QuestionnaireContext,
    TuneState,
    TuneStateKind,
)
from anxious_news_bot.preferences.errors import QuestionnaireGenerationFailed
from anxious_news_bot.preferences.services.apply_changes import (
    DeterministicPreferenceChangeValidator,
)
from anxious_news_bot.preferences.services.dimensions import DIMENSIONS
from anxious_news_bot.preferences.services.duplicates import PreferenceDuplicateDetector
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
        self.completed_no_change = False
        self.dimension_context = ()

    async def start_or_resume(self, telegram_user_id, language_code):
        del telegram_user_id
        return (
            QuestionnaireContext(
                self.profile,
                language_code,
                dimension_context=self.dimension_context,
            ),
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

    async def complete_questionnaire_no_change(self, questionnaire_id, completed_at):
        del completed_at
        self.completed_no_change = True
        return TuneState(TuneStateKind.COMPLETED, questionnaire_id)

    async def duplicate_candidates(self, user_id, semantic_key, name):
        del user_id, semantic_key, name
        return self.profile

    async def fail(self, questionnaire_id, error_code, failed_at):
        del failed_at
        self.failed = error_code
        return TuneState(TuneStateKind.FAILED, questionnaire_id)


def _service(repository, model, **kwargs):
    return PreferenceTuningService(
        repository,
        model,
        DeterministicQuestionnaireQualityValidator(),
        DeterministicPreferenceChangeValidator(),
        SecureCallbackTokenFactory(),
        FixedClock(),
        **kwargs,
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


async def test_retries_locally_invalid_questionnaire_generation() -> None:
    repository = Repository()
    invalid = deepcopy(generated_questionnaire())
    invalid["questions"][0]["ordinal"] = "1"

    class RetryModel(FakeModel):
        calls = 0

        async def generate(self, context):
            del context
            self.calls += 1
            return invalid if self.calls == 1 else generated_questionnaire()

    model = RetryModel(generated_questionnaire())
    result = await _service(
        repository,
        model,
        generation_attempts=2,
    ).start_or_resume(123, "en")

    assert result.kind is TuneStateKind.QUESTION
    assert model.calls == 2


async def test_fails_after_generation_validation_attempts_are_exhausted() -> None:
    repository = Repository()
    invalid = deepcopy(generated_questionnaire())
    invalid["questions"][0]["ordinal"] = "1"

    class InvalidModel(FakeModel):
        calls = 0

        async def generate(self, context):
            del context
            self.calls += 1
            return invalid

    model = InvalidModel(invalid)
    result = await _service(
        repository,
        model,
        generation_attempts=2,
    ).start_or_resume(123, "en")

    assert result.kind is TuneStateKind.FAILED
    assert repository.failed == "generation_failed"
    assert model.calls == 2


async def test_retries_questionnaire_that_reuses_durable_dimension_context() -> None:
    repository = Repository()
    repository.dimension_context = tuple(
        QuestionDimensionContext(
            dimension_key=dimension.key,
            exposure_count=1,
            last_exposed_at=FixedClock.value,
        )
        for dimension in DIMENSIONS[:10]
    )
    fresh = deepcopy(generated_questionnaire())
    for question, dimension in zip(
        fresh["questions"],
        DIMENSIONS[10:20],
        strict=True,
    ):
        question["dimension_key"] = dimension.key

    class RetryModel(FakeModel):
        calls = 0

        async def generate(self, context):
            del context
            self.calls += 1
            return generated_questionnaire() if self.calls == 1 else fresh

    model = RetryModel(generated_questionnaire())
    result = await _service(
        repository,
        model,
        generation_attempts=2,
    ).start_or_resume(123, "en")

    assert result.kind is TuneStateKind.QUESTION
    assert model.calls == 2
    assert repository.stored[0].questions[0].dimension_key == DIMENSIONS[10].key


async def test_equivalent_questionnaire_create_is_resolved_as_adjustment() -> None:
    repository = Repository()
    parameter = PreferenceParameter(
        id=uuid4(),
        user_id=repository.profile.user_id,
        semantic_key="local_news",
        name="Local news",
        description="Local reporting",
        evaluation_instructions="Prefer local reporting",
        weight=Decimal("0.40"),
        origin=PreferenceOrigin.QUESTIONNAIRE,
        active=True,
        created_at=FixedClock.value,
        updated_at=FixedClock.value,
    )
    repository.profile = ProfileSnapshot(parameter.user_id, 0, (parameter,))
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
                "target_weight": "0.80",
                "reason": "Questionnaire evidence",
            }
        ],
    }
    model = FakeModel(generated_questionnaire(), proposal)

    result = await _service(
        repository,
        model,
        duplicate_detector=PreferenceDuplicateDetector(model),
    ).answer(123, "opaque")

    assert result.kind is TuneStateKind.COMPLETED
    assert repository.applied.changes[0].action == "adjust"
    assert repository.applied.changes[0].parameter_id == parameter.id


async def test_protected_equivalent_completes_without_profile_change() -> None:
    repository = Repository()
    parameter = PreferenceParameter(
        id=uuid4(),
        user_id=repository.profile.user_id,
        semantic_key="local_news",
        name="Local news",
        description="Local reporting",
        evaluation_instructions="Prefer local reporting",
        weight=Decimal("0.40"),
        origin=PreferenceOrigin.EXPLICIT,
        active=True,
        created_at=FixedClock.value,
        updated_at=FixedClock.value,
    )
    repository.profile = ProfileSnapshot(parameter.user_id, 0, (parameter,))
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
                "target_weight": "0.40",
                "reason": "Questionnaire evidence",
            }
        ],
    }
    model = FakeModel(generated_questionnaire(), proposal)

    result = await _service(
        repository,
        model,
        duplicate_detector=PreferenceDuplicateDetector(model),
    ).answer(123, "opaque")

    assert result.kind is TuneStateKind.COMPLETED
    assert repository.completed_no_change
    assert repository.applied is None


async def test_retries_invalid_interpretation_proposal() -> None:
    repository = Repository()
    valid = {
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
    invalid = {**valid, "base_profile_revision": 99}

    class RetryModel(FakeModel):
        calls = 0

        async def propose(self, profile, questionnaire_id, answers):
            del profile, questionnaire_id, answers
            self.calls += 1
            return invalid if self.calls == 1 else valid

    model = RetryModel(generated_questionnaire(), valid)
    result = await _service(
        repository,
        model,
        interpretation_attempts=2,
    ).answer(123, "opaque")

    assert result.kind is TuneStateKind.COMPLETED
    assert repository.applied is not None
    assert model.calls == 2
