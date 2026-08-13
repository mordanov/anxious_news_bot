from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from anxious_news_bot.news.domain import DecisionOutcome
from anxious_news_bot.preferences.domain import (
    PreferenceOrigin,
    PreferenceParameter,
    ProfileSnapshot,
)
from anxious_news_bot.ranking.domain import (
    ArticleEvaluation,
    ArticleEvaluationIdentity,
    ArticleParameterRelevance,
    ContributionSnapshot,
    EligibilityReason,
    EvaluationStatus,
    FactorSnapshot,
    PersonalState,
    RankingArticleSnapshot,
    RankingConfiguration,
    RankingIdentity,
    RankingPreference,
    RankingRecord,
    RankingResult,
    RankingRetentionResult,
    RetentionPolicy,
    SelectionOutcome,
    SelectionReason,
)

_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_DIGEST_C = "c" * 64


class FixedClock:
    value = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


class DeterministicExplicitInterpreter:
    def __init__(self, proposal: Mapping[str, Any]) -> None:
        self._proposal = dict(proposal)
        self.calls: list[tuple[UUID, str]] = []

    async def interpret(
        self,
        request_id: UUID,
        statement: str,
        profile_snapshot: ProfileSnapshot,
        relevant_history: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        del profile_snapshot, relevant_history
        self.calls.append((request_id, statement))
        return dict(self._proposal)


class DeterministicArticlePreferenceEvaluator:
    def __init__(self, document: Mapping[str, Any]) -> None:
        self._document = dict(document)
        self.calls: list[tuple[UUID, UUID]] = []

    async def evaluate(
        self,
        article_snapshot: RankingArticleSnapshot,
        profile_snapshot: ProfileSnapshot,
        evaluation_identity: ArticleEvaluationIdentity,
    ) -> Mapping[str, Any]:
        del profile_snapshot, evaluation_identity
        self.calls.append(
            (article_snapshot.article_id, article_snapshot.article_analysis_id)
        )
        return dict(self._document)


class StaticRankingConfigurationProvider:
    def __init__(
        self,
        configuration: RankingConfiguration | None = None,
    ) -> None:
        self.configuration = configuration or ranking_configuration()

    def current(self) -> RankingConfiguration:
        return self.configuration


class StubRankingRepository:
    def __init__(self) -> None:
        self.claimed_evaluation: ArticleEvaluationIdentity | None = None
        self.claimed_ranking: RankingIdentity | None = None
        self.evaluation: ArticleEvaluation | None = None
        self.attempts: list[
            tuple[UUID, int, Mapping[str, Any] | None, str, str | None]
        ] = []
        self.snapshot = (
            ranking_configuration(),
            (ranking_preference(),),
            (article_snapshot(),),
            (article_evaluation(),),
        )
        self.persisted_result: RankingResult | None = None
        self.marked: tuple[RankingIdentity, str, str | None] | None = None
        self.retention_result = RankingRetentionResult()

    async def claim_evaluation(
        self,
        identity: ArticleEvaluationIdentity,
    ) -> ArticleEvaluation:
        self.claimed_evaluation = identity
        if self.evaluation is not None:
            return self.evaluation
        self.evaluation = article_evaluation(
            identity=identity,
            status=EvaluationStatus.PENDING,
            relevances=(),
            attempt_count=0,
        )
        return self.evaluation

    async def load_evaluation_context(
        self,
        user_id: UUID,
        article_id: UUID,
    ) -> tuple[RankingArticleSnapshot, ProfileSnapshot, tuple[RankingPreference, ...]]:
        del article_id
        return (
            article_snapshot(),
            profile_snapshot(user_id=user_id),
            (ranking_preference(user_id=user_id),),
        )

    async def record_attempt(
        self,
        run_id: UUID,
        ordinal: int,
        payload: Mapping[str, Any] | None,
        status: str,
        *,
        error_code: str | None = None,
    ) -> UUID:
        self.attempts.append((run_id, ordinal, payload, status, error_code))
        return uuid4()

    async def accept_evaluation(
        self,
        run_id: UUID,
        accepted_attempt_id: UUID | None,
        evaluation: ArticleEvaluation,
    ) -> ArticleEvaluation:
        del run_id, accepted_attempt_id
        self.evaluation = evaluation
        return evaluation

    async def fail_evaluation(
        self,
        run_id: UUID,
        status: str,
        *,
        error_code: str | None = None,
    ) -> ArticleEvaluation:
        del run_id, status, error_code
        if self.evaluation is None:
            self.evaluation = article_evaluation(status=EvaluationStatus.FAILED)
        return self.evaluation

    async def load_ranking_snapshot(self, identity: RankingIdentity):
        self.claimed_ranking = identity
        return self.snapshot

    async def find_complete_run(
        self, identity: RankingIdentity
    ) -> RankingResult | None:
        del identity
        return self.persisted_result

    async def persist_complete_run(self, result: RankingResult) -> RankingResult:
        self.persisted_result = result
        return result

    async def mark_stale_or_failed(
        self,
        identity: RankingIdentity,
        status: str,
        *,
        error_code: str | None = None,
    ) -> RankingResult | None:
        self.marked = (identity, status, error_code)
        return self.persisted_result

    async def cleanup(
        self,
        now: datetime,
        policy: RetentionPolicy,
    ) -> RankingRetentionResult:
        del now, policy
        return self.retention_result


def preference_parameter(
    *,
    parameter_id: UUID | None = None,
    user_id: UUID | None = None,
    semantic_key: str = "local_news",
    name: str = "Local news",
    weight: str = "0.75",
    origin: PreferenceOrigin = PreferenceOrigin.EXPLICIT,
    active: bool = True,
) -> PreferenceParameter:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return PreferenceParameter(
        id=parameter_id or uuid4(),
        user_id=user_id or uuid4(),
        semantic_key=semantic_key,
        name=name,
        description=f"Specific interest in {name.lower()}",
        evaluation_instructions=f"Prefer articles relevant to {name.lower()}",
        weight=Decimal(weight),
        origin=origin,
        active=active,
        created_at=now,
        updated_at=now,
    )


def profile_snapshot(
    *,
    user_id: UUID | None = None,
    revision: int = 3,
    parameters: Sequence[PreferenceParameter] | None = None,
) -> ProfileSnapshot:
    resolved_user_id = user_id or uuid4()
    if parameters is None:
        parameters = (preference_parameter(user_id=resolved_user_id),)
    return ProfileSnapshot(
        user_id=resolved_user_id,
        revision=revision,
        parameters=tuple(parameters),
    )


def ranking_preference(
    *,
    parameter_id: UUID | None = None,
    user_id: UUID | None = None,
    semantic_key: str = "local_news",
    name: str = "Local news",
    description: str | None = None,
    evaluation_instructions: str | None = None,
    weight: str = "0.75",
    origin: PreferenceOrigin = PreferenceOrigin.EXPLICIT,
    effective_authority: PreferenceOrigin = PreferenceOrigin.EXPLICIT,
    active: bool = True,
) -> RankingPreference:
    resolved_user_id = user_id or uuid4()
    return RankingPreference(
        id=parameter_id or uuid4(),
        user_id=resolved_user_id,
        semantic_key=semantic_key,
        name=name,
        description=description or f"Specific interest in {name.lower()}",
        evaluation_instructions=(
            evaluation_instructions or f"Prefer articles relevant to {name.lower()}"
        ),
        weight=Decimal(weight),
        origin=origin,
        effective_authority=effective_authority,
        active=active,
    )


def evaluation_identity(
    *,
    user_id: UUID | None = None,
    article_id: UUID | None = None,
    article_analysis_id: UUID | None = None,
    profile_revision: int = 3,
) -> ArticleEvaluationIdentity:
    return ArticleEvaluationIdentity(
        user_id=user_id or uuid4(),
        article_id=article_id or uuid4(),
        article_analysis_id=article_analysis_id or uuid4(),
        profile_revision=profile_revision,
        parameter_set_hash=_DIGEST_A,
        schema_version="1.0",
        evaluator_name="test-evaluator",
        evaluator_version="1.0",
        prompt_version="1.0",
    )


def article_evaluation(
    *,
    identity: ArticleEvaluationIdentity | None = None,
    status: EvaluationStatus = EvaluationStatus.COMPLETE,
    parameter_id: UUID | None = None,
    relevance: str = "0.7500",
    run_id: UUID | None = None,
    relevances: tuple[ArticleParameterRelevance, ...] | None = None,
    attempt_count: int = 1,
) -> ArticleEvaluation:
    resolved_identity = identity or evaluation_identity()
    return ArticleEvaluation(
        run_id=run_id or uuid4(),
        identity=resolved_identity,
        status=status,
        relevances=relevances
        if relevances is not None
        else (
            ArticleParameterRelevance(
                parameter_id=parameter_id or uuid4(),
                relevance=Decimal(relevance),
                reason_code="clear_match",
            ),
        ),
        attempt_count=attempt_count,
    )


def ranking_configuration() -> RankingConfiguration:
    return RankingConfiguration(
        version="1.0",
        tie_policy_version="1.0",
        retention_policy_version="1.0",
        personal_coefficient=Decimal("0.45000"),
        importance_coefficient=Decimal("0.20000"),
        freshness_coefficient=Decimal("0.15000"),
        quality_coefficient=Decimal("0.10000"),
        novelty_coefficient=Decimal("0.10000"),
        freshness_horizon_seconds=259200,
        future_tolerance_seconds=300,
        minimum_source_quality=Decimal("0.35000"),
        maximum_candidate_count=500,
        event_cap=2,
        topic_cap=3,
        source_cap=3,
        explicit_weight_threshold=Decimal("0.75"),
        explicit_relevance_threshold=Decimal("0.6000"),
        explanation_contribution_limit=3,
    )


def article_snapshot(
    *,
    article_id: UUID | None = None,
    article_analysis_id: UUID | None = None,
    source_id: UUID | None = None,
    evaluation_run_id: UUID | None = None,
    topic_key: str = "local",
    published_at: datetime | None = datetime(2026, 1, 1, tzinfo=UTC),
    duplicate_outcome: DecisionOutcome | None = DecisionOutcome.DISTINCT,
    importance_score: Decimal = Decimal("0.8000"),
    novelty_score: Decimal = Decimal("0.4000"),
    source_quality_score: Decimal = Decimal("0.9000"),
    title: str = "Local transport update",
    summary: str | None = "A short summary about local transport.",
    normalized_text: str = "Local transport and city council updates.",
    language_code: str = "en",
) -> RankingArticleSnapshot:
    return RankingArticleSnapshot(
        article_id=article_id or uuid4(),
        article_analysis_id=article_analysis_id or uuid4(),
        source_id=source_id or uuid4(),
        event_group_id=uuid4(),
        topic_key=topic_key,
        published_at=published_at,
        importance_score=importance_score,
        novelty_score=novelty_score,
        source_quality_score=source_quality_score,
        duplicate_outcome=duplicate_outcome,
        title=title,
        summary=summary,
        normalized_text=normalized_text,
        language_code=language_code,
        evaluation_run_id=evaluation_run_id,
    )


def factor_snapshot(
    *,
    importance: str = "0.80000000",
    freshness: str = "0.75000000",
    quality: str = "0.90000000",
    novelty: str = "0.40000000",
) -> FactorSnapshot:
    return FactorSnapshot(
        importance=Decimal(importance),
        freshness=Decimal(freshness),
        quality=Decimal(quality),
        novelty=Decimal(novelty),
    )


def contribution_snapshot(
    *,
    parameter_id: UUID | None = None,
    name: str = "Local news",
    origin: PreferenceOrigin = PreferenceOrigin.EXPLICIT,
    effective_authority: PreferenceOrigin = PreferenceOrigin.EXPLICIT,
    weight: str = "0.75",
    relevance: str = "0.8000",
    contribution: str = "0.60000000",
) -> ContributionSnapshot:
    return ContributionSnapshot(
        parameter_id=parameter_id or uuid4(),
        parameter_name=name,
        origin=origin,
        effective_authority=effective_authority,
        weight=Decimal(weight),
        relevance=Decimal(relevance),
        contribution=Decimal(contribution),
    )


def ranking_record(
    *,
    article_id: UUID | None = None,
    article_analysis_id: UUID | None = None,
    source_id: UUID | None = None,
    event_group_id: UUID | None = None,
    topic_key: str | None = "local",
    published_at: datetime | None = datetime(2026, 1, 1, tzinfo=UTC),
    evaluation_run_id: UUID | None = None,
    personal_state: PersonalState = PersonalState.COMPLETE,
    personal_numerator: str = "0.60000000",
    personal_denominator: str = "0.80000000",
    personal_signed: str = "0.75000000",
    personal_factor: str = "0.87500000",
    factors: FactorSnapshot | None = None,
    unrounded_score: str = "0.8123456789012345",
    final_score: str = "0.81234568",
    eligible: bool = True,
    eligibility_reason: EligibilityReason = EligibilityReason.ELIGIBLE,
    explicit_protected: bool = False,
    explicit_veto: bool = False,
    selection: SelectionOutcome | None = None,
    contributions: Sequence[ContributionSnapshot] = (),
    initial_position: int = 1,
) -> RankingRecord:
    resolved_selection = selection or SelectionOutcome(
        selected=False,
        reason=(
            SelectionReason.NOT_EVALUATED if eligible else SelectionReason.INELIGIBLE
        ),
        explicit_protected=explicit_protected,
    )
    return RankingRecord(
        article_id=article_id or uuid4(),
        article_analysis_id=article_analysis_id or uuid4(),
        source_id=source_id or uuid4(),
        event_group_id=event_group_id,
        topic_key=topic_key,
        published_at=published_at,
        evaluation_run_id=evaluation_run_id or uuid4(),
        personal_state=personal_state,
        personal_numerator=Decimal(personal_numerator),
        personal_denominator=Decimal(personal_denominator),
        personal_signed=Decimal(personal_signed),
        personal_factor=Decimal(personal_factor),
        factors=factors or factor_snapshot(),
        unrounded_score=Decimal(unrounded_score),
        final_score=Decimal(final_score),
        eligible=eligible,
        eligibility_reason=eligibility_reason,
        explicit_protected=explicit_protected,
        explicit_veto=explicit_veto,
        selection=resolved_selection,
        contributions=tuple(contributions),
        initial_position=initial_position,
    )


def ranking_identity(
    *,
    user_id: UUID | None = None,
    request_id: str = "digest-001",
    requested_count: int = 10,
) -> RankingIdentity:
    return RankingIdentity(
        request_id=request_id,
        user_id=user_id or uuid4(),
        profile_revision=3,
        candidate_set_hash=_DIGEST_B,
        configuration_version="1.0",
        ranking_at=datetime(2026, 1, 1, tzinfo=UTC),
        requested_count=requested_count,
    )


__all__ = [
    "DeterministicArticlePreferenceEvaluator",
    "DeterministicExplicitInterpreter",
    "FixedClock",
    "StaticRankingConfigurationProvider",
    "StubRankingRepository",
    "article_evaluation",
    "article_snapshot",
    "contribution_snapshot",
    "evaluation_identity",
    "factor_snapshot",
    "preference_parameter",
    "profile_snapshot",
    "ranking_configuration",
    "ranking_identity",
    "ranking_preference",
    "ranking_record",
]
