from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from anxious_news_bot.preferences.domain import (
    PreferenceAction,
    PreferenceOrigin,
    PreferenceParameter,
    ProfileSnapshot,
    SpecifyState,
    SpecifyStateKind,
)
from anxious_news_bot.preferences.errors import (
    InterpretationFailed,
    StaleProfileRevision,
)
from anxious_news_bot.preferences.services.apply_changes import (
    DeterministicPreferenceChangeValidator,
)
from anxious_news_bot.preferences.services.duplicates import DuplicateResolution
from anxious_news_bot.preferences.services.specify import ExplicitPreferenceService
from tests.fixtures.preferences import FixedClock
from tests.fixtures.ranking import DeterministicExplicitInterpreter


@dataclass(frozen=True, slots=True)
class ClaimResult:
    request_id: UUID
    replay_state: SpecifyState | None = None


class Repository:
    def __init__(self, profile: ProfileSnapshot, *, history=()) -> None:
        self.profile = profile
        self.history = tuple(history)
        self.request_id = uuid4()
        self.claims: list[tuple[int, int, str, str | None, datetime]] = []
        self.context_requests: list[UUID] = []
        self.duplicate_calls: list[tuple[UUID, str, str]] = []
        self.applied = []
        self.completed_no_change = []
        self.failed = []
        self.replay_state: SpecifyState | None = None
        self.stale_once = False
        self.apply_calls = 0
        self.transaction_open = False

    async def claim_explicit_request(
        self,
        telegram_user_id: int,
        telegram_update_id: int,
        statement: str,
        language_code: str | None,
        claimed_at: datetime,
    ) -> ClaimResult:
        self.transaction_open = True
        try:
            self.claims.append(
                (
                    telegram_user_id,
                    telegram_update_id,
                    statement,
                    language_code,
                    claimed_at,
                )
            )
            return ClaimResult(self.request_id, self.replay_state)
        finally:
            self.transaction_open = False

    async def load_explicit_context(self, request_id: UUID):
        self.transaction_open = True
        try:
            self.context_requests.append(request_id)
            return self.profile, self.history
        finally:
            self.transaction_open = False

    async def duplicate_candidates(self, user_id, semantic_key, name, *, limit=20):
        del limit
        self.duplicate_calls.append((user_id, semantic_key, name))
        return self.profile

    async def apply_explicit_changes(self, request_id, proposal, applied_at):
        self.apply_calls += 1
        if self.stale_once and self.apply_calls == 1:
            self.profile = ProfileSnapshot(
                self.profile.user_id,
                self.profile.revision + 1,
                self.profile.parameters,
            )
            raise StaleProfileRevision("profile changed during application")
        self.applied.append((request_id, proposal, applied_at))
        return SpecifyState(
            SpecifyStateKind.APPLIED,
            request_id=request_id,
            action=PreferenceAction.CREATE,
            parameter_name="Kirov city news",
            message="Saved your explicit preference for Kirov city news.",
        )

    async def complete_no_change(self, request_id, proposal_hash, completed_at):
        self.completed_no_change.append((request_id, proposal_hash, completed_at))
        return SpecifyState(
            SpecifyStateKind.NO_CHANGE,
            request_id=request_id,
            message="Your current preferences already cover Kirov city news.",
        )

    async def fail_explicit_request(self, request_id, error_code, failed_at):
        self.failed.append((request_id, error_code, failed_at))
        kind = (
            SpecifyStateKind.INVALID
            if error_code in {"proposal_invalid", "statement_invalid"}
            else SpecifyStateKind.FAILED
        )
        return SpecifyState(kind, request_id=request_id, message=error_code)


class InspectingInterpreter(DeterministicExplicitInterpreter):
    def __init__(self, proposal, repository: Repository) -> None:
        super().__init__(proposal)
        self.repository = repository
        self.histories = []

    async def interpret(
        self,
        request_id,
        statement,
        profile_snapshot,
        relevant_history,
        language_code=None,
    ):
        assert self.repository.transaction_open is False
        self.histories.append(tuple(relevant_history))
        return await super().interpret(
            request_id,
            statement,
            profile_snapshot,
            relevant_history,
        )


class DuplicateDetector:
    def __init__(self, parameter_id: UUID | None = None) -> None:
        self.parameter_id = parameter_id
        self.calls = []

    async def resolve(self, proposal, profile):
        self.calls.append((proposal.semantic_key, profile.revision))
        return DuplicateResolution(self.parameter_id)


class AdaptiveInterpreter:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository
        self.calls = 0

    async def interpret(
        self,
        request_id,
        statement,
        profile_snapshot,
        relevant_history,
        language_code=None,
    ):
        del statement, relevant_history
        self.calls += 1
        return {
            "schema_version": "1.0",
            "request_id": request_id,
            "base_profile_revision": profile_snapshot.revision,
            "changes": [
                {
                    "action": "create",
                    "semantic_key": "kirov_city_news",
                    "name": "Kirov city news",
                    "description": "Specific city reporting about Kirov.",
                    "evaluation_instructions": "Prefer relevant Kirov city reporting.",
                    "target_weight": "0.80",
                    "reason": "User explicitly asked for more Kirov city news.",
                }
            ],
        }


def _parameter(
    *,
    weight: str = "0.40",
    origin: PreferenceOrigin = PreferenceOrigin.QUESTIONNAIRE,
    active: bool = True,
) -> PreferenceParameter:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    user_id = uuid4()
    return PreferenceParameter(
        uuid4(),
        user_id,
        "kirov_city_news",
        "Kirov city news",
        "Specific city reporting about Kirov.",
        "Prefer relevant Kirov city reporting.",
        Decimal(weight),
        origin,
        active,
        now,
        now,
    )


def _service(repository, interpreter, *, duplicate_detector=None):
    return ExplicitPreferenceService(
        repository,
        interpreter,
        DeterministicPreferenceChangeValidator(),
        FixedClock(),
        duplicate_detector=duplicate_detector,
        stale_retry_limit=1,
    )


async def test_claims_request_loads_context_and_calls_interpreter_outside_transactions() -> (
    None
):
    parameter = _parameter()
    repository = Repository(
        ProfileSnapshot(parameter.user_id, 3, (parameter,)),
        history=({"action": "adjust", "parameter_name": parameter.name},),
    )
    request_id = repository.request_id
    interpreter = InspectingInterpreter(
        {
            "schema_version": "1.0",
            "request_id": request_id,
            "base_profile_revision": 3,
            "changes": [
                {
                    "action": "adjust",
                    "parameter_id": parameter.id,
                    "target_weight": "0.80",
                    "reason": "User explicitly asked for more Kirov city news.",
                }
            ],
        },
        repository,
    )

    state = await _service(repository, interpreter).specify(
        123,
        77,
        "  More Kirov city news  ",
        "en",
    )

    assert state.kind is SpecifyStateKind.APPLIED
    assert repository.claims == [
        (123, 77, "More Kirov city news", "en", FixedClock.value)
    ]
    assert repository.context_requests == [request_id]
    assert interpreter.calls == [(request_id, "More Kirov city news")]
    assert interpreter.histories == [repository.history]


async def test_replay_claim_returns_persisted_state_without_reinterpreting() -> None:
    repository = Repository(ProfileSnapshot(uuid4(), 3, ()))
    repository.replay_state = SpecifyState(
        SpecifyStateKind.APPLIED,
        request_id=repository.request_id,
        message="Saved your explicit preference for Kirov city news.",
    )
    interpreter = InspectingInterpreter({}, repository)

    state = await _service(repository, interpreter).specify(
        123,
        77,
        "More Kirov city news",
        "en",
    )

    assert state.kind is SpecifyStateKind.APPLIED
    assert interpreter.calls == []
    assert repository.applied == []


async def test_duplicate_resolution_reuses_existing_parameter_before_apply() -> None:
    parameter = _parameter(active=False)
    repository = Repository(ProfileSnapshot(parameter.user_id, 3, (parameter,)))
    interpreter = InspectingInterpreter(
        {
            "schema_version": "1.0",
            "request_id": repository.request_id,
            "base_profile_revision": 3,
            "changes": [
                {
                    "action": "create",
                    "semantic_key": parameter.semantic_key,
                    "name": parameter.name,
                    "description": parameter.description,
                    "evaluation_instructions": parameter.evaluation_instructions,
                    "target_weight": "0.80",
                    "reason": "User explicitly requested the same topic again.",
                }
            ],
        },
        repository,
    )
    duplicate_detector = DuplicateDetector(parameter.id)

    state = await _service(
        repository,
        interpreter,
        duplicate_detector=duplicate_detector,
    ).specify(123, 77, "More Kirov city news", "en")

    assert state.kind is SpecifyStateKind.APPLIED
    applied = repository.applied[-1][1]
    assert {change.action for change in applied.changes} == {"reactivate", "adjust"}
    assert duplicate_detector.calls == [(parameter.semantic_key, 3)]


async def test_noop_interpretation_completes_as_no_change() -> None:
    parameter = _parameter(weight="0.80", active=True)
    repository = Repository(ProfileSnapshot(parameter.user_id, 3, (parameter,)))
    interpreter = InspectingInterpreter(
        {
            "schema_version": "1.0",
            "request_id": repository.request_id,
            "base_profile_revision": 3,
            "changes": [
                {
                    "action": "create",
                    "semantic_key": parameter.semantic_key,
                    "name": parameter.name,
                    "description": parameter.description,
                    "evaluation_instructions": parameter.evaluation_instructions,
                    "target_weight": "0.80",
                    "reason": "User explicitly requested the same topic again.",
                }
            ],
        },
        repository,
    )

    state = await _service(
        repository,
        interpreter,
        duplicate_detector=DuplicateDetector(parameter.id),
    ).specify(123, 77, "More Kirov city news", "en")

    assert state.kind is SpecifyStateKind.NO_CHANGE
    assert repository.applied == []
    assert len(repository.completed_no_change) == 1


async def test_provider_failure_becomes_controlled_failed_state() -> None:
    repository = Repository(ProfileSnapshot(uuid4(), 3, ()))

    class FailedInterpreter:
        async def interpret(self, *args, **kwargs):
            del args, kwargs
            raise InterpretationFailed("provider unavailable")

    state = await _service(repository, FailedInterpreter()).specify(
        123,
        77,
        "More Kirov city news",
        "en",
    )

    assert state.kind is SpecifyStateKind.FAILED
    assert repository.failed[-1][1] == "interpretation_failed"


async def test_context_failure_becomes_controlled_failed_state_without_raw_logging(
    caplog,
) -> None:
    raw_statement = "Sensitive Kirov preference"

    class ContextFailureRepository(Repository):
        async def load_explicit_context(self, request_id):
            del request_id
            raise RuntimeError("database unavailable")

    repository = ContextFailureRepository(ProfileSnapshot(uuid4(), 3, ()))
    caplog.set_level(
        logging.INFO,
        logger="anxious_news_bot.preferences.observability",
    )

    state = await _service(repository, InspectingInterpreter({}, repository)).specify(
        123,
        77,
        raw_statement,
        "en",
    )

    assert state.kind is SpecifyStateKind.FAILED
    assert repository.failed[-1][1] == "context_load_failed"
    assert raw_statement not in caplog.text


async def test_duplicate_classifier_failure_becomes_controlled_failed_state() -> None:
    repository = Repository(ProfileSnapshot(uuid4(), 3, ()))
    interpreter = AdaptiveInterpreter(repository)

    class FailedDuplicateDetector:
        async def resolve(self, proposal, profile):
            del proposal, profile
            raise InterpretationFailed("classifier unavailable")

    state = await _service(
        repository,
        interpreter,
        duplicate_detector=FailedDuplicateDetector(),
    ).specify(123, 77, "More Kirov city news", "en")

    assert state.kind is SpecifyStateKind.FAILED
    assert repository.failed[-1][1] == "duplicate_detection_failed"


async def test_apply_persistence_failure_becomes_controlled_failed_state() -> None:
    class ApplyFailureRepository(Repository):
        async def apply_explicit_changes(self, request_id, proposal, applied_at):
            del request_id, proposal, applied_at
            raise RuntimeError("database unavailable")

    repository = ApplyFailureRepository(ProfileSnapshot(uuid4(), 3, ()))

    state = await _service(repository, AdaptiveInterpreter(repository)).specify(
        123,
        77,
        "More Kirov city news",
        "en",
    )

    assert state.kind is SpecifyStateKind.FAILED
    assert repository.failed[-1][1] == "application_failed"


async def test_failed_state_is_returned_when_marking_request_failed_also_fails() -> (
    None
):
    class FailureRepository(Repository):
        async def load_explicit_context(self, request_id):
            del request_id
            raise RuntimeError("database unavailable")

        async def fail_explicit_request(self, request_id, error_code, failed_at):
            del request_id, error_code, failed_at
            raise RuntimeError("database unavailable")

    repository = FailureRepository(ProfileSnapshot(uuid4(), 3, ()))

    state = await _service(repository, InspectingInterpreter({}, repository)).specify(
        123,
        77,
        "More Kirov city news",
        "en",
    )

    assert state.kind is SpecifyStateKind.FAILED
    assert state.request_id == repository.request_id
    assert state.message == "Preference update failed. Please try again soon."


async def test_validation_failure_becomes_invalid_state() -> None:
    repository = Repository(ProfileSnapshot(uuid4(), 3, ()))
    interpreter = InspectingInterpreter(
        {
            "schema_version": "1.0",
            "request_id": repository.request_id,
            "base_profile_revision": 3,
            "changes": [
                {
                    "action": "adjust",
                    "parameter_id": "not-a-uuid",
                    "target_weight": "0.80",
                    "reason": "Broken document",
                }
            ],
        },
        repository,
    )

    state = await _service(repository, interpreter).specify(
        123,
        77,
        "More Kirov city news",
        "en",
    )

    assert state.kind is SpecifyStateKind.INVALID
    assert repository.failed[-1][1] == "proposal_invalid"


async def test_specificity_validation_failure_becomes_invalid_state() -> None:
    broad = PreferenceParameter(
        uuid4(),
        uuid4(),
        "russia_news",
        "Russia news",
        "Broad reporting about Russia.",
        "Prefer Russia reporting.",
        Decimal("0.40"),
        PreferenceOrigin.QUESTIONNAIRE,
        True,
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    repository = Repository(ProfileSnapshot(broad.user_id, 3, (broad,)))
    interpreter = InspectingInterpreter(
        {
            "schema_version": "1.0",
            "request_id": repository.request_id,
            "base_profile_revision": 3,
            "changes": [
                {
                    "action": "adjust",
                    "parameter_id": broad.id,
                    "target_weight": "0.80",
                    "reason": "User explicitly asked for more Kirov city news.",
                }
            ],
        },
        repository,
    )

    state = await _service(repository, interpreter).specify(
        123,
        77,
        "More Kirov city news",
        "en",
    )

    assert state.kind is SpecifyStateKind.INVALID
    assert repository.failed[-1][1] == "proposal_invalid"


async def test_reinterprets_once_after_stale_profile_conflict() -> None:
    repository = Repository(ProfileSnapshot(uuid4(), 3, ()))
    repository.stale_once = True
    interpreter = AdaptiveInterpreter(repository)

    state = await _service(repository, interpreter).specify(
        123,
        77,
        "More Kirov city news",
        "en",
    )

    assert state.kind is SpecifyStateKind.APPLIED
    assert interpreter.calls == 2
    assert repository.apply_calls == 2
