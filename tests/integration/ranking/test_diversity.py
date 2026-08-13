from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

from anxious_news_bot.infrastructure.database import Database
from anxious_news_bot.news.domain import AnalysisStatus, CycleStatus, SourceType
from anxious_news_bot.news.infrastructure.models import (
    ArticleAnalysis,
    CollectionCycle,
    EventGroup,
    NewsSource,
    NormalizedArticle,
)
from anxious_news_bot.preferences.domain import PreferenceOrigin
from anxious_news_bot.preferences.infrastructure.models import (
    ApplicationUser,
    PreferenceParameter,
    PreferenceProfile,
)
from anxious_news_bot.ranking.domain import EvaluationStatus, RankingStatus
from anxious_news_bot.ranking.infrastructure.models import (
    ArticlePreferenceEvaluationRun,
    ArticleRankingRecord,
    RankingAudit,
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
    ranking_preference,
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


def _service(repository, configuration):
    return PersonalRankingService(
        repository,
        StaticRankingConfigurationProvider(configuration),
        DeterministicRankingScorer(),
        FixedClock(),
    )


async def _seed_diversity_context(database: Database):
    async with database.session() as session:
        user = ApplicationUser(telegram_user_id=701, language_code="en")
        session.add(user)
        await session.flush()
        session.add(PreferenceProfile(user_id=user.id, revision=3))

        cycle = CollectionCycle(
            id=uuid4(),
            status=CycleStatus.RUNNING,
            started_at=NOW,
            configuration_version="test",
        )
        sources = [
            NewsSource(
                id=uuid4(),
                name=f"source-{index}",
                source_type=SourceType.RSS,
                endpoint_url=f"https://example.com/source-{index}.xml",
                region="World",
                language_code="en",
                enabled=True,
                polling_interval_seconds=300,
            )
            for index in range(1, 4)
        ]
        events = [
            EventGroup(
                id=uuid4(),
                label=f"Event {index}",
            )
            for index in range(1, 4)
        ]
        preference = PreferenceParameter(
            id=uuid4(),
            user_id=user.id,
            semantic_key="local_priority",
            name="Local priority",
            description="Prioritize local public-interest coverage",
            evaluation_instructions="Prefer strong local public-interest coverage",
            weight=Decimal("0.80"),
            origin=PreferenceOrigin.EXPLICIT,
            active=True,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add_all((cycle, *sources, *events, preference))
        await session.flush()

        parameter_hash = parameter_set_hash(
            (
                ranking_preference(
                    parameter_id=preference.id,
                    user_id=user.id,
                    semantic_key=preference.semantic_key,
                    name=preference.name,
                    description=preference.description,
                    evaluation_instructions=preference.evaluation_instructions,
                    weight="0.80",
                    origin=PreferenceOrigin.EXPLICIT,
                    effective_authority=PreferenceOrigin.EXPLICIT,
                ),
            )
        )

        article_specs = (
            {
                "slug": "source-conflict",
                "source": sources[0],
                "event": events[0],
                "topic": "local",
                "importance": Decimal("1.0000"),
                "relevance": Decimal("0.5500"),
            },
            {
                "slug": "event-conflict",
                "source": sources[1],
                "event": events[0],
                "topic": "finance",
                "importance": Decimal("0.9000"),
                "relevance": Decimal("0.5000"),
            },
            {
                "slug": "topic-conflict",
                "source": sources[2],
                "event": events[1],
                "topic": "finance",
                "importance": Decimal("0.8500"),
                "relevance": Decimal("0.4500"),
            },
            {
                "slug": "protected",
                "source": sources[0],
                "event": events[2],
                "topic": "science",
                "importance": Decimal("0.0000"),
                "relevance": Decimal("0.9000"),
            },
        )

        article_ids: list[UUID] = []
        article_by_slug: dict[str, UUID] = {}
        for index, spec in enumerate(article_specs, start=1):
            article = NormalizedArticle(
                id=uuid4(),
                title=f"Diversity article {index}",
                summary=f"Summary {index}",
                canonical_url=f"https://example.com/diversity/{index}",
                canonicalization_version="1.0",
                primary_source_id=spec["source"].id,
                published_at=NOW - timedelta(minutes=index),
                ingested_at=NOW,
                language_code="en",
                normalized_text=f"Normalized text {index}",
                event_group_id=spec["event"].id,
                created_in_cycle_id=cycle.id,
            )
            analysis = ArticleAnalysis(
                id=uuid4(),
                article_id=article.id,
                status=AnalysisStatus.COMPLETE,
                schema_version="1.0",
                analyzer_name="generic-analyzer",
                analyzer_version="1.0",
                topics=[spec["topic"]],
                created_at=NOW,
                importance_score=spec["importance"],
                novelty_score=Decimal("0.4000"),
                source_quality_score=Decimal("0.9000"),
            )
            evaluation_run = ArticlePreferenceEvaluationRun(
                id=uuid4(),
                user_id=user.id,
                article_id=article.id,
                article_analysis_id=analysis.id,
                profile_revision=3,
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
            from anxious_news_bot.ranking.infrastructure.models import (
                ArticleParameterRelevance,
            )

            session.add(
                ArticleParameterRelevance(
                    evaluation_run_id=evaluation_run.id,
                    parameter_id=preference.id,
                    parameter_snapshot_hash="a" * 64,
                    relevance=spec["relevance"],
                    reason_code="clear_match",
                )
            )
            article_ids.append(article.id)
            article_by_slug[spec["slug"]] = article.id

        return {
            "user_id": user.id,
            "article_ids": tuple(article_ids),
            "article_by_slug": article_by_slug,
        }


@pytest.mark.asyncio
async def test_diversity_persists_cap_vectors_reasons_positions_and_selection_hashes(
    ranking_database,
) -> None:
    seeded = await _seed_diversity_context(ranking_database)
    configuration = replace(
        ranking_configuration(),
        event_cap=1,
        topic_cap=1,
        source_cap=1,
    )
    repository = SQLAlchemyRankingRepository(ranking_database)

    result = await _service(repository, configuration).rank(
        seeded["user_id"],
        "diversity-request",
        seeded["article_ids"],
        requested_count=3,
        ranking_at=NOW,
    )

    assert result.status is RankingStatus.COMPLETE
    assert result.selected_cap_vector == (
        configuration.event_cap,
        configuration.topic_cap,
        configuration.maximum_candidate_count,
    )
    assert result.unsatisfied_limits == ("source",)

    async with ranking_database.session() as session:
        run = await session.scalar(select(RankingRun))
        records = tuple(
            await session.scalars(
                select(ArticleRankingRecord).order_by(
                    ArticleRankingRecord.initial_position
                )
            )
        )
        audits = tuple(
            await session.scalars(
                select(RankingAudit).order_by(RankingAudit.article_id)
            )
        )

    assert run is not None
    assert run.selected_cap_vector == {
        "event": configuration.event_cap,
        "topic": configuration.topic_cap,
        "source": configuration.maximum_candidate_count,
    }
    assert run.unsatisfied_limits == ["source"]

    by_article = {record.article_id: record for record in records}
    protected = by_article[seeded["article_by_slug"]["protected"]]
    source_conflict = by_article[seeded["article_by_slug"]["source-conflict"]]
    event_conflict = by_article[seeded["article_by_slug"]["event-conflict"]]
    topic_conflict = by_article[seeded["article_by_slug"]["topic-conflict"]]

    assert protected.explicit_protected is True
    assert protected.initial_position > 1
    assert protected.final_position == 1
    assert protected.selection_reason == "selected"
    assert protected.diversity_pass == 2

    assert source_conflict.final_position == 2
    assert source_conflict.selection_reason == "selected"
    assert source_conflict.diversity_pass == 2
    assert event_conflict.final_position is None
    assert event_conflict.selection_reason == "rejected_event_cap"
    assert topic_conflict.final_position == 3
    assert topic_conflict.selection_reason == "selected"
    assert topic_conflict.diversity_pass == 2

    assert sorted(
        record.final_position for record in records if record.final_position is not None
    ) == [1, 2, 3]
    assert all(len(audit.selection_hash) == 64 for audit in audits)
    assert len({audit.selection_hash for audit in audits}) >= 2


@pytest.mark.asyncio
async def test_diversity_replays_deterministically_for_identical_snapshot(
    ranking_database,
) -> None:
    seeded = await _seed_diversity_context(ranking_database)
    configuration = replace(
        ranking_configuration(),
        event_cap=1,
        topic_cap=1,
        source_cap=1,
    )
    repository = SQLAlchemyRankingRepository(ranking_database)
    service = _service(repository, configuration)

    first = await service.rank(
        seeded["user_id"],
        "diversity-request-a",
        seeded["article_ids"],
        requested_count=3,
        ranking_at=NOW,
    )
    replay = await service.rank(
        seeded["user_id"],
        "diversity-request-b",
        seeded["article_ids"],
        requested_count=3,
        ranking_at=NOW,
    )

    assert replay.ranking_run_id == first.ranking_run_id
    assert replay.selected_cap_vector == first.selected_cap_vector
    assert replay.unsatisfied_limits == first.unsatisfied_limits
    assert [
        (record.article_id, record.selection.reason, record.selection.position)
        for record in replay.records
    ] == [
        (record.article_id, record.selection.reason, record.selection.position)
        for record in first.records
    ]

    async with ranking_database.session() as session:
        run_count = await session.scalar(select(func.count()).select_from(RankingRun))
        selection_hashes = tuple(
            await session.scalars(
                select(RankingAudit.selection_hash).order_by(RankingAudit.article_id)
            )
        )

    assert run_count == 1
    assert selection_hashes
    assert all(len(value) == 64 for value in selection_hashes)
