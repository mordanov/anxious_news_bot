from __future__ import annotations

import json
import unicodedata

from pydantic import ValidationError

from anxious_news_bot.preferences.domain import SpecifyState, SpecifyStateKind
from anxious_news_bot.preferences.errors import (
    InterpretationFailed,
    PersistenceConflict,
    PreferenceProposalInvalid,
    StaleProfileRevision,
)
from anxious_news_bot.preferences.observability import log_preference_event
from anxious_news_bot.preferences.ports import (
    Clock,
    ExplicitPreferenceInterpreter,
    PreferenceRepositoryPort,
)
from anxious_news_bot.preferences.schemas import (
    CreateChangeSchema,
    ExplicitPreferenceChangesSchema,
)
from anxious_news_bot.preferences.services.apply_changes import (
    DeterministicPreferenceChangeValidator,
    proposal_hash,
)
from anxious_news_bot.preferences.services.duplicates import (
    PreferenceDuplicateDetector,
)

FAILED_MESSAGE = "Preference update failed. Please try again soon."
INVALID_MESSAGE = "I couldn't convert that into a safe preference change."


class ExplicitPreferenceService:
    def __init__(
        self,
        repository: PreferenceRepositoryPort,
        interpreter: ExplicitPreferenceInterpreter,
        change_validator: DeterministicPreferenceChangeValidator,
        clock: Clock,
        *,
        duplicate_detector: PreferenceDuplicateDetector | None = None,
        stale_retry_limit: int = 1,
        max_statement_length: int = 1000,
    ) -> None:
        self._repository = repository
        self._interpreter = interpreter
        self._change_validator = change_validator
        self._clock = clock
        self._duplicate_detector = duplicate_detector
        self._stale_retry_limit = stale_retry_limit
        self._max_statement_length = max_statement_length

    async def specify(
        self,
        telegram_user_id: int,
        telegram_update_id: int,
        statement: str,
        language_code: str | None,
    ) -> SpecifyState:
        normalized_statement = self._normalize_statement(statement)
        if (
            not normalized_statement
            or len(normalized_statement) > self._max_statement_length
        ):
            return SpecifyState(
                SpecifyStateKind.INVALID,
                message=INVALID_MESSAGE,
            )

        now = self._clock.now()
        try:
            claim = await self._repository.claim_explicit_request(
                telegram_user_id,
                telegram_update_id,
                normalized_statement,
                language_code,
                now,
            )
        except PersistenceConflict:
            return SpecifyState(
                SpecifyStateKind.INVALID,
                message=INVALID_MESSAGE,
            )
        except Exception:
            log_preference_event(
                "claim",
                "failed",
                telegram_update_id=telegram_update_id,
                error_code="request_claim_failed",
            )
            return SpecifyState(
                SpecifyStateKind.FAILED,
                message=FAILED_MESSAGE,
            )

        request_id = claim.request_id
        log_preference_event(
            "received",
            "accepted",
            request_id=request_id,
            telegram_update_id=telegram_update_id,
        )
        if claim.replay_state is not None:
            log_preference_event(
                "replay",
                "returned",
                request_id=request_id,
                state=claim.replay_state.kind.value,
            )
            return claim.replay_state

        attempts = 0
        while True:
            try:
                profile, history = await self._repository.load_explicit_context(
                    request_id
                )
            except Exception:
                log_preference_event(
                    "context",
                    "failed",
                    request_id=request_id,
                    error_code="context_load_failed",
                )
                return await self._fail_safely(
                    request_id,
                    "context_load_failed",
                )
            log_preference_event(
                "interpretation",
                "started",
                request_id=request_id,
                base_profile_revision=profile.revision,
                history_count=len(history),
            )
            try:
                raw = await self._interpreter.interpret(
                    request_id,
                    normalized_statement,
                    profile,
                    history,
                )
            except InterpretationFailed:
                log_preference_event(
                    "interpretation",
                    "failed",
                    request_id=request_id,
                    error_code="interpretation_failed",
                )
                return await self._fail_safely(
                    request_id,
                    "interpretation_failed",
                )
            except Exception:
                log_preference_event(
                    "interpretation",
                    "failed",
                    request_id=request_id,
                    error_code="interpretation_failed",
                )
                return await self._fail_safely(
                    request_id,
                    "interpretation_failed",
                )

            try:
                proposal = ExplicitPreferenceChangesSchema.model_validate_json(
                    json.dumps(raw, default=str, separators=(",", ":")),
                    strict=True,
                )
            except (ValidationError, ValueError, TypeError, KeyError):
                log_preference_event(
                    "validation",
                    "failed",
                    request_id=request_id,
                    error_code="proposal_invalid",
                )
                return await self._fail_safely(
                    request_id,
                    "proposal_invalid",
                    fallback_kind=SpecifyStateKind.INVALID,
                )

            try:
                duplicate_matches = await self._duplicate_matches(proposal, profile)
            except Exception:
                log_preference_event(
                    "duplicate",
                    "failed",
                    request_id=request_id,
                    error_code="duplicate_detection_failed",
                )
                return await self._fail_safely(
                    request_id,
                    "duplicate_detection_failed",
                )

            try:
                validated = self._change_validator.validate(
                    proposal,
                    profile,
                    request_id,
                    statement=normalized_statement,
                    duplicate_matches=duplicate_matches,
                )
            except PreferenceProposalInvalid as exc:
                if self._is_no_change(exc):
                    log_preference_event(
                        "duplicate",
                        "no_change",
                        request_id=request_id,
                    )
                    try:
                        return await self._repository.complete_no_change(
                            request_id,
                            proposal_hash(proposal),
                            self._clock.now(),
                        )
                    except Exception:
                        log_preference_event(
                            "application",
                            "failed",
                            request_id=request_id,
                            error_code="completion_failed",
                        )
                        return await self._fail_safely(
                            request_id,
                            "completion_failed",
                        )
                log_preference_event(
                    "validation",
                    "failed",
                    request_id=request_id,
                    error_code="proposal_invalid",
                )
                return await self._fail_safely(
                    request_id,
                    "proposal_invalid",
                    fallback_kind=SpecifyStateKind.INVALID,
                )
            except Exception:
                log_preference_event(
                    "validation",
                    "failed",
                    request_id=request_id,
                    error_code="validation_failed",
                )
                return await self._fail_safely(
                    request_id,
                    "validation_failed",
                )

            log_preference_event(
                "validation",
                "succeeded",
                request_id=request_id,
                change_count=len(validated.changes),
            )
            try:
                state = await self._repository.apply_explicit_changes(
                    request_id,
                    validated,
                    self._clock.now(),
                )
            except StaleProfileRevision:
                attempts += 1
                log_preference_event(
                    "stale",
                    "retrying" if attempts <= self._stale_retry_limit else "failed",
                    request_id=request_id,
                    retry=attempts,
                )
                if attempts <= self._stale_retry_limit:
                    continue
                return await self._fail_safely(
                    request_id,
                    "stale_profile_revision",
                )
            except Exception:
                log_preference_event(
                    "application",
                    "failed",
                    request_id=request_id,
                    error_code="application_failed",
                )
                return await self._fail_safely(
                    request_id,
                    "application_failed",
                )
            log_preference_event(
                "application",
                "succeeded",
                request_id=request_id,
                state=state.kind.value,
            )
            return state

    async def _fail_safely(
        self,
        request_id,
        error_code: str,
        *,
        fallback_kind: SpecifyStateKind = SpecifyStateKind.FAILED,
    ) -> SpecifyState:
        try:
            return await self._repository.fail_explicit_request(
                request_id,
                error_code,
                self._clock.now(),
            )
        except Exception:
            log_preference_event(
                "failure",
                "failed",
                request_id=request_id,
                error_code="failure_persistence_failed",
            )
            return SpecifyState(
                fallback_kind,
                request_id=request_id,
                message=(
                    INVALID_MESSAGE
                    if fallback_kind is SpecifyStateKind.INVALID
                    else FAILED_MESSAGE
                ),
            )

    async def _duplicate_matches(self, proposal, profile):
        if self._duplicate_detector is None:
            return {}
        matches: dict[int, object] = {}
        for index, change in enumerate(proposal.changes):
            if not isinstance(change, CreateChangeSchema):
                continue
            candidates = await self._repository.duplicate_candidates(
                profile.user_id,
                change.semantic_key,
                change.name,
            )
            resolution = await self._duplicate_detector.resolve(change, candidates)
            if resolution.equivalent_parameter_id is not None:
                matches[index] = resolution.equivalent_parameter_id
                log_preference_event(
                    "duplicate",
                    "reused",
                    request_id=proposal.request_id,
                    checked_by_model=resolution.checked_by_model,
                )
        return matches

    @staticmethod
    def _is_no_change(exc: PreferenceProposalInvalid) -> bool:
        message = str(exc)
        return "would not change" in message or "must change" in message

    @staticmethod
    def _normalize_statement(statement: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", statement).split())
