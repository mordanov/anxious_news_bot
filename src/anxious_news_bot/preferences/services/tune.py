from __future__ import annotations

import json

from pydantic import ValidationError

from anxious_news_bot.preferences.domain import (
    PreferenceOrigin,
    TuneState,
    TuneStateKind,
)
from anxious_news_bot.preferences.errors import (
    PreferenceProposalInvalid,
    PreferenceTuningError,
    QuestionnaireInvalid,
    StaleProfileRevision,
)
from anxious_news_bot.preferences.observability import (
    log_preference_event,
    preference_exception_context,
)
from anxious_news_bot.preferences.ports import (
    Clock,
    PreferenceInterpreter,
    PreferenceRepositoryPort,
    QuestionnaireGenerator,
    QuestionnaireQualityValidator,
    TokenFactory,
)
from anxious_news_bot.preferences.schemas import (
    PreferenceChangesSchema,
    QuestionnaireGenerationSchema,
)
from anxious_news_bot.preferences.services.apply_changes import (
    DeterministicPreferenceChangeValidator,
)
from anxious_news_bot.preferences.services.dimensions import available_dimensions
from anxious_news_bot.preferences.services.duplicates import (
    PreferenceDuplicateDetector,
    rewrite_equivalent_create,
)
from anxious_news_bot.preferences.services.repetition import (
    SubstantialRepetitionDetector,
)


class PreferenceTuningService:
    def __init__(
        self,
        repository: PreferenceRepositoryPort,
        model: QuestionnaireGenerator | PreferenceInterpreter,
        quality: QuestionnaireQualityValidator,
        change_validator: DeterministicPreferenceChangeValidator,
        tokens: TokenFactory,
        clock: Clock,
        duplicate_detector: PreferenceDuplicateDetector | None = None,
        repetition_detector: SubstantialRepetitionDetector | None = None,
        generation_attempts: int = 3,
        interpretation_attempts: int = 2,
    ) -> None:
        if generation_attempts < 1 or interpretation_attempts < 1:
            raise ValueError("model validation attempts must be positive")
        self._repository = repository
        self._model = model
        self._quality = quality
        self._change_validator = change_validator
        self._tokens = tokens
        self._clock = clock
        self._duplicate_detector = duplicate_detector
        self._repetition_detector = repetition_detector
        self._generation_attempts = generation_attempts
        self._interpretation_attempts = interpretation_attempts

    async def start_or_resume(
        self, telegram_user_id: int, language_code: str | None
    ) -> TuneState:
        context, state = await self._repository.start_or_resume(
            telegram_user_id, language_code
        )
        if state.kind is TuneStateKind.PROCESSING:
            questionnaire_id = self._required_id(state)
            try:
                result, _ = await self._interpret_and_apply(questionnaire_id)
                return result
            except (
                PreferenceTuningError,
                ValidationError,
                ValueError,
                KeyError,
            ) as exc:
                return await self._fail(questionnaire_id, "interpretation_failed", exc)
        if state.kind is not TuneStateKind.GENERATING:
            return state
        questionnaire_id = self._required_id(state)
        try:
            candidate = await self._generate_candidate(context, questionnaire_id)
            token_hashes = tuple(
                tuple(self._tokens.create()[1] for _ in question.options)
                for question in candidate.questions
            )
            result = await self._repository.store_generated(
                questionnaire_id, candidate, token_hashes
            )
            log_preference_event(
                "generation", "succeeded", questionnaire_id=questionnaire_id
            )
            return result
        except (PreferenceTuningError, ValidationError, ValueError, KeyError) as exc:
            return await self._fail(questionnaire_id, "generation_failed", exc)

    async def answer(self, telegram_user_id: int, callback_token: str) -> TuneState:
        try:
            state = await self._repository.record_answer(
                telegram_user_id, callback_token, self._clock.now()
            )
            log_preference_event(
                "answer",
                "accepted",
                questionnaire_id=state.questionnaire_id,
                next_ordinal=state.ordinal,
            )
        except PreferenceTuningError:
            raise
        if state.kind is not TuneStateKind.PROCESSING:
            return state

        questionnaire_id = self._required_id(state)
        try:
            result, proposal = await self._interpret_and_apply(questionnaire_id)
            log_preference_event(
                "application",
                "succeeded",
                questionnaire_id=questionnaire_id,
                change_count=len(proposal.changes),
            )
            return result
        except (PreferenceTuningError, ValidationError, ValueError, KeyError) as exc:
            return await self._fail(questionnaire_id, "interpretation_failed", exc)

    async def _interpret_and_apply(self, questionnaire_id):
        for stale_attempt in range(2):
            profile, answers = await self._repository.load_interpretation_input(
                questionnaire_id
            )
            log_preference_event(
                "interpretation",
                "started",
                questionnaire_id=questionnaire_id,
                base_profile_revision=profile.revision,
                answer_count=len(answers),
            )
            proposal = await self._validated_proposal(
                profile,
                questionnaire_id,
                answers,
            )
            if not proposal.changes:
                result = await self._repository.complete_questionnaire_no_change(
                    questionnaire_id,
                    self._clock.now(),
                )
                return result, proposal
            try:
                result = await self._repository.apply_changes(
                    questionnaire_id, proposal, self._clock.now()
                )
                return result, proposal
            except StaleProfileRevision:
                log_preference_event(
                    "application",
                    "stale",
                    questionnaire_id=questionnaire_id,
                    retry=stale_attempt,
                )
                if stale_attempt == 1:
                    raise
        raise RuntimeError("unreachable")

    async def _generate_candidate(
        self,
        context,
        questionnaire_id,
    ) -> QuestionnaireGenerationSchema:
        last_error: Exception | None = None
        for attempt in range(1, self._generation_attempts + 1):
            log_preference_event(
                "generation",
                "started",
                questionnaire_id=questionnaire_id,
                attempt=attempt,
                attempt_limit=self._generation_attempts,
                profile_revision=context.profile.revision,
                prior_answer_count=len(context.prior_answers),
                language_code=context.language_code,
            )
            raw = await self._model.generate(context)
            try:
                candidate = QuestionnaireGenerationSchema.model_validate(
                    raw,
                    strict=True,
                )
                allowed_dimensions = {
                    dimension.key
                    for dimension in available_dimensions(
                        context.prior_answers,
                        context.dimension_context,
                    )
                }
                if any(
                    question.dimension_key not in allowed_dimensions
                    for question in candidate.questions
                ):
                    raise QuestionnaireInvalid(
                        "question substantially repeats prior context"
                    )
                if self._repetition_detector is None:
                    self._quality.validate(
                        candidate,
                        tuple(item.question for item in context.prior_answers),
                    )
                else:
                    self._repetition_detector.validate(
                        candidate,
                        context.prior_answers,
                    )
                    self._quality.validate(candidate, ())
                return candidate
            except (
                QuestionnaireInvalid,
                ValidationError,
                ValueError,
                KeyError,
            ) as exc:
                last_error = exc
                log_preference_event(
                    "generation_validation",
                    "rejected",
                    questionnaire_id=questionnaire_id,
                    attempt=attempt,
                    attempt_limit=self._generation_attempts,
                    **preference_exception_context(exc),
                )
        if last_error is None:
            raise RuntimeError("generation attempts completed without a result")
        raise last_error

    async def _validated_proposal(
        self,
        profile,
        questionnaire_id,
        answers,
    ) -> PreferenceChangesSchema:
        last_error: Exception | None = None
        for attempt in range(1, self._interpretation_attempts + 1):
            try:
                raw = await self._model.propose(profile, questionnaire_id, answers)
                proposal = PreferenceChangesSchema.model_validate_json(
                    json.dumps(raw, default=str, separators=(",", ":")),
                    strict=True,
                )
                proposal = await self._resolve_questionnaire_duplicates(
                    proposal,
                    profile,
                    questionnaire_id,
                )
                if proposal.changes:
                    proposal = self._change_validator.validate(
                        proposal,
                        profile,
                        questionnaire_id,
                    )
                log_preference_event(
                    "validation",
                    "succeeded",
                    questionnaire_id=questionnaire_id,
                    attempt=attempt,
                    change_count=len(proposal.changes),
                )
                return proposal
            except (
                PreferenceProposalInvalid,
                ValidationError,
                ValueError,
                KeyError,
            ) as exc:
                last_error = exc
                log_preference_event(
                    "interpretation_validation",
                    "rejected",
                    questionnaire_id=questionnaire_id,
                    attempt=attempt,
                    attempt_limit=self._interpretation_attempts,
                    **preference_exception_context(exc),
                )
        if last_error is None:
            raise RuntimeError("interpretation attempts completed without a result")
        raise last_error

    async def _resolve_questionnaire_duplicates(
        self,
        proposal: PreferenceChangesSchema,
        profile,
        questionnaire_id,
    ) -> PreferenceChangesSchema:
        if self._duplicate_detector is None:
            return proposal
        by_id = {parameter.id: parameter for parameter in profile.parameters}
        resolved = []
        targeted_ids = {
            change.parameter_id
            for change in proposal.changes
            if hasattr(change, "parameter_id")
        }
        duplicate_count = 0
        protected_skip_count = 0
        for change in proposal.changes:
            if change.action != "create":
                resolved.append(change)
                continue
            candidates = await self._repository.duplicate_candidates(
                profile.user_id,
                change.semantic_key,
                change.name,
            )
            resolution = await self._duplicate_detector.resolve(change, candidates)
            parameter_id = resolution.equivalent_parameter_id
            if parameter_id is None:
                resolved.append(change)
                continue
            duplicate_count += 1
            parameter = by_id.get(parameter_id)
            if parameter is None:
                raise PreferenceProposalInvalid(
                    "duplicate resolution points to an unknown parameter"
                )
            if parameter.origin is not PreferenceOrigin.QUESTIONNAIRE:
                protected_skip_count += 1
                continue
            replacement = next(
                (
                    item
                    for item in rewrite_equivalent_create(change, parameter)
                    if item.parameter_id not in targeted_ids
                ),
                None,
            )
            if replacement is not None:
                targeted_ids.add(replacement.parameter_id)
                resolved.append(replacement)
        log_preference_event(
            "duplicate_resolution",
            "completed",
            questionnaire_id=questionnaire_id,
            proposed_change_count=len(proposal.changes),
            resolved_change_count=len(resolved),
            duplicate_count=duplicate_count,
            protected_skip_count=protected_skip_count,
        )
        return PreferenceChangesSchema.model_construct(
            schema_version=proposal.schema_version,
            questionnaire_id=proposal.questionnaire_id,
            base_profile_revision=proposal.base_profile_revision,
            changes=tuple(resolved),
        )

    async def _fail(
        self, questionnaire_id, error_code: str, exc: Exception
    ) -> TuneState:
        log_preference_event(
            "tuning",
            "failed",
            questionnaire_id=questionnaire_id,
            error_code=error_code,
            **preference_exception_context(exc),
        )
        return await self._repository.fail(
            questionnaire_id, error_code, self._clock.now()
        )

    @staticmethod
    def _required_id(state: TuneState):
        if state.questionnaire_id is None:
            raise RuntimeError("tune state has no questionnaire id")
        return state.questionnaire_id
