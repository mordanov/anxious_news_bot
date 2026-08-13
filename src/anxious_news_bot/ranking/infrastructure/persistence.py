from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, null, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from anxious_news_bot.infrastructure.database import Database
from anxious_news_bot.news.domain import AnalysisStatus, DecisionOutcome
from anxious_news_bot.news.infrastructure.models import (
    ArticleAnalysis,
    DeduplicationDecision,
    NewsSource,
    NormalizedArticle,
)
from anxious_news_bot.preferences.domain import (
    ExplicitRequestStatus,
    PreferenceParameter,
    ProfileSnapshot,
)
from anxious_news_bot.preferences.infrastructure.models import (
    ApplicationUser,
    ExplicitPreferenceRequest,
    PreferenceEvidence,
    PreferenceProfile,
)
from anxious_news_bot.preferences.infrastructure.models import (
    PreferenceParameter as PreferenceParameterModel,
)
from anxious_news_bot.preferences.services.authority import derive_effective_authority
from anxious_news_bot.ranking.domain import (
    ArticleEvaluation,
    ArticleEvaluationIdentity,
    ArticleParameterRelevance,
    ContributionSnapshot,
    DeliveryArticle,
    EligibilityReason,
    EvaluationAttemptStatus,
    EvaluationStatus,
    FactorSnapshot,
    RankingArticleSnapshot,
    RankingConfiguration,
    RankingIdentity,
    RankingPreference,
    RankingRecord,
    RankingResult,
    RankingRetentionResult,
    RankingStatus,
    RetentionPolicy,
    SelectionOutcome,
    SelectionReason,
)
from anxious_news_bot.ranking.errors import (
    EvaluationError,
    RankingConfigurationError,
    RankingRunError,
    StaleSnapshotError,
)
from anxious_news_bot.ranking.infrastructure import models
from anxious_news_bot.ranking.services.configuration import (
    canonical_configuration_hash,
)
from anxious_news_bot.ranking.services.evaluate import (
    parameter_set_hash,
    parameter_snapshot_hash,
)
from anxious_news_bot.ranking.services.explain import top_contributions
from anxious_news_bot.ranking.services.rank import candidate_snapshot_hash


class SQLAlchemyRankingRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def resolve_user_id(self, telegram_user_id: int) -> UUID | None:
        async with self._database.session() as session:
            return await session.scalar(
                select(ApplicationUser.id).where(
                    ApplicationUser.telegram_user_id == telegram_user_id
                )
            )

    async def has_active_nonzero_preferences(self, user_id: UUID) -> bool:
        async with self._database.session() as session:
            return bool(
                await session.scalar(
                    select(PreferenceParameterModel.id)
                    .where(
                        PreferenceParameterModel.user_id == user_id,
                        PreferenceParameterModel.active.is_(True),
                        PreferenceParameterModel.weight != Decimal("0.00"),
                    )
                    .limit(1)
                )
            )

    async def prepare_delivery_candidates(
        self,
        *,
        limit: int,
        ranking_at: datetime,
        freshness_horizon_seconds: int,
    ) -> tuple[UUID, ...]:
        cutoff = ranking_at - timedelta(seconds=freshness_horizon_seconds)
        async with self._database.session() as session:
            rows = (
                await session.execute(
                    select(NormalizedArticle, NewsSource.quality_score)
                    .join(
                        NewsSource,
                        NewsSource.id == NormalizedArticle.primary_source_id,
                    )
                    .where(
                        NormalizedArticle.published_at.is_not(None),
                        NormalizedArticle.published_at >= cutoff,
                        NormalizedArticle.published_at <= ranking_at,
                    )
                    .order_by(
                        NormalizedArticle.published_at.desc(),
                        NormalizedArticle.id,
                    )
                    .limit(limit)
                )
            ).all()
            article_ids = tuple(article.id for article, _ in rows)
            analyses = await self._latest_analyses_by_article(session, article_ids)
            for article, source_quality in rows:
                existing = analyses.get(article.id)
                if existing is not None and existing.status is AnalysisStatus.COMPLETE:
                    continue
                topic = self._baseline_topic(article.topic_metadata)
                await session.execute(
                    insert(ArticleAnalysis)
                    .values(
                        article_id=article.id,
                        status=AnalysisStatus.COMPLETE,
                        schema_version="1.0",
                        analyzer_name="deterministic-baseline",
                        analyzer_version="1.0",
                        topics=[topic] if topic else [],
                        importance_score=Decimal("0.5000"),
                        novelty_score=Decimal("0.5000"),
                        source_quality_score=Decimal(source_quality)
                        if source_quality is not None
                        else Decimal("0.5000"),
                        semantic_metadata={"basis": "delivery_baseline"},
                        created_at=ranking_at,
                    )
                    .on_conflict_do_nothing(constraint="uq_article_analyses_version")
                )
            return article_ids

    async def load_delivery_articles(
        self,
        article_ids: Sequence[UUID],
    ) -> tuple[DeliveryArticle, ...]:
        ids = tuple(article_ids)
        if not ids:
            return ()
        async with self._database.session() as session:
            rows = (
                await session.execute(
                    select(NormalizedArticle, NewsSource.name)
                    .join(
                        NewsSource,
                        NewsSource.id == NormalizedArticle.primary_source_id,
                    )
                    .where(NormalizedArticle.id.in_(ids))
                )
            ).all()
        by_id = {
            article.id: DeliveryArticle(
                article_id=article.id,
                title=article.title,
                summary=article.summary,
                canonical_url=article.canonical_url,
                source_name=source_name,
                published_at=article.published_at,
            )
            for article, source_name in rows
            if article.published_at is not None
        }
        return tuple(by_id[article_id] for article_id in ids if article_id in by_id)

    async def claim_evaluation(
        self,
        identity: ArticleEvaluationIdentity,
    ) -> ArticleEvaluation:
        async with self._database.session() as session:
            inserted_id = (
                await session.execute(
                    insert(models.ArticlePreferenceEvaluationRun)
                    .values(
                        user_id=identity.user_id,
                        article_id=identity.article_id,
                        article_analysis_id=identity.article_analysis_id,
                        profile_revision=identity.profile_revision,
                        parameter_set_hash=identity.parameter_set_hash,
                        schema_version=identity.schema_version,
                        evaluator_name=identity.evaluator_name,
                        evaluator_version=identity.evaluator_version,
                        prompt_version=identity.prompt_version,
                        status=EvaluationStatus.EVALUATING,
                        attempt_count=0,
                        updated_at=datetime.now(UTC),
                    )
                    .on_conflict_do_nothing(
                        constraint="uq_article_preference_evaluation_runs_version"
                    )
                    .returning(models.ArticlePreferenceEvaluationRun.id)
                )
            ).scalar_one_or_none()
            if inserted_id is not None:
                return ArticleEvaluation(
                    run_id=inserted_id,
                    identity=identity,
                    status=EvaluationStatus.PENDING,
                    relevances=(),
                    attempt_count=0,
                )

            row = await session.scalar(
                select(models.ArticlePreferenceEvaluationRun)
                .where(
                    models.ArticlePreferenceEvaluationRun.user_id == identity.user_id,
                    models.ArticlePreferenceEvaluationRun.article_id
                    == identity.article_id,
                    models.ArticlePreferenceEvaluationRun.article_analysis_id
                    == identity.article_analysis_id,
                    models.ArticlePreferenceEvaluationRun.profile_revision
                    == identity.profile_revision,
                    models.ArticlePreferenceEvaluationRun.parameter_set_hash
                    == identity.parameter_set_hash,
                    models.ArticlePreferenceEvaluationRun.schema_version
                    == identity.schema_version,
                    models.ArticlePreferenceEvaluationRun.evaluator_name
                    == identity.evaluator_name,
                    models.ArticlePreferenceEvaluationRun.evaluator_version
                    == identity.evaluator_version,
                    models.ArticlePreferenceEvaluationRun.prompt_version
                    == identity.prompt_version,
                )
                .options(selectinload(models.ArticlePreferenceEvaluationRun.relevances))
                .with_for_update()
            )
            if row is None:
                raise EvaluationError(
                    "evaluation claim failed",
                    code="claim_failed",
                )
            if row.status is EvaluationStatus.COMPLETE:
                return self._domain_evaluation(row)
            if row.status in (EvaluationStatus.INCOMPLETE, EvaluationStatus.FAILED):
                row.status = EvaluationStatus.EVALUATING
                row.error_code = None
                row.updated_at = datetime.now(UTC)
                await session.flush()
                return ArticleEvaluation(
                    run_id=row.id,
                    identity=self._identity_from_row(row),
                    status=EvaluationStatus.PENDING,
                    relevances=(),
                    attempt_count=row.attempt_count,
                )
            return ArticleEvaluation(
                run_id=row.id,
                identity=self._identity_from_row(row),
                status=row.status,
                relevances=(),
                attempt_count=row.attempt_count,
                accepted_attempt_id=row.accepted_attempt_id,
                completed_at=row.completed_at,
                error_code=row.error_code,
            )

    async def load_evaluation_context(
        self,
        user_id: UUID,
        article_id: UUID,
    ) -> tuple[RankingArticleSnapshot, ProfileSnapshot, tuple[RankingPreference, ...]]:
        async with self._database.session() as session:
            profile = await session.get(PreferenceProfile, user_id)
            if profile is None:
                raise EvaluationError(
                    "preference profile is missing", code="missing_profile"
                )

            article = await session.get(NormalizedArticle, article_id)
            if article is None:
                raise EvaluationError("article is missing", code="missing_article")

            analysis = await self._latest_complete_analysis(session, article_id)
            if analysis is None:
                raise EvaluationError(
                    "article analysis is missing",
                    code="missing_article_analysis",
                )

            duplicate_outcome = await self._latest_duplicate_outcome(
                session, article_id
            )
            profile_snapshot = await self._profile_snapshot(
                session, user_id, profile.revision
            )
            preferences = await self._active_preferences(session, user_id)
            topic_key = analysis.topics[0] if analysis.topics else None
            article_snapshot = RankingArticleSnapshot(
                article_id=article.id,
                article_analysis_id=analysis.id,
                source_id=article.primary_source_id,
                event_group_id=article.event_group_id,
                topic_key=topic_key,
                published_at=article.published_at,
                importance_score=Decimal(analysis.importance_score)
                if analysis.importance_score is not None
                else None,
                novelty_score=Decimal(analysis.novelty_score)
                if analysis.novelty_score is not None
                else None,
                source_quality_score=Decimal(analysis.source_quality_score)
                if analysis.source_quality_score is not None
                else None,
                duplicate_outcome=duplicate_outcome,
                title=article.title,
                summary=article.summary,
                normalized_text=article.normalized_text,
                language_code=article.language_code,
            )
            return article_snapshot, profile_snapshot, preferences

    async def record_attempt(
        self,
        run_id: UUID,
        ordinal: int,
        payload: Mapping[str, Any] | None,
        status: str,
        *,
        error_code: str | None = None,
    ) -> UUID:
        async with self._database.session() as session:
            run = await session.scalar(
                select(models.ArticlePreferenceEvaluationRun)
                .where(models.ArticlePreferenceEvaluationRun.id == run_id)
                .with_for_update()
            )
            if run is None:
                raise EvaluationError(
                    "unknown evaluation run", code="unknown_evaluation_run"
                )

            now = datetime.now(UTC)
            attempt = models.ArticlePreferenceEvaluationAttempt(
                run_id=run_id,
                ordinal=ordinal,
                response_hash=self._json_hash(payload),
                raw_response=self._jsonable(payload),
                status=EvaluationAttemptStatus(status),
                error_code=error_code[:100] if error_code else None,
                started_at=now,
                completed_at=now,
            )
            session.add(attempt)
            run.status = EvaluationStatus.EVALUATING
            run.attempt_count = max(run.attempt_count, ordinal)
            run.error_code = error_code[:100] if error_code else None
            run.updated_at = now
            await session.flush()
            return attempt.id

    async def accept_evaluation(
        self,
        run_id: UUID,
        accepted_attempt_id: UUID | None,
        evaluation: ArticleEvaluation,
    ) -> ArticleEvaluation:
        async with self._database.session() as session:
            run = await session.scalar(
                select(models.ArticlePreferenceEvaluationRun)
                .where(models.ArticlePreferenceEvaluationRun.id == run_id)
                .options(selectinload(models.ArticlePreferenceEvaluationRun.relevances))
                .with_for_update()
            )
            if run is None:
                raise EvaluationError(
                    "unknown evaluation run", code="unknown_evaluation_run"
                )
            if run.status is EvaluationStatus.COMPLETE:
                return self._domain_evaluation(run)

            if run.user_id != evaluation.identity.user_id:
                raise EvaluationError(
                    "evaluation user does not match run", code="identity_mismatch"
                )
            if run.article_id != evaluation.identity.article_id:
                raise EvaluationError(
                    "evaluation article does not match run", code="identity_mismatch"
                )
            if run.article_analysis_id != evaluation.identity.article_analysis_id:
                raise EvaluationError(
                    "evaluation analysis does not match run",
                    code="identity_mismatch",
                )
            if run.profile_revision != evaluation.identity.profile_revision:
                raise EvaluationError(
                    "evaluation profile revision does not match run",
                    code="identity_mismatch",
                )
            if run.parameter_set_hash != evaluation.identity.parameter_set_hash:
                raise EvaluationError(
                    "evaluation parameter set does not match run",
                    code="identity_mismatch",
                )

            await self._ensure_current_versions(session, run)
            active_preferences = await self._active_preferences(session, run.user_id)
            if run.parameter_set_hash != parameter_set_hash(active_preferences):
                await self._mark_stale(session, run, "parameter_set_changed")
                raise StaleSnapshotError(
                    "evaluation parameter set changed before acceptance",
                    code="parameter_set_changed",
                )

            expected_ids = tuple(parameter.id for parameter in active_preferences)
            actual_ids = tuple(
                relevance.parameter_id for relevance in evaluation.relevances
            )
            if set(expected_ids) != set(actual_ids):
                raise EvaluationError(
                    "relevances must cover every active parameter exactly once",
                    code="parameter_coverage_mismatch",
                )
            if run.relevances:
                raise EvaluationError(
                    "evaluation run already has accepted relevance rows",
                    code="evaluation_state_conflict",
                )
            if accepted_attempt_id is not None:
                attempt = await session.get(
                    models.ArticlePreferenceEvaluationAttempt,
                    accepted_attempt_id,
                )
                if attempt is None or attempt.run_id != run_id:
                    raise EvaluationError(
                        "accepted attempt does not belong to evaluation run",
                        code="accepted_attempt_mismatch",
                    )

            preference_map = {
                parameter.id: parameter for parameter in active_preferences
            }
            for relevance in evaluation.relevances:
                parameter = preference_map[relevance.parameter_id]
                session.add(
                    models.ArticleParameterRelevance(
                        evaluation_run_id=run.id,
                        parameter_id=parameter.id,
                        parameter_snapshot_hash=parameter_snapshot_hash(parameter),
                        relevance=relevance.relevance,
                        reason_code=relevance.reason_code,
                    )
                )

            completed_at = datetime.now(UTC)
            run.accepted_attempt_id = accepted_attempt_id
            run.status = EvaluationStatus.COMPLETE
            run.error_code = None
            run.completed_at = completed_at
            run.updated_at = completed_at
            await session.flush()
            await session.refresh(run, attribute_names=["relevances"])
            return self._domain_evaluation(run)

    async def fail_evaluation(
        self,
        run_id: UUID,
        status: str,
        *,
        error_code: str | None = None,
    ) -> ArticleEvaluation:
        async with self._database.session() as session:
            run = await session.scalar(
                select(models.ArticlePreferenceEvaluationRun)
                .where(models.ArticlePreferenceEvaluationRun.id == run_id)
                .options(selectinload(models.ArticlePreferenceEvaluationRun.relevances))
                .with_for_update()
            )
            if run is None:
                raise EvaluationError(
                    "unknown evaluation run", code="unknown_evaluation_run"
                )
            if run.status is EvaluationStatus.COMPLETE:
                return self._domain_evaluation(run)

            completed_at = datetime.now(UTC)
            run.status = EvaluationStatus(status)
            run.error_code = error_code[:100] if error_code else None
            run.completed_at = completed_at
            run.updated_at = completed_at
            await session.flush()
            return self._domain_evaluation(run)

    async def load_ranking_snapshot(
        self,
        user_id: UUID,
        candidate_article_ids: tuple[UUID, ...] | list[UUID],
    ) -> tuple[
        int,
        tuple[RankingPreference, ...],
        tuple[RankingArticleSnapshot, ...],
        tuple[ArticleEvaluation, ...],
    ]:
        candidate_ids = tuple(candidate_article_ids)
        async with self._database.session() as session:
            profile = await session.get(PreferenceProfile, user_id)
            if profile is None:
                raise RankingRunError(
                    "preference profile is missing",
                    code="missing_profile",
                )

            preferences = await self._active_preferences(session, user_id)
            parameter_hash = parameter_set_hash(preferences)
            articles = await self._ranking_articles(
                session,
                candidate_ids,
            )
            latest_analyses = await self._latest_analyses_by_article(
                session,
                candidate_ids,
            )
            duplicate_outcomes = await self._latest_duplicate_outcomes(
                session,
                candidate_ids,
            )
            evaluations = await self._latest_rank_evaluations(
                session,
                user_id,
                candidate_ids,
                latest_analyses,
                profile.revision,
                parameter_hash,
            )

            article_snapshots = []
            for article_id in candidate_ids:
                article = articles.get(article_id)
                if article is None:
                    raise RankingRunError(
                        "candidate article is missing",
                        code="missing_candidate_article",
                    )
                analysis = latest_analyses.get(article_id)
                topic_key = (
                    analysis.topics[0]
                    if analysis is not None and analysis.topics
                    else None
                )
                complete = (
                    analysis is not None and analysis.status is AnalysisStatus.COMPLETE
                )
                article_snapshots.append(
                    RankingArticleSnapshot(
                        article_id=article.id,
                        article_analysis_id=analysis.id
                        if analysis is not None
                        else None,
                        source_id=article.primary_source_id,
                        event_group_id=article.event_group_id,
                        topic_key=topic_key,
                        published_at=article.published_at,
                        importance_score=Decimal(analysis.importance_score)
                        if complete
                        and analysis is not None
                        and analysis.importance_score is not None
                        else None,
                        novelty_score=Decimal(analysis.novelty_score)
                        if complete
                        and analysis is not None
                        and analysis.novelty_score is not None
                        else None,
                        source_quality_score=Decimal(analysis.source_quality_score)
                        if complete
                        and analysis is not None
                        and analysis.source_quality_score is not None
                        else None,
                        duplicate_outcome=duplicate_outcomes.get(article.id),
                        title=article.title,
                        summary=article.summary,
                        normalized_text=article.normalized_text,
                        language_code=article.language_code,
                        evaluation_run_id=evaluations.get(article.id).run_id
                        if article.id in evaluations
                        else None,
                    )
                )

            return (
                profile.revision,
                preferences,
                tuple(article_snapshots),
                tuple(
                    evaluations[article.article_id]
                    for article in article_snapshots
                    if article.article_id in evaluations
                ),
            )

    async def find_complete_run(
        self,
        identity: RankingIdentity,
        configuration: RankingConfiguration,
    ) -> RankingResult | None:
        async with self._database.session() as session:
            await self._ensure_configuration_snapshot(session, configuration)
            inserted_id = (
                await session.execute(
                    insert(models.RankingRun)
                    .values(
                        request_id=identity.request_id,
                        user_id=identity.user_id,
                        profile_revision=identity.profile_revision,
                        candidate_set_hash=identity.candidate_set_hash,
                        configuration_version=identity.configuration_version,
                        ranking_at=identity.ranking_at,
                        requested_count=identity.requested_count,
                        status=RankingStatus.PENDING,
                        updated_at=datetime.now(UTC),
                    )
                    .on_conflict_do_nothing()
                    .returning(models.RankingRun.id)
                )
            ).scalar_one_or_none()
            if inserted_id is not None:
                return None

            request_row = await session.scalar(
                select(models.RankingRun)
                .where(
                    models.RankingRun.user_id == identity.user_id,
                    models.RankingRun.request_id == identity.request_id,
                )
                .options(
                    selectinload(models.RankingRun.records).selectinload(
                        models.ArticleRankingRecord.contributions
                    )
                )
                .with_for_update()
            )
            if request_row is not None:
                self._ensure_same_request_identity(request_row, identity)
                if request_row.status in {
                    RankingStatus.COMPLETE,
                    RankingStatus.FAILED,
                    RankingStatus.STALE,
                }:
                    return await self._domain_ranking_result(session, request_row)
                return None

            snapshot_row = await session.scalar(
                select(models.RankingRun)
                .where(
                    models.RankingRun.user_id == identity.user_id,
                    models.RankingRun.profile_revision == identity.profile_revision,
                    models.RankingRun.candidate_set_hash == identity.candidate_set_hash,
                    models.RankingRun.configuration_version
                    == identity.configuration_version,
                    models.RankingRun.ranking_at == identity.ranking_at,
                    models.RankingRun.requested_count == identity.requested_count,
                )
                .options(
                    selectinload(models.RankingRun.records).selectinload(
                        models.ArticleRankingRecord.contributions
                    )
                )
                .with_for_update()
            )
            if snapshot_row is None:
                raise RankingRunError("ranking claim failed", code="claim_failed")
            if snapshot_row.status in {
                RankingStatus.COMPLETE,
                RankingStatus.FAILED,
                RankingStatus.STALE,
            }:
                return await self._domain_ranking_result(session, snapshot_row)
            return None

    async def persist_complete_run(
        self,
        result: RankingResult,
        configuration: RankingConfiguration,
    ) -> RankingResult:
        async with self._database.session() as session:
            await self._ensure_configuration_snapshot(session, configuration)
            run = await self._claimed_ranking_run(session, result.identity)
            if run.status in {
                RankingStatus.COMPLETE,
                RankingStatus.FAILED,
                RankingStatus.STALE,
            }:
                return await self._domain_ranking_result(session, run)

            await self._ensure_current_ranking_versions(
                session,
                run,
                result.identity,
                tuple(record.article_id for record in result.records),
            )
            self._validate_complete_selection(result)
            preference_map = {
                preference.id: preference
                for preference in await self._active_preferences(
                    session, result.identity.user_id
                )
            }
            run.status = RankingStatus.COMPLETE
            run.selected_count = result.selected_count
            run.excluded_count = result.excluded_count
            run.selected_cap_vector = (
                {
                    "event": result.selected_cap_vector[0],
                    "topic": result.selected_cap_vector[1],
                    "source": result.selected_cap_vector[2],
                }
                if result.selected_cap_vector is not None
                else None
            )
            run.unsatisfied_limits = list(result.unsatisfied_limits)
            run.error_code = None
            run.completed_at = result.completed_at or datetime.now(UTC)
            run.updated_at = run.completed_at

            explanation_limit = configuration.explanation_contribution_limit
            for record in result.records:
                ranking_record = models.ArticleRankingRecord(
                    ranking_run_id=run.id,
                    article_id=record.article_id,
                    article_analysis_id=record.article_analysis_id,
                    evaluation_run_id=record.evaluation_run_id,
                    event_group_id=record.event_group_id,
                    source_id=record.source_id,
                    topic_key=record.topic_key,
                    personal_numerator=self._score_8(record.personal_numerator),
                    personal_denominator=self._score_8(record.personal_denominator),
                    personal_state=record.personal_state,
                    personal_signed=self._score_8(record.personal_signed),
                    personal_factor=self._score_8(record.personal_factor),
                    importance=self._score_8(record.factors.importance),
                    freshness=self._score_8(record.factors.freshness),
                    quality=self._score_8(record.factors.quality),
                    novelty=self._score_8(record.factors.novelty),
                    unrounded_score=self._score_16(record.unrounded_score),
                    final_score=self._score_8(record.final_score),
                    eligible=record.eligible,
                    eligibility_reason=record.eligibility_reason.value,
                    explicit_protected=record.explicit_protected,
                    explicit_veto=record.explicit_veto,
                    initial_position=record.initial_position,
                    final_position=record.selection.position
                    if record.selection.selected
                    else None,
                    selection_reason=record.selection.reason.value,
                    diversity_pass=record.selection.diversity_pass,
                )
                session.add(ranking_record)
                await session.flush()

                displayed = {
                    item.parameter_id: index
                    for index, item in enumerate(
                        top_contributions(record.contributions, explanation_limit),
                        start=1,
                    )
                }
                for contribution in sorted(
                    record.contributions,
                    key=lambda item: item.parameter_id.int,
                ):
                    parameter = preference_map.get(contribution.parameter_id)
                    if parameter is None:
                        raise RankingRunError(
                            "ranking contribution parameter is missing",
                            code="missing_contribution_parameter",
                        )
                    session.add(
                        models.RankingParameterContribution(
                            article_ranking_id=ranking_record.id,
                            parameter_id=contribution.parameter_id,
                            parameter_snapshot_hash=parameter_snapshot_hash(parameter),
                            parameter_name=contribution.parameter_name,
                            parameter_origin=contribution.origin,
                            effective_authority=contribution.effective_authority,
                            weight=contribution.weight,
                            relevance=contribution.relevance,
                            contribution=contribution.contribution,
                            explanation_ordinal=displayed.get(
                                contribution.parameter_id
                            ),
                        )
                    )

                session.add(
                    models.RankingAudit(
                        id=ranking_record.id,
                        ranking_run_id=run.id,
                        user_id=result.identity.user_id,
                        article_id=record.article_id,
                        profile_revision=result.identity.profile_revision,
                        configuration_version=result.identity.configuration_version,
                        input_hash=self._input_hash(result.identity, record),
                        factor_hash=self._factor_hash(configuration, record),
                        contribution_hash=self._contribution_hash(record),
                        score_hash=self._score_hash(record),
                        selection_hash=self._selection_hash(record),
                        final_score=self._score_8(record.final_score),
                        final_position=record.selection.position
                        if record.selection.selected
                        else None,
                        ranked_at=result.identity.ranking_at,
                    )
                )

            await session.flush()
            return await self._domain_ranking_result(session, run)

    async def mark_stale_or_failed(
        self,
        identity: RankingIdentity,
        configuration: RankingConfiguration,
        status: str,
        *,
        error_code: str | None = None,
    ) -> RankingResult | None:
        async with self._database.session() as session:
            await self._ensure_configuration_snapshot(session, configuration)
            run = await self._claimed_ranking_run(session, identity, create=True)
            if run.status is RankingStatus.COMPLETE:
                return await self._domain_ranking_result(session, run)
            run.status = RankingStatus(status)
            run.selected_count = 0
            run.excluded_count = 0
            run.error_code = error_code[:100] if error_code else None
            run.completed_at = datetime.now(UTC)
            run.updated_at = run.completed_at
            await session.flush()
            return await self._domain_ranking_result(session, run)

    async def cleanup(
        self,
        now: datetime,
        policy: RetentionPolicy,
    ) -> RankingRetentionResult:
        remaining = policy.batch_size
        raw_texts_removed = 0
        raw_responses_removed = 0
        evaluation_details_removed = 0
        ranking_details_removed = 0
        compact_audit_rows_preserved = 0
        async with self._database.session() as session:
            if policy.raw_response_days > 0 and remaining > 0:
                raw_cutoff = now - timedelta(days=policy.raw_response_days)
                request_ids = tuple(
                    await session.scalars(
                        select(ExplicitPreferenceRequest.id)
                        .where(
                            ExplicitPreferenceRequest.raw_text.is_not(None),
                            ExplicitPreferenceRequest.completed_at.is_not(None),
                            ExplicitPreferenceRequest.completed_at < raw_cutoff,
                            ExplicitPreferenceRequest.status.in_(
                                (
                                    ExplicitRequestStatus.APPLIED,
                                    ExplicitRequestStatus.FAILED,
                                    ExplicitRequestStatus.STALE,
                                )
                            ),
                        )
                        .order_by(
                            ExplicitPreferenceRequest.completed_at,
                            ExplicitPreferenceRequest.id,
                        )
                        .limit(remaining)
                        .with_for_update(skip_locked=True)
                    )
                )
                if request_ids:
                    await session.execute(
                        update(ExplicitPreferenceRequest)
                        .where(ExplicitPreferenceRequest.id.in_(request_ids))
                        .values(raw_text=None, updated_at=now)
                    )
                    raw_texts_removed = len(request_ids)
                    remaining -= raw_texts_removed

                if remaining > 0:
                    attempt_ids = tuple(
                        await session.scalars(
                            select(models.ArticlePreferenceEvaluationAttempt.id)
                            .join(
                                models.ArticlePreferenceEvaluationRun,
                                models.ArticlePreferenceEvaluationAttempt.run_id
                                == models.ArticlePreferenceEvaluationRun.id,
                            )
                            .where(
                                models.ArticlePreferenceEvaluationAttempt.raw_response.is_not(
                                    None
                                ),
                                models.ArticlePreferenceEvaluationAttempt.completed_at
                                < raw_cutoff,
                                models.ArticlePreferenceEvaluationRun.status.in_(
                                    (
                                        EvaluationStatus.COMPLETE,
                                        EvaluationStatus.INCOMPLETE,
                                        EvaluationStatus.FAILED,
                                        EvaluationStatus.STALE,
                                    )
                                ),
                            )
                            .order_by(
                                models.ArticlePreferenceEvaluationAttempt.completed_at,
                                models.ArticlePreferenceEvaluationAttempt.id,
                            )
                            .limit(remaining)
                            .with_for_update(skip_locked=True)
                        )
                    )
                    if attempt_ids:
                        await self._set_immutable_trigger(
                            session,
                            "article_preference_evaluation_attempts",
                            "article_preference_evaluation_attempts_immutable",
                            enabled=False,
                        )
                        try:
                            await session.execute(
                                update(models.ArticlePreferenceEvaluationAttempt)
                                .where(
                                    models.ArticlePreferenceEvaluationAttempt.id.in_(
                                        attempt_ids
                                    )
                                )
                                .values(raw_response=null())
                            )
                        finally:
                            await self._set_immutable_trigger(
                                session,
                                "article_preference_evaluation_attempts",
                                "article_preference_evaluation_attempts_immutable",
                                enabled=True,
                            )
                        raw_responses_removed = len(attempt_ids)
                        remaining -= raw_responses_removed

            if policy.detail_days > 0 and remaining > 0:
                detail_cutoff = now - timedelta(days=policy.detail_days)
                ranking_run_ids = tuple(
                    await session.scalars(
                        select(models.RankingRun.id)
                        .where(
                            models.RankingRun.completed_at.is_not(None),
                            models.RankingRun.completed_at < detail_cutoff,
                            models.RankingRun.status.in_(
                                (
                                    RankingStatus.COMPLETE,
                                    RankingStatus.FAILED,
                                    RankingStatus.STALE,
                                )
                            ),
                            select(models.ArticleRankingRecord.id)
                            .where(
                                models.ArticleRankingRecord.ranking_run_id
                                == models.RankingRun.id
                            )
                            .exists(),
                        )
                        .order_by(
                            models.RankingRun.completed_at,
                            models.RankingRun.id,
                        )
                        .limit(remaining)
                        .with_for_update(skip_locked=True)
                    )
                )
                for run_id in ranking_run_ids:
                    record_ids = tuple(
                        await session.scalars(
                            select(models.ArticleRankingRecord.id)
                            .where(models.ArticleRankingRecord.ranking_run_id == run_id)
                            .order_by(
                                models.ArticleRankingRecord.initial_position.is_(None),
                                models.ArticleRankingRecord.initial_position,
                                models.ArticleRankingRecord.article_id,
                            )
                            .with_for_update(skip_locked=True)
                        )
                    )
                    if not record_ids:
                        continue
                    audit_ids = set(
                        await session.scalars(
                            select(models.RankingAudit.id).where(
                                models.RankingAudit.id.in_(record_ids)
                            )
                        )
                    )
                    if audit_ids != set(record_ids):
                        raise RuntimeError(
                            "refusing ranking detail compaction without compact audit"
                        )
                    await self._set_immutable_trigger(
                        session,
                        "ranking_parameter_contributions",
                        "ranking_parameter_contributions_immutable",
                        enabled=False,
                    )
                    try:
                        await session.execute(
                            delete(models.RankingParameterContribution).where(
                                models.RankingParameterContribution.article_ranking_id.in_(
                                    record_ids
                                )
                            )
                        )
                        await session.execute(
                            delete(models.ArticleRankingRecord).where(
                                models.ArticleRankingRecord.id.in_(record_ids)
                            )
                        )
                    finally:
                        await self._set_immutable_trigger(
                            session,
                            "ranking_parameter_contributions",
                            "ranking_parameter_contributions_immutable",
                            enabled=True,
                        )
                    ranking_details_removed += 1
                    compact_audit_rows_preserved += len(audit_ids)
                    remaining -= 1
                    if remaining <= 0:
                        break

            if policy.detail_days > 0 and remaining > 0:
                detail_cutoff = now - timedelta(days=policy.detail_days)
                profile_revisions: dict[UUID, int | None] = {}
                active_parameter_hashes: dict[UUID, str] = {}
                latest_analysis_ids: dict[UUID, UUID | None] = {}
                candidate_rows = tuple(
                    await session.scalars(
                        select(models.ArticlePreferenceEvaluationRun)
                        .where(
                            models.ArticlePreferenceEvaluationRun.completed_at.is_not(
                                None
                            ),
                            models.ArticlePreferenceEvaluationRun.completed_at
                            < detail_cutoff,
                            models.ArticlePreferenceEvaluationRun.status.in_(
                                (
                                    EvaluationStatus.COMPLETE,
                                    EvaluationStatus.INCOMPLETE,
                                    EvaluationStatus.FAILED,
                                    EvaluationStatus.STALE,
                                )
                            ),
                        )
                        .order_by(
                            models.ArticlePreferenceEvaluationRun.completed_at,
                            models.ArticlePreferenceEvaluationRun.id,
                        )
                        .limit(max(remaining * 5, remaining, 20))
                        .with_for_update(skip_locked=True)
                    )
                )
                removable_ids: list[UUID] = []
                for row in candidate_rows:
                    if await session.scalar(
                        select(models.ArticleRankingRecord.id)
                        .where(models.ArticleRankingRecord.evaluation_run_id == row.id)
                        .limit(1)
                    ):
                        continue
                    if row.status is EvaluationStatus.COMPLETE:
                        revision = profile_revisions.get(row.user_id)
                        if revision is None:
                            profile = await session.get(PreferenceProfile, row.user_id)
                            revision = profile.revision if profile is not None else None
                            profile_revisions[row.user_id] = revision
                        if revision == row.profile_revision:
                            current_hash = active_parameter_hashes.get(row.user_id)
                            if current_hash is None:
                                current_hash = parameter_set_hash(
                                    await self._active_preferences(session, row.user_id)
                                )
                                active_parameter_hashes[row.user_id] = current_hash
                            analysis_id = latest_analysis_ids.get(row.article_id)
                            if analysis_id is None:
                                analysis = await self._latest_complete_analysis(
                                    session,
                                    row.article_id,
                                )
                                analysis_id = (
                                    analysis.id if analysis is not None else None
                                )
                                latest_analysis_ids[row.article_id] = analysis_id
                            if (
                                current_hash == row.parameter_set_hash
                                and analysis_id == row.article_analysis_id
                            ):
                                continue
                    removable_ids.append(row.id)
                    if len(removable_ids) == remaining:
                        break

                if removable_ids:
                    await self._set_immutable_trigger(
                        session,
                        "article_preference_evaluation_attempts",
                        "article_preference_evaluation_attempts_immutable",
                        enabled=False,
                    )
                    await self._set_immutable_trigger(
                        session,
                        "article_parameter_relevances",
                        "article_parameter_relevances_immutable",
                        enabled=False,
                    )
                    try:
                        await session.execute(
                            delete(models.ArticlePreferenceEvaluationRun).where(
                                models.ArticlePreferenceEvaluationRun.id.in_(
                                    removable_ids
                                )
                            )
                        )
                    finally:
                        await self._set_immutable_trigger(
                            session,
                            "article_parameter_relevances",
                            "article_parameter_relevances_immutable",
                            enabled=True,
                        )
                        await self._set_immutable_trigger(
                            session,
                            "article_preference_evaluation_attempts",
                            "article_preference_evaluation_attempts_immutable",
                            enabled=True,
                        )
                    evaluation_details_removed = len(removable_ids)

            return RankingRetentionResult(
                raw_texts_removed=raw_texts_removed,
                raw_responses_removed=raw_responses_removed,
                evaluation_details_removed=evaluation_details_removed,
                ranking_details_removed=ranking_details_removed,
                compact_audit_rows_preserved=compact_audit_rows_preserved,
            )

    async def _ranking_articles(
        self,
        session: AsyncSession,
        article_ids: tuple[UUID, ...],
    ) -> dict[UUID, NormalizedArticle]:
        rows = tuple(
            await session.scalars(
                select(NormalizedArticle).where(NormalizedArticle.id.in_(article_ids))
            )
        )
        return {row.id: row for row in rows}

    async def _latest_analyses_by_article(
        self,
        session: AsyncSession,
        article_ids: tuple[UUID, ...],
    ) -> dict[UUID, ArticleAnalysis]:
        rows = tuple(
            await session.scalars(
                select(ArticleAnalysis)
                .where(
                    ArticleAnalysis.article_id.in_(article_ids),
                    ArticleAnalysis.status == AnalysisStatus.COMPLETE,
                )
                .order_by(
                    ArticleAnalysis.article_id,
                    ArticleAnalysis.created_at.desc(),
                    ArticleAnalysis.id.desc(),
                )
            )
        )
        analyses: dict[UUID, ArticleAnalysis] = {}
        for row in rows:
            analyses.setdefault(row.article_id, row)
        return analyses

    async def _latest_duplicate_outcomes(
        self,
        session: AsyncSession,
        article_ids: tuple[UUID, ...],
    ) -> dict[UUID, DecisionOutcome]:
        rows = tuple(
            await session.scalars(
                select(DeduplicationDecision)
                .where(
                    or_(
                        DeduplicationDecision.left_article_id.in_(article_ids),
                        DeduplicationDecision.right_article_id.in_(article_ids),
                    )
                )
                .order_by(
                    DeduplicationDecision.decided_at.desc(),
                    DeduplicationDecision.id.desc(),
                )
            )
        )
        outcomes: dict[UUID, DecisionOutcome] = {}
        for row in rows:
            if (
                row.left_article_id in article_ids
                and row.left_article_id not in outcomes
            ):
                outcomes[row.left_article_id] = row.outcome
            if (
                row.right_article_id in article_ids
                and row.right_article_id not in outcomes
            ):
                outcomes[row.right_article_id] = row.outcome
        return outcomes

    async def _latest_rank_evaluations(
        self,
        session: AsyncSession,
        user_id: UUID,
        article_ids: tuple[UUID, ...],
        analyses: dict[UUID, ArticleAnalysis],
        profile_revision: int,
        parameter_hash: str,
    ) -> dict[UUID, ArticleEvaluation]:
        rows = tuple(
            await session.scalars(
                select(models.ArticlePreferenceEvaluationRun)
                .where(
                    models.ArticlePreferenceEvaluationRun.user_id == user_id,
                    models.ArticlePreferenceEvaluationRun.article_id.in_(article_ids),
                    models.ArticlePreferenceEvaluationRun.profile_revision
                    == profile_revision,
                    models.ArticlePreferenceEvaluationRun.parameter_set_hash
                    == parameter_hash,
                )
                .options(selectinload(models.ArticlePreferenceEvaluationRun.relevances))
                .order_by(
                    models.ArticlePreferenceEvaluationRun.article_id,
                    models.ArticlePreferenceEvaluationRun.updated_at.desc(),
                    models.ArticlePreferenceEvaluationRun.id.desc(),
                )
            )
        )
        complete: dict[UUID, ArticleEvaluation] = {}
        fallback: dict[UUID, ArticleEvaluation] = {}
        for row in rows:
            analysis = analyses.get(row.article_id)
            if analysis is None or row.article_analysis_id != analysis.id:
                continue
            fallback.setdefault(row.article_id, self._domain_evaluation(row))
            if row.status is EvaluationStatus.COMPLETE:
                complete.setdefault(row.article_id, self._domain_evaluation(row))
        for article_id, evaluation in fallback.items():
            complete.setdefault(article_id, evaluation)
        return complete

    async def _ensure_configuration_snapshot(
        self,
        session: AsyncSession,
        configuration: RankingConfiguration,
    ) -> None:
        existing = await session.get(
            models.RankingConfigurationSnapshot,
            configuration.version,
        )
        configuration_hash = canonical_configuration_hash(configuration)
        if existing is not None:
            if existing.configuration_hash != configuration_hash:
                raise RankingConfigurationError(
                    "configuration version already persists different values",
                    code="configuration_version_conflict",
                )
            return
        session.add(
            models.RankingConfigurationSnapshot(
                version=configuration.version,
                configuration_hash=configuration_hash,
                personal_coefficient=configuration.personal_coefficient,
                importance_coefficient=configuration.importance_coefficient,
                freshness_coefficient=configuration.freshness_coefficient,
                quality_coefficient=configuration.quality_coefficient,
                novelty_coefficient=configuration.novelty_coefficient,
                freshness_horizon_seconds=configuration.freshness_horizon_seconds,
                future_tolerance_seconds=configuration.future_tolerance_seconds,
                minimum_source_quality=configuration.minimum_source_quality,
                maximum_candidate_count=configuration.maximum_candidate_count,
                event_cap=configuration.event_cap,
                topic_cap=configuration.topic_cap,
                source_cap=configuration.source_cap,
                explicit_weight_threshold=configuration.explicit_weight_threshold,
                explicit_relevance_threshold=configuration.explicit_relevance_threshold,
                explanation_contribution_limit=configuration.explanation_contribution_limit,
                tie_policy_version=configuration.tie_policy_version,
                retention_policy_version=configuration.retention_policy_version,
            )
        )
        await session.flush()

    @staticmethod
    def _ensure_same_request_identity(
        row: models.RankingRun,
        identity: RankingIdentity,
    ) -> None:
        if (
            row.profile_revision != identity.profile_revision
            or row.candidate_set_hash != identity.candidate_set_hash
            or row.configuration_version != identity.configuration_version
            or row.ranking_at != identity.ranking_at
            or row.requested_count != identity.requested_count
        ):
            raise RankingRunError(
                "same request id cannot be reused with different input",
                code="request_id_conflict",
            )

    async def _claimed_ranking_run(
        self,
        session: AsyncSession,
        identity: RankingIdentity,
        *,
        create: bool = False,
    ) -> models.RankingRun:
        row = await session.scalar(
            select(models.RankingRun)
            .where(
                models.RankingRun.user_id == identity.user_id,
                models.RankingRun.request_id == identity.request_id,
            )
            .options(
                selectinload(models.RankingRun.records).selectinload(
                    models.ArticleRankingRecord.contributions
                )
            )
            .with_for_update()
        )
        if row is not None:
            self._ensure_same_request_identity(row, identity)
            return row

        row = await session.scalar(
            select(models.RankingRun)
            .where(
                models.RankingRun.user_id == identity.user_id,
                models.RankingRun.profile_revision == identity.profile_revision,
                models.RankingRun.candidate_set_hash == identity.candidate_set_hash,
                models.RankingRun.configuration_version
                == identity.configuration_version,
                models.RankingRun.ranking_at == identity.ranking_at,
                models.RankingRun.requested_count == identity.requested_count,
            )
            .options(
                selectinload(models.RankingRun.records).selectinload(
                    models.ArticleRankingRecord.contributions
                )
            )
            .with_for_update()
        )
        if row is not None:
            return row
        if not create:
            raise RankingRunError("ranking run is missing", code="missing_ranking_run")
        row = models.RankingRun(
            request_id=identity.request_id,
            user_id=identity.user_id,
            profile_revision=identity.profile_revision,
            candidate_set_hash=identity.candidate_set_hash,
            configuration_version=identity.configuration_version,
            ranking_at=identity.ranking_at,
            requested_count=identity.requested_count,
            status=RankingStatus.PENDING,
        )
        session.add(row)
        await session.flush()
        return row

    async def _ensure_current_ranking_versions(
        self,
        session: AsyncSession,
        run: models.RankingRun,
        identity: RankingIdentity,
        article_ids: tuple[UUID, ...],
    ) -> None:
        profile = await session.get(PreferenceProfile, identity.user_id)
        if profile is None or profile.revision != identity.profile_revision:
            await self._mark_ranking_stale(session, run, "stale_profile_revision")
            raise StaleSnapshotError(
                "profile changed before ranking persistence",
                code="stale_profile_revision",
            )
        preferences = await self._active_preferences(session, identity.user_id)
        current_hash = await self._current_candidate_hash(
            session,
            identity.user_id,
            article_ids,
            profile.revision,
            parameter_set_hash(preferences),
        )
        if current_hash != identity.candidate_set_hash:
            await self._mark_ranking_stale(session, run, "stale_candidate_snapshot")
            raise StaleSnapshotError(
                "ranking candidate snapshot changed before persistence",
                code="stale_candidate_snapshot",
            )

    async def _current_candidate_hash(
        self,
        session: AsyncSession,
        user_id: UUID,
        article_ids: tuple[UUID, ...],
        profile_revision: int,
        parameter_hash: str,
    ) -> str:
        articles = await self._ranking_articles(session, article_ids)
        analyses = await self._latest_analyses_by_article(session, article_ids)
        if any(article_id not in articles for article_id in article_ids):
            return ""
        duplicates = await self._latest_duplicate_outcomes(session, article_ids)
        evaluations = await self._latest_rank_evaluations(
            session,
            user_id,
            article_ids,
            analyses,
            profile_revision,
            parameter_hash,
        )
        snapshots = []
        for article_id in article_ids:
            article = articles[article_id]
            analysis = analyses.get(article_id)
            complete = (
                analysis is not None and analysis.status is AnalysisStatus.COMPLETE
            )
            snapshots.append(
                RankingArticleSnapshot(
                    article_id=article.id,
                    article_analysis_id=analysis.id if analysis is not None else None,
                    source_id=article.primary_source_id,
                    event_group_id=article.event_group_id,
                    topic_key=analysis.topics[0]
                    if analysis is not None and analysis.topics
                    else None,
                    published_at=article.published_at,
                    importance_score=Decimal(analysis.importance_score)
                    if complete
                    and analysis is not None
                    and analysis.importance_score is not None
                    else None,
                    novelty_score=Decimal(analysis.novelty_score)
                    if complete
                    and analysis is not None
                    and analysis.novelty_score is not None
                    else None,
                    source_quality_score=Decimal(analysis.source_quality_score)
                    if complete
                    and analysis is not None
                    and analysis.source_quality_score is not None
                    else None,
                    duplicate_outcome=duplicates.get(article.id),
                    title=article.title,
                    summary=article.summary,
                    normalized_text=article.normalized_text,
                    language_code=article.language_code,
                    evaluation_run_id=evaluations.get(article.id).run_id
                    if article.id in evaluations
                    else None,
                )
            )
        return candidate_snapshot_hash(
            tuple(snapshots),
            tuple(evaluations.values()),
        )

    @staticmethod
    async def _mark_ranking_stale(
        session: AsyncSession,
        run: models.RankingRun,
        error_code: str,
    ) -> None:
        completed_at = datetime.now(UTC)
        run.status = RankingStatus.STALE
        run.error_code = error_code[:100]
        run.completed_at = completed_at
        run.updated_at = completed_at
        await session.flush()

    async def _domain_ranking_result(
        self,
        session: AsyncSession,
        run: models.RankingRun,
    ) -> RankingResult:
        rows = tuple(
            await session.scalars(
                select(models.ArticleRankingRecord)
                .where(models.ArticleRankingRecord.ranking_run_id == run.id)
                .options(selectinload(models.ArticleRankingRecord.contributions))
                .order_by(
                    models.ArticleRankingRecord.initial_position.is_(None),
                    models.ArticleRankingRecord.initial_position,
                    models.ArticleRankingRecord.article_id,
                )
            )
        )
        published_at_rows = (
            await session.execute(
                select(NormalizedArticle.id, NormalizedArticle.published_at).where(
                    NormalizedArticle.id.in_([row.article_id for row in rows])
                )
            )
        ).all()
        published_at = {
            article_id: published for article_id, published in published_at_rows
        }
        records = tuple(
            RankingRecord(
                article_id=row.article_id,
                article_analysis_id=row.article_analysis_id,
                source_id=row.source_id,
                event_group_id=row.event_group_id,
                topic_key=row.topic_key,
                published_at=published_at.get(row.article_id),
                evaluation_run_id=row.evaluation_run_id,
                personal_state=row.personal_state,
                personal_numerator=Decimal(row.personal_numerator),
                personal_denominator=Decimal(row.personal_denominator),
                personal_signed=Decimal(row.personal_signed),
                personal_factor=Decimal(row.personal_factor),
                factors=FactorSnapshot(
                    importance=Decimal(row.importance),
                    freshness=Decimal(row.freshness),
                    quality=Decimal(row.quality),
                    novelty=Decimal(row.novelty),
                ),
                unrounded_score=Decimal(row.unrounded_score),
                final_score=Decimal(row.final_score),
                eligible=row.eligible,
                eligibility_reason=EligibilityReason(row.eligibility_reason),
                explicit_protected=row.explicit_protected,
                explicit_veto=row.explicit_veto,
                selection=SelectionOutcome(
                    selected=row.final_position is not None,
                    reason=SelectionReason(row.selection_reason),
                    position=row.final_position,
                    explicit_protected=row.explicit_protected,
                    diversity_pass=row.diversity_pass,
                ),
                contributions=tuple(
                    ContributionSnapshot(
                        parameter_id=contribution.parameter_id,
                        parameter_name=contribution.parameter_name,
                        origin=contribution.parameter_origin,
                        effective_authority=contribution.effective_authority,
                        weight=Decimal(contribution.weight),
                        relevance=Decimal(contribution.relevance),
                        contribution=Decimal(contribution.contribution),
                    )
                    for contribution in sorted(
                        row.contributions,
                        key=lambda item: item.parameter_id.int,
                    )
                ),
                initial_position=row.initial_position,
            )
            for row in rows
        )
        return RankingResult(
            ranking_run_id=run.id,
            identity=RankingIdentity(
                request_id=run.request_id,
                user_id=run.user_id,
                profile_revision=run.profile_revision,
                candidate_set_hash=run.candidate_set_hash,
                configuration_version=run.configuration_version,
                ranking_at=run.ranking_at,
                requested_count=run.requested_count,
            ),
            status=run.status,
            records=records,
            selected_count=run.selected_count,
            excluded_count=run.excluded_count,
            selected_cap_vector=(
                (
                    int(run.selected_cap_vector["event"]),
                    int(run.selected_cap_vector["topic"]),
                    int(run.selected_cap_vector["source"]),
                )
                if run.selected_cap_vector is not None
                else None
            ),
            unsatisfied_limits=tuple(run.unsatisfied_limits),
            completed_at=run.completed_at,
            error_code=run.error_code,
        )

    @staticmethod
    def _validate_complete_selection(result: RankingResult) -> None:
        if result.status is not RankingStatus.COMPLETE:
            raise RankingRunError(
                "ranking result must be complete before persistence",
                code="invalid_ranking_status",
            )
        if result.selected_cap_vector is None:
            raise RankingRunError(
                "complete ranking result must include a selected cap vector",
                code="missing_selected_cap_vector",
            )
        if len(set(result.unsatisfied_limits)) != len(result.unsatisfied_limits) or any(
            limit not in {"source", "topic", "event"}
            for limit in result.unsatisfied_limits
        ):
            raise RankingRunError(
                "unsatisfied_limits must contain unique configured diversity limits",
                code="invalid_unsatisfied_limits",
            )

        selected_positions = sorted(
            record.selection.position
            for record in result.records
            if record.selection.selected and record.selection.position is not None
        )
        if len(selected_positions) != result.selected_count:
            raise RankingRunError(
                "selected_count must match selected record positions",
                code="selected_count_mismatch",
            )
        if selected_positions != list(range(1, len(selected_positions) + 1)):
            raise RankingRunError(
                "selected record positions must be contiguous",
                code="non_contiguous_final_positions",
            )
        if any(
            record.selection.selected
            and record.selection.reason is not SelectionReason.SELECTED
            for record in result.records
        ):
            raise RankingRunError(
                "selected records must use the selected selection reason",
                code="invalid_selected_reason",
            )
        if any(
            not record.selection.selected and record.selection.position is not None
            for record in result.records
        ):
            raise RankingRunError(
                "non-selected records must not retain final positions",
                code="invalid_unselected_position",
            )
        if any(
            not record.selection.selected
            and record.selection.diversity_pass is not None
            for record in result.records
        ):
            raise RankingRunError(
                "non-selected records must not retain diversity passes",
                code="invalid_unselected_diversity_pass",
            )
        selected_passes = {
            record.selection.diversity_pass
            for record in result.records
            if record.selection.selected
        }
        if len(selected_passes) > 1 or (selected_passes and None in selected_passes):
            raise RankingRunError(
                "selected records must share one final diversity pass",
                code="inconsistent_diversity_pass",
            )

    @staticmethod
    def _score_8(value: Decimal) -> Decimal:
        return Decimal(f"{Decimal(value):.8f}")

    @staticmethod
    def _score_16(value: Decimal) -> Decimal:
        return Decimal(f"{Decimal(value):.16f}")

    @classmethod
    def _payload_hash(cls, value: Mapping[str, Any]) -> str:
        return cls._json_hash(value) or "0" * 64

    @classmethod
    def _input_hash(
        cls,
        identity: RankingIdentity,
        record: RankingRecord,
    ) -> str:
        return cls._payload_hash(
            {
                "article_id": str(record.article_id),
                "article_analysis_id": str(record.article_analysis_id)
                if record.article_analysis_id is not None
                else None,
                "source_id": str(record.source_id),
                "event_group_id": str(record.event_group_id)
                if record.event_group_id is not None
                else None,
                "topic_key": record.topic_key,
                "published_at": record.published_at.isoformat()
                if record.published_at is not None
                else None,
                "evaluation_run_id": str(record.evaluation_run_id)
                if record.evaluation_run_id is not None
                else None,
                "profile_revision": identity.profile_revision,
                "candidate_set_hash": identity.candidate_set_hash,
                "ranking_at": identity.ranking_at.isoformat(),
            }
        )

    @classmethod
    def _factor_hash(
        cls,
        configuration: RankingConfiguration,
        record: RankingRecord,
    ) -> str:
        return cls._payload_hash(
            {
                "configuration_version": configuration.version,
                "coefficients": {
                    "personal": f"{configuration.personal_coefficient:.5f}",
                    "importance": f"{configuration.importance_coefficient:.5f}",
                    "freshness": f"{configuration.freshness_coefficient:.5f}",
                    "quality": f"{configuration.quality_coefficient:.5f}",
                    "novelty": f"{configuration.novelty_coefficient:.5f}",
                },
                "factors": {
                    "personal_factor": f"{record.personal_factor:.8f}",
                    "importance": f"{record.factors.importance:.8f}",
                    "freshness": f"{record.factors.freshness:.8f}",
                    "quality": f"{record.factors.quality:.8f}",
                    "novelty": f"{record.factors.novelty:.8f}",
                },
            }
        )

    @classmethod
    def _contribution_hash(cls, record: RankingRecord) -> str:
        return cls._payload_hash(
            {
                "contributions": [
                    {
                        "parameter_id": str(contribution.parameter_id),
                        "origin": contribution.origin.value,
                        "effective_authority": contribution.effective_authority.value,
                        "weight": f"{contribution.weight:.2f}",
                        "relevance": f"{contribution.relevance:.4f}",
                        "contribution": f"{contribution.contribution:.8f}",
                    }
                    for contribution in sorted(
                        record.contributions,
                        key=lambda item: item.parameter_id.int,
                    )
                ]
            }
        )

    @classmethod
    def _score_hash(cls, record: RankingRecord) -> str:
        return cls._payload_hash(
            {
                "personal_numerator": f"{record.personal_numerator:.8f}",
                "personal_denominator": f"{record.personal_denominator:.8f}",
                "personal_signed": f"{record.personal_signed:.8f}",
                "unrounded_score": f"{Decimal(record.unrounded_score):.16f}",
                "final_score": f"{record.final_score:.8f}",
            }
        )

    @classmethod
    def _selection_hash(cls, record: RankingRecord) -> str:
        return cls._payload_hash(
            {
                "eligible": record.eligible,
                "eligibility_reason": record.eligibility_reason.value,
                "explicit_protected": record.explicit_protected,
                "explicit_veto": record.explicit_veto,
                "selected": record.selection.selected,
                "selection_reason": record.selection.reason.value,
                "position": record.selection.position,
                "diversity_pass": record.selection.diversity_pass,
            }
        )

    async def _profile_snapshot(
        self,
        session: AsyncSession,
        user_id: UUID,
        revision: int,
    ) -> ProfileSnapshot:
        parameters = tuple(
            self._domain_parameter(row)
            for row in (
                await session.scalars(
                    select(PreferenceParameterModel)
                    .where(PreferenceParameterModel.user_id == user_id)
                    .order_by(
                        PreferenceParameterModel.created_at, PreferenceParameterModel.id
                    )
                )
            )
        )
        return ProfileSnapshot(
            user_id=user_id, revision=revision, parameters=parameters
        )

    async def _active_preferences(
        self,
        session: AsyncSession,
        user_id: UUID,
    ) -> tuple[RankingPreference, ...]:
        rows = tuple(
            await session.scalars(
                select(PreferenceParameterModel)
                .where(
                    PreferenceParameterModel.user_id == user_id,
                    PreferenceParameterModel.active.is_(True),
                )
                .order_by(
                    PreferenceParameterModel.created_at, PreferenceParameterModel.id
                )
            )
        )
        evidence_sources: dict[UUID, list[Any]] = defaultdict(list)
        if rows:
            evidence_rows = (
                await session.execute(
                    select(PreferenceEvidence.parameter_id, PreferenceEvidence.source)
                    .where(
                        PreferenceEvidence.parameter_id.in_([row.id for row in rows])
                    )
                    .order_by(PreferenceEvidence.created_at, PreferenceEvidence.id)
                )
            ).all()
            for parameter_id, source in evidence_rows:
                evidence_sources[parameter_id].append(source)
        return tuple(
            RankingPreference(
                id=row.id,
                user_id=row.user_id,
                semantic_key=row.semantic_key,
                name=row.name,
                description=row.description,
                evaluation_instructions=row.evaluation_instructions,
                weight=Decimal(row.weight),
                origin=row.origin,
                effective_authority=derive_effective_authority(
                    row.origin,
                    evidence_sources.get(row.id, ()),
                ),
                active=row.active,
            )
            for row in rows
        )

    async def _latest_complete_analysis(
        self,
        session: AsyncSession,
        article_id: UUID,
    ) -> ArticleAnalysis | None:
        return await session.scalar(
            select(ArticleAnalysis)
            .where(
                ArticleAnalysis.article_id == article_id,
                ArticleAnalysis.status == AnalysisStatus.COMPLETE,
            )
            .order_by(ArticleAnalysis.created_at.desc(), ArticleAnalysis.id.desc())
            .limit(1)
        )

    @staticmethod
    def _baseline_topic(metadata: list[Any]) -> str | None:
        for item in metadata:
            if isinstance(item, str) and item.strip():
                return item.strip()[:100]
            if isinstance(item, Mapping):
                value = item.get("key") or item.get("name") or item.get("topic")
                if isinstance(value, str) and value.strip():
                    return value.strip()[:100]
        return None

    async def _latest_duplicate_outcome(
        self,
        session: AsyncSession,
        article_id: UUID,
    ) -> DecisionOutcome | None:
        row = await session.scalar(
            select(DeduplicationDecision)
            .where(
                or_(
                    DeduplicationDecision.left_article_id == article_id,
                    DeduplicationDecision.right_article_id == article_id,
                )
            )
            .order_by(
                DeduplicationDecision.decided_at.desc(), DeduplicationDecision.id.desc()
            )
            .limit(1)
        )
        return row.outcome if row is not None else None

    async def _ensure_current_versions(
        self,
        session: AsyncSession,
        run: models.ArticlePreferenceEvaluationRun,
    ) -> None:
        profile = await session.get(PreferenceProfile, run.user_id)
        if profile is None or profile.revision != run.profile_revision:
            await self._mark_stale(session, run, "stale_profile_revision")
            raise StaleSnapshotError(
                "profile changed before evaluation acceptance",
                code="stale_profile_revision",
            )
        current_analysis = await self._latest_complete_analysis(session, run.article_id)
        if current_analysis is None or current_analysis.id != run.article_analysis_id:
            await self._mark_stale(session, run, "stale_article_analysis")
            raise StaleSnapshotError(
                "article analysis changed before evaluation acceptance",
                code="stale_article_analysis",
            )

    @staticmethod
    async def _mark_stale(
        session: AsyncSession,
        run: models.ArticlePreferenceEvaluationRun,
        error_code: str,
    ) -> None:
        completed_at = datetime.now(UTC)
        run.status = EvaluationStatus.STALE
        run.error_code = error_code[:100]
        run.completed_at = completed_at
        run.updated_at = completed_at
        await session.flush()

    @staticmethod
    def _identity_from_row(
        row: models.ArticlePreferenceEvaluationRun,
    ) -> ArticleEvaluationIdentity:
        return ArticleEvaluationIdentity(
            user_id=row.user_id,
            article_id=row.article_id,
            article_analysis_id=row.article_analysis_id,
            profile_revision=row.profile_revision,
            parameter_set_hash=row.parameter_set_hash,
            schema_version=row.schema_version,
            evaluator_name=row.evaluator_name,
            evaluator_version=row.evaluator_version,
            prompt_version=row.prompt_version,
        )

    def _domain_evaluation(
        self,
        row: models.ArticlePreferenceEvaluationRun,
    ) -> ArticleEvaluation:
        relevances = tuple(
            ArticleParameterRelevance(
                parameter_id=item.parameter_id,
                relevance=Decimal(item.relevance),
                reason_code=item.reason_code,
            )
            for item in sorted(
                row.relevances,
                key=lambda relevance: (relevance.created_at, relevance.parameter_id),
            )
        )
        return ArticleEvaluation(
            run_id=row.id,
            identity=self._identity_from_row(row),
            status=row.status,
            relevances=relevances,
            accepted_attempt_id=row.accepted_attempt_id,
            attempt_count=row.attempt_count,
            completed_at=row.completed_at,
            error_code=row.error_code,
        )

    @staticmethod
    def _domain_parameter(row: PreferenceParameterModel) -> PreferenceParameter:
        return PreferenceParameter(
            id=row.id,
            user_id=row.user_id,
            semantic_key=row.semantic_key,
            name=row.name,
            description=row.description,
            evaluation_instructions=row.evaluation_instructions,
            weight=Decimal(row.weight),
            origin=row.origin,
            active=row.active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _jsonable(
        value: Mapping[str, Any] | None,
    ) -> dict[str, Any] | list[Any] | str | None:
        if value is None:
            return None
        return json.loads(json.dumps(value, default=str, separators=(",", ":")))

    @classmethod
    def _json_hash(cls, value: Mapping[str, Any] | None) -> str | None:
        if value is None:
            return None
        payload = json.dumps(
            cls._jsonable(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    async def _set_immutable_trigger(
        session: AsyncSession,
        table_name: str,
        trigger_name: str,
        *,
        enabled: bool,
    ) -> None:
        command = "ENABLE" if enabled else "DISABLE"
        await session.execute(
            text(f"ALTER TABLE {table_name} {command} TRIGGER {trigger_name}")
        )


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


__all__ = ["SQLAlchemyRankingRepository", "SystemClock"]
