from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx

from anxious_news_bot.preferences.domain import (
    PreferenceOrigin,
    PreferenceParameter,
    ProfileSnapshot,
)
from anxious_news_bot.ranking.domain import (
    ArticleEvaluation,
    ArticleParameterRelevance,
    EvaluationStatus,
)
from anxious_news_bot.ranking.errors import StaleSnapshotError
from anxious_news_bot.ranking.services.evaluate import (
    ArticleEvaluationService,
    parameter_set_hash,
)
from tests.fixtures.ranking import FixedClock, article_snapshot, ranking_preference


@dataclass(frozen=True, slots=True)
class Context:
    article_snapshot: Any
    profile_snapshot: ProfileSnapshot
    preferences: tuple[Any, ...]


class Repository:
    def __init__(self, contexts: dict[tuple[UUID, UUID], Context]) -> None:
        self.contexts = contexts
        self.claims: list[Any] = []
        self.attempts: list[tuple[UUID, UUID, int, Any, str, str | None]] = []
        self.accepts: list[tuple[UUID, UUID | None, ArticleEvaluation]] = []
        self.failures: list[tuple[UUID, str, str | None]] = []
        self.runs_by_key: dict[tuple[Any, ...], ArticleEvaluation] = {}
        self.runs_by_id: dict[UUID, ArticleEvaluation] = {}
        self.stale_run_ids: set[UUID] = set()

    async def load_evaluation_context(self, user_id: UUID, article_id: UUID):
        context = self.contexts[(user_id, article_id)]
        return (
            context.article_snapshot,
            context.profile_snapshot,
            context.preferences,
        )

    async def claim_evaluation(self, identity):
        self.claims.append(identity)
        key = self._key(identity)
        existing = self.runs_by_key.get(key)
        if existing is None:
            run = ArticleEvaluation(
                run_id=uuid4(),
                identity=identity,
                status=EvaluationStatus.PENDING,
                relevances=(),
                attempt_count=0,
            )
            self._store(run)
            return run
        if existing.status in {EvaluationStatus.INCOMPLETE, EvaluationStatus.FAILED}:
            run = ArticleEvaluation(
                run_id=existing.run_id,
                identity=identity,
                status=EvaluationStatus.PENDING,
                relevances=existing.relevances,
                attempt_count=existing.attempt_count,
                accepted_attempt_id=existing.accepted_attempt_id,
                completed_at=existing.completed_at,
                error_code=existing.error_code,
            )
            self._store(run)
            return run
        return existing

    async def record_attempt(
        self,
        run_id: UUID,
        ordinal: int,
        payload,
        status: str,
        *,
        error_code: str | None = None,
    ) -> UUID:
        attempt_id = uuid4()
        self.attempts.append((attempt_id, run_id, ordinal, payload, status, error_code))
        existing = self.runs_by_id[run_id]
        self._store(
            ArticleEvaluation(
                run_id=existing.run_id,
                identity=existing.identity,
                status=EvaluationStatus.EVALUATING,
                relevances=existing.relevances,
                attempt_count=ordinal,
                accepted_attempt_id=existing.accepted_attempt_id,
                completed_at=existing.completed_at,
                error_code=existing.error_code,
            )
        )
        return attempt_id

    async def accept_evaluation(
        self,
        run_id: UUID,
        accepted_attempt_id: UUID | None,
        evaluation: ArticleEvaluation,
    ) -> ArticleEvaluation:
        if run_id in self.stale_run_ids:
            raise StaleSnapshotError("evaluation inputs changed before acceptance")
        current = self.runs_by_id[run_id]
        accepted = ArticleEvaluation(
            run_id=run_id,
            identity=evaluation.identity,
            status=EvaluationStatus.COMPLETE,
            relevances=evaluation.relevances,
            attempt_count=current.attempt_count,
            accepted_attempt_id=accepted_attempt_id,
            completed_at=FixedClock.value,
        )
        self.accepts.append((run_id, accepted_attempt_id, accepted))
        self._store(accepted)
        return accepted

    async def fail_evaluation(
        self,
        run_id: UUID,
        status: str,
        *,
        error_code: str | None = None,
    ) -> ArticleEvaluation:
        current = self.runs_by_id[run_id]
        failed = ArticleEvaluation(
            run_id=run_id,
            identity=current.identity,
            status=EvaluationStatus(status),
            relevances=current.relevances,
            attempt_count=current.attempt_count,
            accepted_attempt_id=current.accepted_attempt_id,
            completed_at=FixedClock.value,
            error_code=error_code,
        )
        self.failures.append((run_id, status, error_code))
        self._store(failed)
        return failed

    @staticmethod
    def _key(identity) -> tuple[Any, ...]:
        return (
            identity.user_id,
            identity.article_id,
            identity.article_analysis_id,
            identity.profile_revision,
            identity.parameter_set_hash,
            identity.schema_version,
            identity.evaluator_name,
            identity.evaluator_version,
            identity.prompt_version,
        )

    def _store(self, evaluation: ArticleEvaluation) -> None:
        self.runs_by_key[self._key(evaluation.identity)] = evaluation
        self.runs_by_id[evaluation.run_id] = evaluation


class SequencedEvaluator:
    def __init__(self, *behaviors) -> None:
        self.behaviors = list(behaviors)
        self.calls: list[tuple[UUID, UUID]] = []

    async def evaluate(self, article_snapshot, profile_snapshot, evaluation_identity):
        del profile_snapshot
        self.calls.append((article_snapshot.article_id, evaluation_identity.user_id))
        behavior = self.behaviors[min(len(self.calls) - 1, len(self.behaviors) - 1)]
        if isinstance(behavior, Exception):
            raise behavior
        if callable(behavior):
            return behavior(article_snapshot, evaluation_identity)
        return behavior


class BranchingEvaluator:
    def __init__(self, behaviors: dict[tuple[UUID, UUID], Any]) -> None:
        self.behaviors = dict(behaviors)
        self.calls: list[tuple[UUID, UUID]] = []

    async def evaluate(self, article_snapshot, profile_snapshot, evaluation_identity):
        del profile_snapshot
        key = (evaluation_identity.user_id, article_snapshot.article_id)
        self.calls.append(key)
        behavior = self.behaviors[key]
        if isinstance(behavior, Exception):
            raise behavior
        if callable(behavior):
            return behavior(article_snapshot, evaluation_identity)
        return behavior


def _profile_from_preferences(
    user_id: UUID,
    preferences,
    *,
    revision: int = 3,
) -> ProfileSnapshot:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return ProfileSnapshot(
        user_id=user_id,
        revision=revision,
        parameters=tuple(
            PreferenceParameter(
                id=preference.id,
                user_id=user_id,
                semantic_key=preference.semantic_key,
                name=preference.name,
                description=preference.description,
                evaluation_instructions=preference.evaluation_instructions,
                weight=preference.weight,
                origin=preference.origin,
                active=preference.active,
                created_at=now,
                updated_at=now,
            )
            for preference in preferences
        ),
    )


def _context(
    *, user_id: UUID | None = None, article_id: UUID | None = None, preferences=None
):
    resolved_user_id = user_id or uuid4()
    if preferences is None:
        resolved_preferences = (
            ranking_preference(
                parameter_id=uuid4(),
                user_id=resolved_user_id,
                semantic_key="kirov_city_news",
                name="Kirov city news",
                weight="0.80",
                origin=PreferenceOrigin.EXPLICIT,
            ),
        )
    else:
        resolved_preferences = tuple(preferences)
    article = article_snapshot(
        article_id=article_id or uuid4(), article_analysis_id=uuid4()
    )
    return Context(
        article_snapshot=article,
        profile_snapshot=_profile_from_preferences(
            resolved_user_id, resolved_preferences
        ),
        preferences=tuple(resolved_preferences),
    )


def _valid_document(preferences, *, relevances: dict[UUID, str] | None = None):
    relevance_map = relevances or {
        preference.id: "0.7500" for preference in preferences
    }

    def builder(article, identity):
        return {
            "schema_version": "1.0",
            "article_id": article.article_id,
            "article_analysis_id": article.article_analysis_id,
            "profile_revision": identity.profile_revision,
            "parameter_set_hash": identity.parameter_set_hash,
            "relevances": [
                {
                    "parameter_id": preference.id,
                    "relevance": relevance_map[preference.id],
                    "reason_code": "clear_match",
                }
                for preference in preferences
            ],
        }

    return builder


def _invalid_document(preferences):
    def builder(article, identity):
        valid = _valid_document(preferences)(article, identity)
        valid["relevances"][0]["reason_code"] = "Bad Reason"
        return valid

    return builder


def _service(repository: Repository, evaluator, *, retry_attempts: int = 3):
    return ArticleEvaluationService(
        repository,
        evaluator,
        FixedClock(),
        evaluator_name="test-evaluator",
        evaluator_version="1.0",
        prompt_version="prompt-v1",
        retry_attempts=retry_attempts,
    )


async def test_claim_and_replay_return_persisted_complete_evaluation() -> None:
    context = _context()
    repository = Repository(
        {
            (
                context.profile_snapshot.user_id,
                context.article_snapshot.article_id,
            ): context
        }
    )
    evaluator = SequencedEvaluator(_valid_document(context.preferences))
    service = _service(repository, evaluator)

    first = await service.evaluate(
        context.profile_snapshot.user_id,
        context.article_snapshot.article_id,
    )
    second = await service.evaluate(
        context.profile_snapshot.user_id,
        context.article_snapshot.article_id,
    )

    assert first.status is EvaluationStatus.COMPLETE
    assert second.status is EvaluationStatus.COMPLETE
    assert first.run_id == second.run_id
    assert len(evaluator.calls) == 1
    assert [attempt[4] for attempt in repository.attempts] == ["accepted"]


async def test_no_active_profiles_complete_without_calling_evaluator() -> None:
    user_id = uuid4()
    article_id = uuid4()
    context = _context(
        user_id=user_id,
        article_id=article_id,
        preferences=(),
    )
    repository = Repository({(user_id, article_id): context})
    evaluator = SequencedEvaluator(_valid_document(()))

    result = await _service(repository, evaluator).evaluate(user_id, article_id)

    assert result.status is EvaluationStatus.COMPLETE
    assert result.relevances == ()
    assert evaluator.calls == []
    assert repository.attempts == []


async def test_transient_failures_retry_before_accepting() -> None:
    context = _context()
    repository = Repository(
        {
            (
                context.profile_snapshot.user_id,
                context.article_snapshot.article_id,
            ): context
        }
    )
    request = httpx.Request("POST", "https://model.example/v1/chat/completions")
    evaluator = SequencedEvaluator(
        httpx.ConnectError("boom", request=request),
        _valid_document(context.preferences),
    )

    result = await _service(repository, evaluator, retry_attempts=3).evaluate(
        context.profile_snapshot.user_id,
        context.article_snapshot.article_id,
    )

    assert result.status is EvaluationStatus.COMPLETE
    assert [attempt[4] for attempt in repository.attempts] == [
        "transient_failure",
        "accepted",
    ]
    assert [attempt[2] for attempt in repository.attempts] == [1, 2]
    assert len(evaluator.calls) == 2


async def test_invalid_output_is_terminal_and_marks_evaluation_incomplete() -> None:
    context = _context()
    repository = Repository(
        {
            (
                context.profile_snapshot.user_id,
                context.article_snapshot.article_id,
            ): context
        }
    )
    evaluator = SequencedEvaluator(_invalid_document(context.preferences))

    result = await _service(repository, evaluator, retry_attempts=3).evaluate(
        context.profile_snapshot.user_id,
        context.article_snapshot.article_id,
    )

    assert result.status is EvaluationStatus.INCOMPLETE
    assert len(evaluator.calls) == 1
    assert [attempt[4] for attempt in repository.attempts] == ["invalid"]
    assert repository.failures[-1][1] == EvaluationStatus.INCOMPLETE.value


async def test_stale_inputs_mark_run_stale_after_a_valid_attempt() -> None:
    context = _context()
    repository = Repository(
        {
            (
                context.profile_snapshot.user_id,
                context.article_snapshot.article_id,
            ): context
        }
    )
    evaluator = SequencedEvaluator(_valid_document(context.preferences))
    service = _service(repository, evaluator)

    identity_hash = parameter_set_hash(context.preferences)
    pending = await repository.claim_evaluation(
        service.build_identity(
            context.profile_snapshot.user_id,
            context.article_snapshot,
            context.profile_snapshot,
            context.preferences,
        )
    )
    repository.stale_run_ids.add(pending.run_id)
    repository._store(
        ArticleEvaluation(
            run_id=pending.run_id,
            identity=pending.identity,
            status=EvaluationStatus.INCOMPLETE,
            relevances=(),
            attempt_count=0,
            error_code="reset_for_service",
        )
    )

    result = await service.evaluate(
        context.profile_snapshot.user_id,
        context.article_snapshot.article_id,
    )

    assert identity_hash == result.identity.parameter_set_hash
    assert result.status is EvaluationStatus.STALE
    assert [attempt[4] for attempt in repository.attempts] == ["accepted"]
    assert repository.failures[-1][1] == EvaluationStatus.STALE.value


async def test_failed_reprocessing_preserves_prior_valid_evidence_and_allows_later_success() -> (
    None
):
    context = _context()
    repository = Repository(
        {
            (
                context.profile_snapshot.user_id,
                context.article_snapshot.article_id,
            ): context
        }
    )
    prior_identity = None
    first_service = _service(
        repository, SequencedEvaluator(_invalid_document(context.preferences))
    )

    prior_identity = first_service.build_identity(
        context.profile_snapshot.user_id,
        context.article_snapshot,
        ProfileSnapshot(
            context.profile_snapshot.user_id,
            context.profile_snapshot.revision - 1,
            context.profile_snapshot.parameters,
        ),
        context.preferences,
    )
    prior_valid = ArticleEvaluation(
        run_id=uuid4(),
        identity=prior_identity,
        status=EvaluationStatus.COMPLETE,
        relevances=(
            ArticleParameterRelevance(
                parameter_id=context.preferences[0].id,
                relevance=Decimal("0.5000"),
                reason_code="prior_match",
            ),
        ),
        attempt_count=1,
        completed_at=FixedClock.value,
    )
    repository._store(prior_valid)

    failed = await first_service.evaluate(
        context.profile_snapshot.user_id,
        context.article_snapshot.article_id,
    )

    assert failed.status is EvaluationStatus.INCOMPLETE
    assert (
        repository.runs_by_key[repository._key(prior_identity)].status
        is EvaluationStatus.COMPLETE
    )

    second_service = _service(
        repository, SequencedEvaluator(_valid_document(context.preferences))
    )
    recovered = await second_service.evaluate(
        context.profile_snapshot.user_id,
        context.article_snapshot.article_id,
    )

    assert recovered.status is EvaluationStatus.COMPLETE
    assert [attempt[2] for attempt in repository.attempts] == [1, 2]
    assert (
        repository.runs_by_key[repository._key(prior_identity)].status
        is EvaluationStatus.COMPLETE
    )


async def test_failed_user_does_not_block_concurrently_successful_user() -> None:
    first_context = _context(user_id=uuid4(), article_id=uuid4())
    second_context = _context(user_id=uuid4(), article_id=uuid4())
    repository = Repository(
        {
            (
                first_context.profile_snapshot.user_id,
                first_context.article_snapshot.article_id,
            ): first_context,
            (
                second_context.profile_snapshot.user_id,
                second_context.article_snapshot.article_id,
            ): second_context,
        }
    )
    evaluator = BranchingEvaluator(
        {
            (
                first_context.profile_snapshot.user_id,
                first_context.article_snapshot.article_id,
            ): _invalid_document(first_context.preferences),
            (
                second_context.profile_snapshot.user_id,
                second_context.article_snapshot.article_id,
            ): _valid_document(second_context.preferences),
        }
    )
    service = _service(repository, evaluator)

    failed, succeeded = await asyncio.gather(
        service.evaluate(
            first_context.profile_snapshot.user_id,
            first_context.article_snapshot.article_id,
        ),
        service.evaluate(
            second_context.profile_snapshot.user_id,
            second_context.article_snapshot.article_id,
        ),
    )

    assert failed.status is EvaluationStatus.INCOMPLETE
    assert succeeded.status is EvaluationStatus.COMPLETE
    assert {attempt[1] for attempt in repository.attempts} == {
        failed.run_id,
        succeeded.run_id,
    }
