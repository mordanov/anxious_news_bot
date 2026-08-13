from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text

from anxious_news_bot.news.domain import AnalysisStatus, CycleStatus, SourceType
from anxious_news_bot.news.infrastructure.models import (
    ArticleAnalysis,
    CollectionCycle,
    EventGroup,
    NewsSource,
    NormalizedArticle,
)
from anxious_news_bot.preferences.domain import (
    ExplicitRequestStatus,
    PreferenceAction,
    PreferenceOrigin,
    UpdateBatchStatus,
)
from anxious_news_bot.preferences.infrastructure.models import (
    ApplicationUser,
    ExplicitPreferenceRequest,
    PreferenceChangeAudit,
    PreferenceChangeHistory,
    PreferenceEvidence,
    PreferenceParameter,
    PreferenceProfile,
    PreferenceUpdateBatch,
)
from anxious_news_bot.ranking.domain import (
    EvaluationAttemptStatus,
    EvaluationStatus,
    PersonalState,
    RankingStatus,
    RetentionPolicy,
)
from anxious_news_bot.ranking.infrastructure.models import (
    ArticleParameterRelevance,
    ArticlePreferenceEvaluationAttempt,
    ArticlePreferenceEvaluationRun,
    ArticleRankingRecord,
    RankingAudit,
    RankingConfigurationSnapshot,
    RankingParameterContribution,
    RankingRun,
)
from anxious_news_bot.ranking.infrastructure.persistence import (
    SQLAlchemyRankingRepository,
)
from anxious_news_bot.ranking.services.configuration import (
    canonical_configuration_hash,
)
from anxious_news_bot.ranking.services.evaluate import parameter_set_hash
from tests.fixtures.ranking import ranking_configuration, ranking_preference

NOW = datetime(2026, 1, 1, tzinfo=UTC)
OLD = NOW - timedelta(days=120)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _uuid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012d}")


async def _seed_base_context(session, *, telegram_user_id: int) -> dict[str, object]:
    user = ApplicationUser(telegram_user_id=telegram_user_id, language_code="en")
    session.add(user)
    await session.flush()
    session.add(PreferenceProfile(user_id=user.id, revision=3))

    source = NewsSource(
        id=uuid4(),
        name=f"retention-source-{telegram_user_id}",
        source_type=SourceType.RSS,
        endpoint_url=f"https://example.com/retention/{telegram_user_id}.xml",
        region="World",
        language_code="en",
        enabled=True,
        polling_interval_seconds=300,
    )
    cycle = CollectionCycle(
        id=uuid4(),
        status=CycleStatus.RUNNING,
        started_at=NOW,
        configuration_version="test",
    )
    event = EventGroup(id=uuid4(), label=f"Retention event {telegram_user_id}")
    parameter = PreferenceParameter(
        id=uuid4(),
        user_id=user.id,
        semantic_key="kirov_city_news",
        name="Kirov city news",
        description="Specific city reporting about Kirov.",
        evaluation_instructions="Prefer relevant Kirov city reporting.",
        weight=Decimal("0.80"),
        origin=PreferenceOrigin.EXPLICIT,
        active=True,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add_all((source, cycle, event, parameter))
    await session.flush()

    parameter_hash = parameter_set_hash(
        (
            ranking_preference(
                parameter_id=parameter.id,
                user_id=user.id,
                semantic_key=parameter.semantic_key,
                name=parameter.name,
                description=parameter.description,
                evaluation_instructions=parameter.evaluation_instructions,
                weight="0.80",
                origin=PreferenceOrigin.EXPLICIT,
                effective_authority=PreferenceOrigin.EXPLICIT,
            ),
        )
    )

    return {
        "user_id": user.id,
        "source_id": source.id,
        "cycle_id": cycle.id,
        "event_id": event.id,
        "parameter": parameter,
        "parameter_hash": parameter_hash,
        "profile_revision": 3,
    }


async def _seed_article(
    session,
    context: dict[str, object],
    *,
    title: str,
    published_at: datetime = NOW - timedelta(hours=1),
    importance: Decimal = Decimal("0.8000"),
    novelty: Decimal = Decimal("0.3000"),
    quality: Decimal = Decimal("0.9000"),
    topic: str = "local",
) -> dict[str, object]:
    article = NormalizedArticle(
        id=uuid4(),
        title=title,
        summary=f"{title} summary",
        canonical_url=f"https://example.com/{title.replace(' ', '-').lower()}",
        canonicalization_version="1.0",
        primary_source_id=context["source_id"],
        published_at=published_at,
        ingested_at=NOW,
        language_code="en",
        normalized_text=f"{title} normalized text",
        event_group_id=context["event_id"],
        created_in_cycle_id=context["cycle_id"],
    )
    analysis = ArticleAnalysis(
        id=uuid4(),
        article_id=article.id,
        status=AnalysisStatus.COMPLETE,
        schema_version="1.0",
        analyzer_name="generic-analyzer",
        analyzer_version="1.0",
        topics=[topic],
        created_at=NOW,
        importance_score=importance,
        novelty_score=novelty,
        source_quality_score=quality,
    )
    session.add_all((article, analysis))
    await session.flush()
    return {
        "article_id": article.id,
        "analysis_id": analysis.id,
    }


async def _seed_evaluation_run(
    session,
    context: dict[str, object],
    article: dict[str, object],
    *,
    status: EvaluationStatus,
    completed_at: datetime | None,
    raw_response: dict[str, object] | None,
    profile_revision: int | None = None,
    parameter_hash: str | None = None,
    attempt_status: EvaluationAttemptStatus | None = None,
    include_relevance: bool | None = None,
) -> UUID:
    run = ArticlePreferenceEvaluationRun(
        id=uuid4(),
        user_id=context["user_id"],
        article_id=article["article_id"],
        article_analysis_id=article["analysis_id"],
        profile_revision=profile_revision
        if profile_revision is not None
        else context["profile_revision"],
        parameter_set_hash=parameter_hash or context["parameter_hash"],
        schema_version="1.0",
        evaluator_name="integration-evaluator",
        evaluator_version="1.0",
        prompt_version="prompt-v1",
        status=status,
        attempt_count=1 if raw_response is not None else 0,
        completed_at=completed_at,
        created_at=completed_at or OLD,
        updated_at=completed_at or OLD,
    )
    session.add(run)
    await session.flush()

    if raw_response is not None:
        attempt = ArticlePreferenceEvaluationAttempt(
            id=uuid4(),
            run_id=run.id,
            ordinal=1,
            response_hash=_digest(f"attempt:{run.id}"),
            raw_response=raw_response,
            status=attempt_status
            or (
                EvaluationAttemptStatus.ACCEPTED
                if status is EvaluationStatus.COMPLETE
                else EvaluationAttemptStatus.FAILED
            ),
            error_code=None
            if status is EvaluationStatus.COMPLETE
            else "evaluation_failed",
            started_at=completed_at or OLD,
            completed_at=completed_at or OLD,
        )
        session.add(attempt)
        await session.flush()
        if include_relevance is not False and status is EvaluationStatus.COMPLETE:
            from anxious_news_bot.ranking.infrastructure.models import (
                ArticleParameterRelevance,
            )

            session.add(
                ArticleParameterRelevance(
                    evaluation_run_id=run.id,
                    parameter_id=context["parameter"].id,
                    parameter_snapshot_hash=_digest(
                        f"parameter:{context['parameter'].id}"
                    ),
                    relevance=Decimal("0.7500"),
                    reason_code="clear_match",
                )
            )
            run.accepted_attempt_id = attempt.id

    await session.flush()
    return run.id


async def _ensure_configuration_snapshot(session) -> None:
    configuration = ranking_configuration()
    if await session.get(RankingConfigurationSnapshot, configuration.version):
        return
    session.add(
        RankingConfigurationSnapshot(
            version=configuration.version,
            configuration_hash=canonical_configuration_hash(configuration),
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
            created_at=OLD,
        )
    )
    await session.flush()


async def _seed_ranking_detail(
    session,
    context: dict[str, object],
    article: dict[str, object],
    evaluation_run_id: UUID,
    *,
    request_id: str,
    completed_at: datetime,
) -> UUID:
    await _ensure_configuration_snapshot(session)
    run = RankingRun(
        id=uuid4(),
        request_id=request_id,
        user_id=context["user_id"],
        profile_revision=context["profile_revision"],
        candidate_set_hash=_digest(f"candidate:{request_id}"),
        configuration_version="1.0",
        ranking_at=completed_at,
        requested_count=1,
        status=RankingStatus.COMPLETE,
        selected_count=1,
        excluded_count=0,
        selected_cap_vector={"event": 2, "topic": 3, "source": 3},
        unsatisfied_limits=[],
        error_code=None,
        completed_at=completed_at,
        created_at=completed_at,
        updated_at=completed_at,
    )
    session.add(run)
    await session.flush()

    record_id = uuid4()
    session.add(
        ArticleRankingRecord(
            id=record_id,
            ranking_run_id=run.id,
            article_id=article["article_id"],
            article_analysis_id=article["analysis_id"],
            evaluation_run_id=evaluation_run_id,
            event_group_id=context["event_id"],
            source_id=context["source_id"],
            topic_key="local",
            personal_numerator=Decimal("0.60000000"),
            personal_denominator=Decimal("0.80000000"),
            personal_state=PersonalState.COMPLETE,
            personal_signed=Decimal("0.75000000"),
            personal_factor=Decimal("0.87500000"),
            importance=Decimal("0.80000000"),
            freshness=Decimal("0.90000000"),
            quality=Decimal("0.90000000"),
            novelty=Decimal("0.30000000"),
            unrounded_score=Decimal("0.8287500000000000"),
            final_score=Decimal("0.82875000"),
            eligible=True,
            eligibility_reason="eligible",
            explicit_protected=True,
            explicit_veto=False,
            initial_position=1,
            final_position=1,
            selection_reason="selected",
            diversity_pass=1,
        )
    )
    session.add(
        RankingParameterContribution(
            article_ranking_id=record_id,
            parameter_id=context["parameter"].id,
            parameter_snapshot_hash=_digest(f"contribution:{context['parameter'].id}"),
            parameter_name=context["parameter"].name,
            parameter_origin=PreferenceOrigin.EXPLICIT,
            effective_authority=PreferenceOrigin.EXPLICIT,
            weight=Decimal("0.80"),
            relevance=Decimal("0.7500"),
            contribution=Decimal("0.60000000"),
            explanation_ordinal=1,
        )
    )
    session.add(
        RankingAudit(
            id=record_id,
            ranking_run_id=run.id,
            user_id=context["user_id"],
            article_id=article["article_id"],
            profile_revision=context["profile_revision"],
            configuration_version="1.0",
            input_hash=_digest(f"input:{request_id}"),
            factor_hash=_digest(f"factor:{request_id}"),
            contribution_hash=_digest(f"contribution:{request_id}"),
            score_hash=_digest(f"score:{request_id}"),
            selection_hash=_digest(f"selection:{request_id}"),
            final_score=Decimal("0.82875000"),
            final_position=1,
            ranked_at=completed_at,
        )
    )
    await session.flush()
    return run.id


async def _seed_active_ranking_run(
    session,
    context: dict[str, object],
    *,
    request_id: str,
) -> UUID:
    await _ensure_configuration_snapshot(session)
    run = RankingRun(
        id=uuid4(),
        request_id=request_id,
        user_id=context["user_id"],
        profile_revision=context["profile_revision"],
        candidate_set_hash=_digest(f"candidate:{request_id}"),
        configuration_version="1.0",
        ranking_at=OLD,
        requested_count=1,
        status=RankingStatus.SCORING,
        selected_count=0,
        excluded_count=0,
        selected_cap_vector=None,
        unsatisfied_limits=[],
        error_code=None,
        completed_at=None,
        created_at=OLD,
        updated_at=OLD,
    )
    session.add(run)
    await session.flush()
    return run.id


async def _seed_explicit_request(
    session,
    context: dict[str, object],
    *,
    telegram_update_id: int,
    status: ExplicitRequestStatus,
    raw_text: str,
    completed_at: datetime | None,
    with_audit: bool = False,
) -> UUID:
    request = ExplicitPreferenceRequest(
        id=uuid4(),
        user_id=context["user_id"],
        telegram_update_id=telegram_update_id,
        normalized_text_hash=_digest(raw_text),
        raw_text=raw_text,
        language_code="en",
        status=status,
        schema_version="1.0",
        base_profile_revision=2 if with_audit else context["profile_revision"],
        interpretation_version="reviewed-fixture",
        proposal_hash=_digest(f"proposal:{telegram_update_id}") if with_audit else None,
        error_code="provider_error" if status is ExplicitRequestStatus.FAILED else None,
        completed_at=completed_at,
        created_at=completed_at or OLD,
        updated_at=completed_at or OLD,
    )
    session.add(request)
    await session.flush()

    if with_audit:
        batch = PreferenceUpdateBatch(
            id=uuid4(),
            explicit_request_id=request.id,
            user_id=context["user_id"],
            schema_version="1.0",
            base_profile_revision=2,
            resulting_profile_revision=3,
            proposal_hash=_digest(f"batch:{telegram_update_id}"),
            change_count=1,
            history_digest=_digest(f"history:{telegram_update_id}"),
            status=UpdateBatchStatus.APPLIED,
            created_at=completed_at or OLD,
            applied_at=completed_at,
        )
        session.add(batch)
        await session.flush()
        history_id = uuid4()
        session.add(
            PreferenceChangeHistory(
                id=history_id,
                batch_id=batch.id,
                parameter_id=context["parameter"].id,
                action=PreferenceAction.ADJUST,
                source=PreferenceOrigin.EXPLICIT,
                questionnaire_id=None,
                explicit_request_id=request.id,
                previous_state={"weight": "0.40", "active": True},
                new_state={"weight": "0.80", "active": True},
                reason="User explicitly asked for more Kirov city news.",
                changed_at=completed_at or OLD,
            )
        )
        session.add(
            PreferenceChangeAudit(
                id=history_id,
                batch_id=batch.id,
                parameter_id=context["parameter"].id,
                action=PreferenceAction.ADJUST,
                source=PreferenceOrigin.EXPLICIT,
                questionnaire_id=None,
                explicit_request_id=request.id,
                previous_state_hash=_digest(f"previous:{telegram_update_id}"),
                new_state_hash=_digest(f"new:{telegram_update_id}"),
                reason_hash=_digest(f"reason:{telegram_update_id}"),
                changed_at=completed_at or OLD,
            )
        )
        session.add(
            PreferenceEvidence(
                id=uuid4(),
                parameter_id=context["parameter"].id,
                user_id=context["user_id"],
                source=PreferenceOrigin.EXPLICIT,
                explicit_request_id=request.id,
                questionnaire_id=None,
                action=PreferenceAction.ADJUST,
                requested_weight=Decimal("0.80"),
                active=True,
                reason_hash=_digest(f"evidence:{telegram_update_id}"),
                created_at=completed_at or OLD,
            )
        )

    await session.flush()
    return request.id


async def test_cleanup_clears_expired_raw_text_and_raw_responses_without_touching_active_work(
    ranking_database,
) -> None:
    async with ranking_database.session() as session:
        context = await _seed_base_context(session, telegram_user_id=901)
        terminal_request_id = await _seed_explicit_request(
            session,
            context,
            telegram_update_id=9001,
            status=ExplicitRequestStatus.APPLIED,
            raw_text="Please send more Kirov city news",
            completed_at=OLD,
            with_audit=True,
        )
        active_request_id = await _seed_explicit_request(
            session,
            context,
            telegram_update_id=9002,
            status=ExplicitRequestStatus.RECEIVED,
            raw_text="Please keep this active request intact",
            completed_at=None,
        )
        current_article = await _seed_article(
            session, context, title="Current reusable article"
        )
        failed_article = await _seed_article(
            session, context, title="Failed evaluation article"
        )
        active_article = await _seed_article(
            session, context, title="Active evaluation article"
        )
        current_run_id = await _seed_evaluation_run(
            session,
            context,
            current_article,
            status=EvaluationStatus.COMPLETE,
            completed_at=OLD,
            raw_response={"content": "current raw response"},
        )
        failed_run_id = await _seed_evaluation_run(
            session,
            context,
            failed_article,
            status=EvaluationStatus.FAILED,
            completed_at=OLD,
            raw_response={"content": "failed raw response"},
            attempt_status=EvaluationAttemptStatus.FAILED,
            include_relevance=False,
        )
        active_run_id = await _seed_evaluation_run(
            session,
            context,
            active_article,
            status=EvaluationStatus.EVALUATING,
            completed_at=None,
            raw_response={"content": "active raw response"},
            attempt_status=EvaluationAttemptStatus.RECEIVED,
            include_relevance=False,
        )

    repository = SQLAlchemyRankingRepository(ranking_database)
    result = await repository.cleanup(
        NOW,
        RetentionPolicy(raw_response_days=30, detail_days=365, batch_size=50),
    )

    assert result.raw_texts_removed == 1
    assert result.raw_responses_removed == 2
    assert result.evaluation_details_removed == 0
    assert result.ranking_details_removed == 0

    async with ranking_database.session() as session:
        terminal_request = await session.get(
            ExplicitPreferenceRequest, terminal_request_id
        )
        active_request = await session.get(ExplicitPreferenceRequest, active_request_id)
        current_attempt = await session.scalar(
            select(ArticlePreferenceEvaluationAttempt).where(
                ArticlePreferenceEvaluationAttempt.run_id == current_run_id
            )
        )
        failed_attempt = await session.scalar(
            select(ArticlePreferenceEvaluationAttempt).where(
                ArticlePreferenceEvaluationAttempt.run_id == failed_run_id
            )
        )
        active_attempt = await session.scalar(
            select(ArticlePreferenceEvaluationAttempt).where(
                ArticlePreferenceEvaluationAttempt.run_id == active_run_id
            )
        )
        audit_count = await session.scalar(
            select(func.count()).select_from(PreferenceChangeAudit)
        )
        evidence_count = await session.scalar(
            select(func.count()).select_from(PreferenceEvidence)
        )

    assert terminal_request is not None and terminal_request.raw_text is None
    assert active_request is not None and active_request.raw_text is not None
    assert current_attempt is not None and current_attempt.raw_response is None
    assert failed_attempt is not None and failed_attempt.raw_response is None
    assert active_attempt is not None and active_attempt.raw_response is not None
    assert audit_count == 1
    assert evidence_count == 1


async def test_cleanup_deletes_only_expired_noncurrent_evaluation_details(
    ranking_database,
) -> None:
    async with ranking_database.session() as session:
        context = await _seed_base_context(session, telegram_user_id=902)
        current_article = await _seed_article(
            session, context, title="Current reusable article"
        )
        stale_article = await _seed_article(
            session, context, title="Stale evaluation article"
        )
        failed_article = await _seed_article(
            session, context, title="Failed evaluation article"
        )
        active_article = await _seed_article(
            session, context, title="Active evaluation article"
        )
        current_run_id = await _seed_evaluation_run(
            session,
            context,
            current_article,
            status=EvaluationStatus.COMPLETE,
            completed_at=OLD,
            raw_response={"content": "keep"},
        )
        stale_run_id = await _seed_evaluation_run(
            session,
            context,
            stale_article,
            status=EvaluationStatus.COMPLETE,
            completed_at=OLD,
            raw_response={"content": "delete"},
            profile_revision=2,
        )
        failed_run_id = await _seed_evaluation_run(
            session,
            context,
            failed_article,
            status=EvaluationStatus.FAILED,
            completed_at=OLD,
            raw_response={"content": "delete"},
            attempt_status=EvaluationAttemptStatus.FAILED,
            include_relevance=False,
        )
        active_run_id = await _seed_evaluation_run(
            session,
            context,
            active_article,
            status=EvaluationStatus.EVALUATING,
            completed_at=None,
            raw_response={"content": "keep active"},
            attempt_status=EvaluationAttemptStatus.RECEIVED,
            include_relevance=False,
        )

    repository = SQLAlchemyRankingRepository(ranking_database)
    result = await repository.cleanup(
        NOW,
        RetentionPolicy(raw_response_days=0, detail_days=90, batch_size=10),
    )

    assert result.raw_texts_removed == 0
    assert result.raw_responses_removed == 0
    assert result.evaluation_details_removed == 2

    async with ranking_database.session() as session:
        remaining_ids = set(
            await session.scalars(select(ArticlePreferenceEvaluationRun.id))
        )
        remaining_relevances = await session.scalar(
            select(func.count()).select_from(ArticleParameterRelevance)
        )

    assert current_run_id in remaining_ids
    assert active_run_id in remaining_ids
    assert stale_run_id not in remaining_ids
    assert failed_run_id not in remaining_ids
    assert remaining_relevances == 1


async def test_cleanup_compacts_expired_ranking_details_in_bounded_batches_and_preserves_audit(
    ranking_database,
) -> None:
    async with ranking_database.session() as session:
        context = await _seed_base_context(session, telegram_user_id=903)
        first_article = await _seed_article(
            session, context, title="First retained ranking"
        )
        second_article = await _seed_article(
            session, context, title="Second retained ranking"
        )
        first_eval = await _seed_evaluation_run(
            session,
            context,
            first_article,
            status=EvaluationStatus.COMPLETE,
            completed_at=OLD,
            raw_response={"content": "keep evaluation"},
        )
        second_eval = await _seed_evaluation_run(
            session,
            context,
            second_article,
            status=EvaluationStatus.COMPLETE,
            completed_at=OLD,
            raw_response={"content": "keep evaluation"},
        )
        await _seed_ranking_detail(
            session,
            context,
            first_article,
            first_eval,
            request_id="ranking-retention-a",
            completed_at=OLD - timedelta(days=1),
        )
        await _seed_ranking_detail(
            session,
            context,
            second_article,
            second_eval,
            request_id="ranking-retention-b",
            completed_at=OLD,
        )
        active_run_id = await _seed_active_ranking_run(
            session,
            context,
            request_id="ranking-retention-active",
        )

    repository = SQLAlchemyRankingRepository(ranking_database)
    first = await repository.cleanup(
        NOW,
        RetentionPolicy(raw_response_days=0, detail_days=90, batch_size=1),
    )

    assert first.ranking_details_removed == 1
    assert first.compact_audit_rows_preserved == 1

    async with ranking_database.session() as session:
        assert (
            await session.scalar(select(func.count()).select_from(ArticleRankingRecord))
            == 1
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(RankingParameterContribution)
            )
            == 1
        )
        assert await session.scalar(select(func.count()).select_from(RankingAudit)) == 2
        assert await session.scalar(select(func.count()).select_from(RankingRun)) == 3
        active_run = await session.get(RankingRun, active_run_id)

    assert active_run is not None and active_run.status is RankingStatus.SCORING

    second = await repository.cleanup(
        NOW,
        RetentionPolicy(raw_response_days=0, detail_days=90, batch_size=1),
    )

    assert second.ranking_details_removed == 1
    assert second.compact_audit_rows_preserved == 1

    async with ranking_database.session() as session:
        assert (
            await session.scalar(select(func.count()).select_from(ArticleRankingRecord))
            == 0
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(RankingParameterContribution)
            )
            == 0
        )
        assert await session.scalar(select(func.count()).select_from(RankingAudit)) == 2
        assert await session.scalar(select(func.count()).select_from(RankingRun)) == 3


async def test_cleanup_refuses_ranking_detail_deletion_without_compact_audit(
    ranking_database,
) -> None:
    async with ranking_database.session() as session:
        context = await _seed_base_context(session, telegram_user_id=904)
        article = await _seed_article(session, context, title="Audit refusal article")
        evaluation_run_id = await _seed_evaluation_run(
            session,
            context,
            article,
            status=EvaluationStatus.COMPLETE,
            completed_at=OLD,
            raw_response={"content": "keep evaluation"},
        )
        await _seed_ranking_detail(
            session,
            context,
            article,
            evaluation_run_id,
            request_id="ranking-missing-audit",
            completed_at=OLD,
        )
        await session.execute(
            text("ALTER TABLE ranking_audit DISABLE TRIGGER ranking_audit_immutable")
        )
        await session.execute(text("DELETE FROM ranking_audit"))
        await session.execute(
            text("ALTER TABLE ranking_audit ENABLE TRIGGER ranking_audit_immutable")
        )

    repository = SQLAlchemyRankingRepository(ranking_database)
    with pytest.raises(RuntimeError, match="compact audit"):
        await repository.cleanup(
            NOW,
            RetentionPolicy(raw_response_days=0, detail_days=90, batch_size=10),
        )

    async with ranking_database.session() as session:
        assert (
            await session.scalar(select(func.count()).select_from(ArticleRankingRecord))
            == 1
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(RankingParameterContribution)
            )
            == 1
        )
