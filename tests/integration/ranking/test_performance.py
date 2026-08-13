from __future__ import annotations

import math
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

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
from anxious_news_bot.ranking.domain import (
    ArticleEvaluation,
    ArticleEvaluationIdentity,
    ArticleParameterRelevance,
    EvaluationStatus,
    RankingStatus,
)
from anxious_news_bot.ranking.infrastructure.persistence import (
    SQLAlchemyRankingRepository,
)
from anxious_news_bot.ranking.services.diversify import DeterministicDiversitySelector
from anxious_news_bot.ranking.services.evaluate import parameter_set_hash
from anxious_news_bot.ranking.services.rank import PersonalRankingService
from anxious_news_bot.ranking.services.score import (
    DeterministicRankingScorer,
    order_records,
    with_initial_positions,
)
from tests.fixtures.ranking import (
    FixedClock,
    StaticRankingConfigurationProvider,
    article_snapshot,
    ranking_configuration,
    ranking_preference,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _uuid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012d}")


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def _scoring_inputs(count: int = 500):
    preferences = tuple(
        ranking_preference(
            parameter_id=_uuid(1000 + index),
            user_id=_uuid(2000),
            semantic_key=f"preference_{index}",
            name=f"Preference {index}",
            weight=f"{Decimal('0.10') if index % 2 else Decimal('-0.10'):.2f}",
            origin=PreferenceOrigin.EXPLICIT
            if index == 1
            else PreferenceOrigin.QUESTIONNAIRE,
            effective_authority=PreferenceOrigin.EXPLICIT
            if index == 1
            else PreferenceOrigin.QUESTIONNAIRE,
        )
        for index in range(1, 9)
    )
    articles = tuple(
        article_snapshot(
            article_id=_uuid(3000 + index),
            article_analysis_id=_uuid(4000 + index),
            source_id=_uuid(5000 + (index % 40)),
            published_at=NOW - timedelta(minutes=index % 180),
            topic_key=f"topic-{index % 25}",
            importance_score=Decimal("0.5000") + Decimal(index % 5) / Decimal("10"),
            novelty_score=Decimal("0.2000") + Decimal(index % 4) / Decimal("10"),
            source_quality_score=Decimal("0.7000") + Decimal(index % 3) / Decimal("10"),
        )
        for index in range(count)
    )
    evaluations = {
        article.article_id: ArticleEvaluation(
            run_id=uuid4(),
            identity=ArticleEvaluationIdentity(
                user_id=preferences[0].user_id,
                article_id=article.article_id,
                article_analysis_id=article.article_analysis_id,
                profile_revision=3,
                parameter_set_hash="a" * 64,
                schema_version="1.0",
                evaluator_name="test-evaluator",
                evaluator_version="1.0",
                prompt_version="1.0",
            ),
            status=EvaluationStatus.COMPLETE,
            relevances=tuple(
                ArticleParameterRelevance(
                    parameter_id=preference.id,
                    relevance=Decimal(f"{((index + offset) % 9 - 4) / 4:.4f}"),
                    reason_code="clear_match",
                )
                for offset, preference in enumerate(preferences, start=1)
            ),
        )
        for index, article in enumerate(articles)
    }
    return preferences, articles, evaluations


async def _seed_performance_context(ranking_database) -> dict[str, object]:
    async with ranking_database.session() as session:
        user = ApplicationUser(telegram_user_id=830, language_code="en")
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
                id=_uuid(6000 + index),
                name=f"source-{index}",
                source_type=SourceType.RSS,
                endpoint_url=f"https://example.com/performance/{index}.xml",
                region="World",
                language_code="en",
                enabled=True,
                polling_interval_seconds=300,
            )
            for index in range(1, 21)
        ]
        events = [
            EventGroup(
                id=_uuid(7000 + index),
                label=f"Performance event {index}",
            )
            for index in range(1, 31)
        ]
        parameters = [
            PreferenceParameter(
                id=_uuid(8000 + index),
                user_id=user.id,
                semantic_key=f"preference_{index}",
                name=f"Preference {index}",
                description=f"Description {index}",
                evaluation_instructions=f"Evaluate preference {index}",
                weight=Decimal(weight),
                origin=PreferenceOrigin.EXPLICIT
                if index == 1
                else PreferenceOrigin.QUESTIONNAIRE,
                active=True,
                created_at=NOW + timedelta(seconds=index),
                updated_at=NOW + timedelta(seconds=index),
            )
            for index, weight in enumerate(("0.80", "0.30", "-0.20"), start=1)
        ]
        session.add_all((cycle, *sources, *events, *parameters))
        await session.flush()

        ranking_preferences = tuple(
            ranking_preference(
                parameter_id=parameter.id,
                user_id=user.id,
                semantic_key=parameter.semantic_key,
                name=parameter.name,
                description=parameter.description,
                evaluation_instructions=parameter.evaluation_instructions,
                weight=f"{Decimal(parameter.weight):.2f}",
                origin=parameter.origin,
                effective_authority=parameter.origin,
            )
            for parameter in parameters
        )
        parameter_hash = parameter_set_hash(ranking_preferences)

        article_ids: list[UUID] = []
        for index in range(500):
            article = NormalizedArticle(
                id=uuid4(),
                title=f"Performance article {index}",
                summary=f"Summary {index}",
                canonical_url=f"https://example.com/performance/{index}",
                canonicalization_version="1.0",
                primary_source_id=sources[index % len(sources)].id,
                published_at=NOW - timedelta(minutes=index % 180),
                ingested_at=NOW,
                language_code="en",
                normalized_text=f"Performance text {index}",
                event_group_id=events[index % len(events)].id,
                created_in_cycle_id=cycle.id,
            )
            analysis = ArticleAnalysis(
                id=uuid4(),
                article_id=article.id,
                status=AnalysisStatus.COMPLETE,
                schema_version="1.0",
                analyzer_name="generic-analyzer",
                analyzer_version="1.0",
                topics=[f"topic-{index % 50}"],
                created_at=NOW,
                importance_score=Decimal("0.5000") + Decimal(index % 5) / Decimal("10"),
                novelty_score=Decimal("0.2000") + Decimal(index % 4) / Decimal("10"),
                source_quality_score=Decimal("0.7000")
                + Decimal(index % 3) / Decimal("10"),
            )
            from anxious_news_bot.ranking.infrastructure.models import (
                ArticleParameterRelevance,
                ArticlePreferenceEvaluationRun,
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
            for offset, parameter in enumerate(parameters, start=1):
                session.add(
                    ArticleParameterRelevance(
                        evaluation_run_id=evaluation_run.id,
                        parameter_id=parameter.id,
                        parameter_snapshot_hash="a" * 64,
                        relevance=Decimal(f"{((index + offset) % 9 - 4) / 4:.4f}"),
                        reason_code="clear_match",
                    )
                )
            article_ids.append(article.id)

        return {
            "user_id": user.id,
            "article_ids": tuple(article_ids),
        }


def test_pure_scoring_and_diversity_meet_five_hundred_candidate_latency_budget() -> (
    None
):
    configuration = ranking_configuration()
    preferences, articles, evaluations = _scoring_inputs()
    scorer = DeterministicRankingScorer()
    selector = DeterministicDiversitySelector()

    latencies: list[float] = []
    for _ in range(20):
        started = time.perf_counter()
        ordered = with_initial_positions(
            order_records(
                tuple(
                    scorer.score(
                        article,
                        configuration,
                        preferences,
                        evaluations[article.article_id],
                        ranking_at=NOW,
                    )
                    for article in articles
                )
            )
        )
        selection = selector.select(
            ordered,
            requested_count=50,
            configuration=configuration,
        )
        assert len(selection.records) == 500
        latencies.append(time.perf_counter() - started)

    assert _p95(latencies) < 0.5


async def test_end_to_end_ranking_meets_sc011_for_already_evaluated_candidates(
    ranking_database,
) -> None:
    seeded = await _seed_performance_context(ranking_database)
    repository = SQLAlchemyRankingRepository(ranking_database)
    service = PersonalRankingService(
        repository,
        StaticRankingConfigurationProvider(ranking_configuration()),
        DeterministicRankingScorer(),
        FixedClock(),
    )

    latencies: list[float] = []
    for index in range(5):
        started = time.perf_counter()
        result = await service.rank(
            seeded["user_id"],
            f"performance-{index}",
            seeded["article_ids"],
            requested_count=50,
            ranking_at=NOW + timedelta(seconds=index),
        )
        latencies.append(time.perf_counter() - started)
        assert result.status is RankingStatus.COMPLETE
        assert len(result.records) == 500

    assert _p95(latencies) < 5.0
