from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from anxious_news_bot.infrastructure.database import Database
from anxious_news_bot.news.domain import AnalysisStatus, CycleStatus, SourceType
from anxious_news_bot.news.infrastructure.models import (
    ArticleAnalysis,
    CollectionCycle,
    NewsSource,
    NormalizedArticle,
)
from anxious_news_bot.preferences.domain import PreferenceOrigin
from anxious_news_bot.preferences.infrastructure.models import (
    ApplicationUser,
    PreferenceParameter,
    PreferenceProfile,
)
from anxious_news_bot.ranking.domain import (
    EligibilityReason,
    EvaluationStatus,
    RankingStatus,
)
from anxious_news_bot.ranking.errors import RankingConfigurationError
from anxious_news_bot.ranking.infrastructure.models import (
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
from anxious_news_bot.ranking.services.evaluate import parameter_set_hash
from anxious_news_bot.ranking.services.rank import PersonalRankingService
from anxious_news_bot.ranking.services.score import DeterministicRankingScorer
from tests.fixtures.ranking import (
    FixedClock,
    StaticRankingConfigurationProvider,
    ranking_configuration,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def ranking_database(postgres_database_url):
    database = Database(postgres_database_url)
    try:
        yield database
    finally:
        async with database.session() as session:
            await session.execute(
                text(
                    "TRUNCATE ranking_audit, ranking_parameter_contributions, "
                    "article_ranking_records, ranking_runs, ranking_configuration_snapshots, "
                    "article_parameter_relevances, article_preference_evaluation_attempts, "
                    "article_preference_evaluation_runs, deduplication_decisions, "
                    "article_analyses, normalized_articles, event_groups, "
                    "source_article_records, source_runs, collection_cycles, news_sources, "
                    "preference_evidence, preference_change_audit, preference_change_history, "
                    "preference_update_batches, explicit_preference_requests, "
                    "preference_answers, preference_question_options, preference_questions, "
                    "preference_questionnaires, preference_parameters, preference_profiles, "
                    "application_users CASCADE"
                )
            )
        await database.close()


def _as_ranking_preference(parameter: PreferenceParameter):
    from anxious_news_bot.ranking.domain import RankingPreference

    return RankingPreference(
        id=parameter.id,
        user_id=parameter.user_id,
        semantic_key=parameter.semantic_key,
        name=parameter.name,
        description=parameter.description,
        evaluation_instructions=parameter.evaluation_instructions,
        weight=Decimal(parameter.weight),
        origin=parameter.origin,
        effective_authority=parameter.origin,
        active=parameter.active,
    )


async def _seed_user_context(
    database: Database,
    *,
    telegram_user_id: int,
    article_count: int,
    profile_revision: int = 3,
    base_title: str = "Article",
):
    async with database.session() as session:
        user = ApplicationUser(telegram_user_id=telegram_user_id, language_code="en")
        session.add(user)
        await session.flush()
        session.add(PreferenceProfile(user_id=user.id, revision=profile_revision))
        source = NewsSource(
            id=uuid4(),
            name=f"source-{telegram_user_id}",
            source_type=SourceType.RSS,
            endpoint_url=f"https://example.com/{telegram_user_id}.xml",
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
        parameters = [
            PreferenceParameter(
                id=uuid4(),
                user_id=user.id,
                semantic_key=f"preference_{index}",
                name=f"Preference {index}",
                description=f"Description {index}",
                evaluation_instructions=f"Evaluate {index}",
                weight=Decimal(weight),
                origin=PreferenceOrigin.EXPLICIT
                if index == 1
                else PreferenceOrigin.QUESTIONNAIRE,
                active=True,
                created_at=NOW + timedelta(seconds=index),
                updated_at=NOW + timedelta(seconds=index),
            )
            for index, weight in enumerate(("0.80", "0.20"), start=1)
        ]
        session.add_all((source, cycle, *parameters))
        await session.flush()

        ranking_preferences = tuple(
            _as_ranking_preference(parameter) for parameter in parameters
        )
        parameter_hash = parameter_set_hash(ranking_preferences)

        article_ids: list[UUID] = []
        for index in range(article_count):
            article = NormalizedArticle(
                id=uuid4(),
                title=f"{base_title} {index}",
                summary=f"Summary {index}",
                canonical_url=f"https://example.com/{telegram_user_id}/{index}",
                canonicalization_version="1.0",
                primary_source_id=source.id,
                published_at=NOW - timedelta(hours=index % 24),
                ingested_at=NOW,
                language_code="en",
                normalized_text=f"Normalized text {index}",
                created_in_cycle_id=cycle.id,
            )
            analysis = ArticleAnalysis(
                id=uuid4(),
                article_id=article.id,
                status=AnalysisStatus.COMPLETE,
                schema_version="1.0",
                analyzer_name="generic-analyzer",
                analyzer_version="1.0",
                topics=["local", f"topic-{index % 3}"],
                created_at=NOW,
                importance_score=Decimal("0.8000") - Decimal(index % 3) / Decimal("10"),
                novelty_score=Decimal("0.3000") + Decimal(index % 5) / Decimal("10"),
                source_quality_score=Decimal("0.9000"),
            )
            evaluation_run = ArticlePreferenceEvaluationRun(
                id=uuid4(),
                user_id=user.id,
                article_id=article.id,
                article_analysis_id=analysis.id,
                profile_revision=profile_revision,
                parameter_set_hash=parameter_hash,
                schema_version="1.0",
                evaluator_name="integration-evaluator",
                evaluator_version="1.0",
                prompt_version="prompt-v1",
                status=EvaluationStatus.COMPLETE,
                attempt_count=1,
                completed_at=NOW,
            )
            session.add_all((article, analysis))
            await session.flush()
            session.add(evaluation_run)
            await session.flush()
            for parameter, relevance in zip(
                parameters, ("0.7500", "0.2500"), strict=True
            ):
                from anxious_news_bot.ranking.infrastructure.models import (
                    ArticleParameterRelevance,
                )

                session.add(
                    ArticleParameterRelevance(
                        evaluation_run_id=evaluation_run.id,
                        parameter_id=parameter.id,
                        parameter_snapshot_hash="a" * 64,
                        relevance=Decimal(relevance),
                        reason_code="clear_match",
                    )
                )
            article_ids.append(article.id)

        return {
            "user_id": user.id,
            "article_ids": tuple(article_ids),
        }


class MutatingRepository(SQLAlchemyRankingRepository):
    def __init__(self, database: Database, mutate) -> None:
        super().__init__(database)
        self._mutate = mutate
        self._mutated = False

    async def persist_complete_run(self, result, configuration):
        if not self._mutated:
            await self._mutate()
            self._mutated = True
        return await super().persist_complete_run(result, configuration)


def _service(repository, configuration=None):
    return PersonalRankingService(
        repository,
        StaticRankingConfigurationProvider(configuration),
        DeterministicRankingScorer(),
        FixedClock(),
    )


@pytest.mark.asyncio
async def test_ranking_persists_atomic_runs_records_contributions_and_audits(
    ranking_database,
) -> None:
    seeded = await _seed_user_context(
        ranking_database, telegram_user_id=601, article_count=3
    )
    repository = SQLAlchemyRankingRepository(ranking_database)
    service = _service(repository)

    result = await service.rank(
        seeded["user_id"],
        "request-atomic",
        seeded["article_ids"],
        requested_count=3,
        ranking_at=NOW,
    )

    assert result.status is RankingStatus.COMPLETE

    async with ranking_database.session() as session:
        run_count = await session.scalar(select(func.count()).select_from(RankingRun))
        record_count = await session.scalar(
            select(func.count()).select_from(ArticleRankingRecord)
        )
        contribution_count = await session.scalar(
            select(func.count()).select_from(RankingParameterContribution)
        )
        audit_count = await session.scalar(
            select(func.count()).select_from(RankingAudit)
        )
        config_row = await session.scalar(select(RankingConfigurationSnapshot))
        stored_record = await session.scalar(
            select(ArticleRankingRecord)
            .order_by(ArticleRankingRecord.initial_position)
            .limit(1)
        )

    assert run_count == 1
    assert record_count == 3
    assert contribution_count == 6
    assert audit_count == 3
    assert config_row is not None
    assert stored_record is not None

    reconstructed = (
        config_row.personal_coefficient * stored_record.personal_factor
        + config_row.importance_coefficient * stored_record.importance
        + config_row.freshness_coefficient * stored_record.freshness
        + config_row.quality_coefficient * stored_record.quality
        + config_row.novelty_coefficient * stored_record.novelty
    ).quantize(Decimal("0.00000001"))
    assert reconstructed == stored_record.final_score


@pytest.mark.asyncio
async def test_ranking_persists_missing_analysis_candidate_as_ineligible(
    ranking_database,
) -> None:
    seeded = await _seed_user_context(
        ranking_database, telegram_user_id=608, article_count=1
    )
    async with ranking_database.session() as session:
        source_id = await session.scalar(select(NewsSource.id))
        cycle_id = await session.scalar(select(CollectionCycle.id))
        missing = NormalizedArticle(
            id=uuid4(),
            title="Missing analysis",
            summary="No generic analysis is available yet.",
            canonical_url="https://example.com/608/missing-analysis",
            canonicalization_version="1.0",
            primary_source_id=source_id,
            published_at=NOW,
            ingested_at=NOW,
            language_code="en",
            normalized_text="Missing generic analysis candidate",
            created_in_cycle_id=cycle_id,
        )
        session.add(missing)
        await session.flush()
        missing_id = missing.id

    repository = SQLAlchemyRankingRepository(ranking_database)
    service = _service(repository)
    candidate_ids = (*seeded["article_ids"], missing_id)

    result = await service.rank(
        seeded["user_id"],
        "request-missing-analysis",
        candidate_ids,
        requested_count=2,
        ranking_at=NOW,
    )
    replay = await service.rank(
        seeded["user_id"],
        "request-missing-analysis",
        tuple(reversed(candidate_ids)),
        requested_count=2,
        ranking_at=NOW,
    )

    missing_record = next(
        record for record in result.records if record.article_id == missing_id
    )
    async with ranking_database.session() as session:
        stored = await session.scalar(
            select(ArticleRankingRecord).where(
                ArticleRankingRecord.article_id == missing_id
            )
        )

    assert result.status is RankingStatus.COMPLETE
    assert missing_record.article_analysis_id is None
    assert missing_record.eligible is False
    assert (
        missing_record.eligibility_reason is EligibilityReason.MISSING_GENERIC_ANALYSIS
    )
    assert stored is not None
    assert stored.article_analysis_id is None
    assert replay.ranking_run_id == result.ranking_run_id
    assert replay.identity.candidate_set_hash == result.identity.candidate_set_hash


@pytest.mark.asyncio
async def test_configuration_versions_are_immutable_once_referenced(
    ranking_database,
) -> None:
    seeded = await _seed_user_context(
        ranking_database, telegram_user_id=602, article_count=1
    )
    repository = SQLAlchemyRankingRepository(ranking_database)
    await _service(repository).rank(
        seeded["user_id"],
        "request-config-1",
        seeded["article_ids"],
        requested_count=1,
        ranking_at=NOW,
    )

    incompatible = replace(
        ranking_configuration(),
        quality_coefficient=Decimal("0.15000"),
        novelty_coefficient=Decimal("0.05000"),
    )
    with pytest.raises(RankingConfigurationError):
        await _service(repository, incompatible).rank(
            seeded["user_id"],
            "request-config-2",
            seeded["article_ids"],
            requested_count=1,
            ranking_at=NOW,
        )


@pytest.mark.asyncio
async def test_input_version_recheck_marks_runs_stale_without_persisting_records(
    ranking_database,
) -> None:
    seeded = await _seed_user_context(
        ranking_database, telegram_user_id=603, article_count=1
    )

    async def mutate() -> None:
        async with ranking_database.session() as session:
            profile = await session.get(PreferenceProfile, seeded["user_id"])
            profile.revision += 1

    repository = MutatingRepository(ranking_database, mutate)
    result = await _service(repository).rank(
        seeded["user_id"],
        "request-stale",
        seeded["article_ids"],
        requested_count=1,
        ranking_at=NOW,
    )

    assert result.status is RankingStatus.STALE

    async with ranking_database.session() as session:
        run = await session.scalar(select(RankingRun))
        record_count = await session.scalar(
            select(func.count()).select_from(ArticleRankingRecord)
        )
    assert run is not None and run.status is RankingStatus.STALE
    assert record_count == 0


@pytest.mark.asyncio
async def test_concurrent_replay_and_user_isolation(
    ranking_database,
) -> None:
    successful = await _seed_user_context(
        ranking_database, telegram_user_id=604, article_count=2
    )
    failing = await _seed_user_context(
        ranking_database, telegram_user_id=605, article_count=1
    )

    async def mutate_failure() -> None:
        async with ranking_database.session() as session:
            profile = await session.get(PreferenceProfile, failing["user_id"])
            profile.revision += 1

    normal_repository = SQLAlchemyRankingRepository(ranking_database)
    stale_repository = MutatingRepository(ranking_database, mutate_failure)
    normal_service = _service(normal_repository)
    stale_service = _service(stale_repository)

    first, second, stale = await asyncio.gather(
        normal_service.rank(
            successful["user_id"],
            "request-success",
            successful["article_ids"],
            requested_count=2,
            ranking_at=NOW,
        ),
        normal_service.rank(
            successful["user_id"],
            "request-success",
            successful["article_ids"],
            requested_count=2,
            ranking_at=NOW,
        ),
        stale_service.rank(
            failing["user_id"],
            "request-failure",
            failing["article_ids"],
            requested_count=1,
            ranking_at=NOW,
        ),
    )

    assert first.ranking_run_id == second.ranking_run_id
    assert first.status is RankingStatus.COMPLETE
    assert stale.status is RankingStatus.STALE

    async with ranking_database.session() as session:
        run_count = await session.scalar(select(func.count()).select_from(RankingRun))
    assert run_count == 2


@pytest.mark.asyncio
async def test_ranking_audit_is_append_only(
    ranking_database,
) -> None:
    seeded = await _seed_user_context(
        ranking_database, telegram_user_id=606, article_count=1
    )
    repository = SQLAlchemyRankingRepository(ranking_database)
    await _service(repository).rank(
        seeded["user_id"],
        "request-audit",
        seeded["article_ids"],
        requested_count=1,
        ranking_at=NOW,
    )

    async with ranking_database.session() as session:
        audit = await session.scalar(select(RankingAudit))
        assert audit is not None
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                audit.final_score = Decimal("0.00000000")
                await session.flush()


@pytest.mark.asyncio
async def test_ranking_handles_five_hundred_candidates_within_budget(
    ranking_database,
) -> None:
    seeded = await _seed_user_context(
        ranking_database,
        telegram_user_id=607,
        article_count=500,
        base_title="Performance article",
    )
    repository = SQLAlchemyRankingRepository(ranking_database)
    service = _service(repository)

    started = time.perf_counter()
    result = await service.rank(
        seeded["user_id"],
        "request-performance",
        seeded["article_ids"],
        requested_count=50,
        ranking_at=NOW,
    )
    elapsed = time.perf_counter() - started

    assert result.status is RankingStatus.COMPLETE
    assert len(result.records) == 500
    assert elapsed < 5.0
