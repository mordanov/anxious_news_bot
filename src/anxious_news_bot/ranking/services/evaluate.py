from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
from pydantic import ValidationError

from anxious_news_bot.preferences.domain import ProfileSnapshot
from anxious_news_bot.ranking.domain import (
    ArticleEvaluation,
    ArticleEvaluationIdentity,
    EvaluationAttemptStatus,
    EvaluationStatus,
    RankingArticleSnapshot,
    RankingPreference,
)
from anxious_news_bot.ranking.errors import EvaluationError, StaleSnapshotError
from anxious_news_bot.ranking.observability import (
    log_evaluation_acceptance,
    log_evaluation_attempt,
    log_evaluation_claim,
    log_evaluation_failure,
    log_evaluation_replay,
    log_evaluation_reprocess,
    log_evaluation_stale,
    log_evaluation_validation,
)
from anxious_news_bot.ranking.ports import (
    ArticlePreferenceEvaluator,
    Clock,
    RankingRepository,
)
from anxious_news_bot.ranking.schemas import ArticlePreferenceEvaluationSchema

TRANSIENT_EVALUATION_CODES = frozenset(
    {
        "rate_limited",
        "server_error",
        "transport_failure",
    }
)


def parameter_snapshot(parameter: RankingPreference) -> dict[str, Any]:
    return {
        "id": str(parameter.id),
        "user_id": str(parameter.user_id),
        "semantic_key": parameter.semantic_key,
        "name": parameter.name,
        "description": parameter.description,
        "evaluation_instructions": parameter.evaluation_instructions,
        "weight": f"{parameter.weight:.2f}",
        "origin": parameter.origin.value,
        "effective_authority": parameter.effective_authority.value,
        "active": parameter.active,
    }


def parameter_snapshot_hash(parameter: RankingPreference) -> str:
    payload = json.dumps(
        parameter_snapshot(parameter),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def parameter_set_hash(preferences: Sequence[RankingPreference]) -> str:
    payload = json.dumps(
        [
            parameter_snapshot(parameter)
            for parameter in preferences
            if parameter.active
        ],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def validate_evaluation_document(
    raw: Mapping[str, Any],
    identity: ArticleEvaluationIdentity,
    preferences: Sequence[RankingPreference],
    *,
    run_id: UUID | None = None,
    attempt_count: int = 0,
    accepted_attempt_id: UUID | None = None,
    completed_at: datetime | None = None,
) -> ArticleEvaluation:
    try:
        schema = ArticlePreferenceEvaluationSchema.model_validate_json(
            json.dumps(raw, default=str, separators=(",", ":")),
            strict=True,
        )
    except ValidationError as exc:
        if "repeat parameter ids" in str(exc):
            raise EvaluationError(
                "evaluation output contains duplicate parameter ids",
                code="duplicate_parameter_ids",
            ) from exc
        raise
    if schema.article_id != identity.article_id:
        raise EvaluationError(
            "evaluation identity article_id mismatch",
            code="identity_mismatch",
        )
    if schema.article_analysis_id != identity.article_analysis_id:
        raise EvaluationError(
            "evaluation identity article_analysis_id mismatch",
            code="identity_mismatch",
        )
    if schema.profile_revision != identity.profile_revision:
        raise EvaluationError(
            "evaluation identity profile_revision mismatch",
            code="identity_mismatch",
        )
    if schema.parameter_set_hash != identity.parameter_set_hash:
        raise EvaluationError(
            "evaluation identity parameter_set_hash mismatch",
            code="identity_mismatch",
        )

    active_preferences = tuple(
        parameter for parameter in preferences if parameter.active
    )
    ordered_expected_ids = tuple(parameter.id for parameter in active_preferences)
    found_ids = tuple(item.parameter_id for item in schema.relevances)
    if set(found_ids) != set(ordered_expected_ids):
        raise EvaluationError(
            "relevances must cover every active parameter exactly once",
            code="parameter_coverage_mismatch",
        )

    ordered_relevances = tuple(
        next(
            item.to_domain()
            for item in schema.relevances
            if item.parameter_id == parameter_id
        )
        for parameter_id in ordered_expected_ids
    )
    return ArticleEvaluation(
        run_id=run_id or uuid4(),
        identity=identity,
        status=EvaluationStatus.COMPLETE,
        relevances=ordered_relevances,
        accepted_attempt_id=accepted_attempt_id,
        attempt_count=attempt_count,
        completed_at=completed_at,
    )


class ArticleEvaluationService:
    def __init__(
        self,
        repository: RankingRepository,
        evaluator: ArticlePreferenceEvaluator,
        clock: Clock,
        *,
        evaluator_name: str,
        evaluator_version: str,
        prompt_version: str,
        schema_version: str = "1.0",
        retry_attempts: int = 3,
    ) -> None:
        self._repository = repository
        self._evaluator = evaluator
        self._clock = clock
        self._evaluator_name = evaluator_name
        self._evaluator_version = evaluator_version
        self._prompt_version = prompt_version
        self._schema_version = schema_version
        self._retry_attempts = retry_attempts

    def build_identity(
        self,
        user_id: UUID,
        article_snapshot: RankingArticleSnapshot,
        profile_snapshot: ProfileSnapshot,
        preferences: Sequence[RankingPreference],
    ) -> ArticleEvaluationIdentity:
        active_preferences = tuple(
            parameter for parameter in preferences if parameter.active
        )
        return ArticleEvaluationIdentity(
            user_id=user_id,
            article_id=article_snapshot.article_id,
            article_analysis_id=article_snapshot.article_analysis_id,
            profile_revision=profile_snapshot.revision,
            parameter_set_hash=parameter_set_hash(active_preferences),
            schema_version=self._schema_version,
            evaluator_name=self._evaluator_name,
            evaluator_version=self._evaluator_version,
            prompt_version=self._prompt_version,
        )

    async def evaluate(self, user_id: UUID, article_id: UUID) -> ArticleEvaluation:
        (
            article_snapshot,
            profile_snapshot,
            preferences,
        ) = await self._repository.load_evaluation_context(
            user_id,
            article_id,
        )
        identity = self.build_identity(
            user_id,
            article_snapshot,
            profile_snapshot,
            preferences,
        )
        claim = await self._repository.claim_evaluation(identity)
        log_evaluation_claim(
            claim.identity,
            evaluation_run_id=claim.run_id,
            attempt_count=claim.attempt_count,
            status=claim.status.value,
        )
        if claim.status is EvaluationStatus.COMPLETE:
            log_evaluation_replay(
                claim.identity,
                evaluation_run_id=claim.run_id,
                attempt_count=claim.attempt_count,
            )
            return claim
        if claim.status is not EvaluationStatus.PENDING:
            return claim

        active_preferences = tuple(
            parameter for parameter in preferences if parameter.active
        )
        if claim.attempt_count > 0:
            log_evaluation_reprocess(
                identity,
                evaluation_run_id=claim.run_id,
                attempt_count=claim.attempt_count,
            )

        if not active_preferences:
            evaluation = ArticleEvaluation(
                run_id=claim.run_id,
                identity=identity,
                status=EvaluationStatus.COMPLETE,
                relevances=(),
                attempt_count=claim.attempt_count,
            )
            try:
                accepted = await self._repository.accept_evaluation(
                    claim.run_id,
                    None,
                    evaluation,
                )
            except StaleSnapshotError as exc:
                return await self._fail_stale(claim.run_id, identity, exc)
            log_evaluation_acceptance(
                identity,
                evaluation_run_id=accepted.run_id,
                attempt_count=accepted.attempt_count,
                relevance_count=0,
            )
            return accepted

        if claim.attempt_count >= self._retry_attempts:
            return await self._repository.fail_evaluation(
                claim.run_id,
                EvaluationStatus.INCOMPLETE.value,
                error_code="retry_limit_exhausted",
            )

        for ordinal in range(claim.attempt_count + 1, self._retry_attempts + 1):
            try:
                raw = await self._evaluator.evaluate(
                    article_snapshot,
                    profile_snapshot,
                    identity,
                )
            except Exception as exc:  # pragma: no cover - exercised by tests
                error_code = self._error_code(exc)
                transient = self._is_transient(exc)
                attempt_status = (
                    EvaluationAttemptStatus.TRANSIENT_FAILURE.value
                    if transient
                    else EvaluationAttemptStatus.FAILED.value
                )
                await self._repository.record_attempt(
                    claim.run_id,
                    ordinal,
                    None,
                    attempt_status,
                    error_code=error_code,
                )
                log_evaluation_attempt(
                    identity,
                    evaluation_run_id=claim.run_id,
                    ordinal=ordinal,
                    status=attempt_status,
                    error_code=error_code,
                )
                if transient and ordinal < self._retry_attempts:
                    continue
                final_status = (
                    EvaluationStatus.INCOMPLETE.value
                    if transient
                    else EvaluationStatus.FAILED.value
                )
                log_evaluation_failure(
                    identity,
                    evaluation_run_id=claim.run_id,
                    error_code=error_code,
                    status=final_status,
                )
                return await self._repository.fail_evaluation(
                    claim.run_id,
                    final_status,
                    error_code=error_code,
                )

            try:
                evaluation = validate_evaluation_document(
                    raw,
                    identity,
                    active_preferences,
                    run_id=claim.run_id,
                    attempt_count=ordinal,
                )
            except (EvaluationError, ValidationError) as exc:
                error_code = self._validation_error_code(exc)
                await self._repository.record_attempt(
                    claim.run_id,
                    ordinal,
                    raw,
                    EvaluationAttemptStatus.INVALID.value,
                    error_code=error_code,
                )
                log_evaluation_validation(
                    identity,
                    evaluation_run_id=claim.run_id,
                    ordinal=ordinal,
                    status="failed",
                    error_code=error_code,
                )
                log_evaluation_failure(
                    identity,
                    evaluation_run_id=claim.run_id,
                    error_code=error_code,
                    status=EvaluationStatus.INCOMPLETE.value,
                )
                return await self._repository.fail_evaluation(
                    claim.run_id,
                    EvaluationStatus.INCOMPLETE.value,
                    error_code=error_code,
                )

            log_evaluation_validation(
                identity,
                evaluation_run_id=claim.run_id,
                ordinal=ordinal,
                status="succeeded",
                relevance_count=len(evaluation.relevances),
            )
            accepted_attempt_id = await self._repository.record_attempt(
                claim.run_id,
                ordinal,
                raw,
                EvaluationAttemptStatus.ACCEPTED.value,
            )
            log_evaluation_attempt(
                identity,
                evaluation_run_id=claim.run_id,
                ordinal=ordinal,
                status=EvaluationAttemptStatus.ACCEPTED.value,
            )
            try:
                accepted = await self._repository.accept_evaluation(
                    claim.run_id,
                    accepted_attempt_id,
                    evaluation,
                )
            except StaleSnapshotError as exc:
                return await self._fail_stale(claim.run_id, identity, exc)
            log_evaluation_acceptance(
                identity,
                evaluation_run_id=accepted.run_id,
                attempt_count=accepted.attempt_count,
                relevance_count=len(accepted.relevances),
            )
            return accepted

        log_evaluation_failure(
            identity,
            evaluation_run_id=claim.run_id,
            error_code="retry_limit_exhausted",
            status=EvaluationStatus.INCOMPLETE.value,
        )
        return await self._repository.fail_evaluation(
            claim.run_id,
            EvaluationStatus.INCOMPLETE.value,
            error_code="retry_limit_exhausted",
        )

    async def _fail_stale(
        self,
        run_id: UUID,
        identity: ArticleEvaluationIdentity,
        exc: StaleSnapshotError,
    ) -> ArticleEvaluation:
        error_code = self._error_code(exc)
        log_evaluation_stale(
            identity,
            evaluation_run_id=run_id,
            error_code=error_code,
        )
        return await self._repository.fail_evaluation(
            run_id,
            EvaluationStatus.STALE.value,
            error_code=error_code,
        )

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        if isinstance(exc, EvaluationError):
            return exc.code in TRANSIENT_EVALUATION_CODES
        if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code == 429 or exc.response.status_code >= 500
        return False

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, (EvaluationError, StaleSnapshotError)):
            return exc.code
        if isinstance(exc, ValidationError):
            return "invalid_output"
        if isinstance(exc, httpx.ConnectError):
            return "transport_failure"
        if isinstance(exc, httpx.TimeoutException):
            return "transport_timeout"
        if isinstance(exc, httpx.HTTPStatusError):
            if exc.response.status_code == 429:
                return "rate_limited"
            if exc.response.status_code >= 500:
                return "server_error"
            return "request_rejected"
        return "evaluation_failed"

    @classmethod
    def _validation_error_code(cls, exc: Exception) -> str:
        if isinstance(exc, EvaluationError):
            return exc.code
        return cls._error_code(exc)


__all__ = [
    "ArticleEvaluationService",
    "TRANSIENT_EVALUATION_CODES",
    "parameter_set_hash",
    "parameter_snapshot",
    "parameter_snapshot_hash",
    "validate_evaluation_document",
]
