from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select

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
from anxious_news_bot.ranking.infrastructure.models import RankingRun
from anxious_news_bot.ranking.infrastructure.persistence import (
    SQLAlchemyRankingRepository,
)
from anxious_news_bot.ranking.services.evaluate import parameter_set_hash
from anxious_news_bot.ranking.services.explain import DeterministicRankingExplainer
from anxious_news_bot.ranking.services.rank import PersonalRankingService
from anxious_news_bot.ranking.services.score import DeterministicRankingScorer
from tests.fixtures.ranking import (
    FixedClock,
    StaticRankingConfigurationProvider,
    ranking_configuration,
    ranking_preference,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _uuid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012d}")


async def _seed_determinism_context(ranking_database) -> dict[str, object]:
    async with ranking_database.session() as session:
        user = ApplicationUser(telegram_user_id=810, language_code="en")
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
                id=_uuid(100 + index),
                name=f"source-{index}",
                source_type=SourceType.RSS,
                endpoint_url=f"https://example.com/source-{index}.xml",
                region="World",
                language_code="en",
                enabled=True,
                polling_interval_seconds=300,
            )
            for index in range(1, 6)
        ]
        events = [
            EventGroup(
                id=_uuid(200 + index),
                label=f"Event {index}",
            )
            for index in range(1, 6)
        ]
        parameter = PreferenceParameter(
            id=_uuid(50),
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
        session.add_all((cycle, *sources, *events, parameter))
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

        article_specs = (
            {
                "slug": "tie-low-id",
                "article_id": _uuid(301),
                "source": sources[1],
                "event": events[0],
                "topic": "local",
                "importance": Decimal("0.8000"),
                "novelty": Decimal("0.4000"),
                "quality": Decimal("0.9000"),
                "relevance": Decimal("0.5000"),
                "published_at": NOW - timedelta(minutes=30),
            },
            {
                "slug": "tie-high-id",
                "article_id": _uuid(302),
                "source": sources[2],
                "event": events[1],
                "topic": "local",
                "importance": Decimal("0.8000"),
                "novelty": Decimal("0.4000"),
                "quality": Decimal("0.9000"),
                "relevance": Decimal("0.5000"),
                "published_at": NOW - timedelta(minutes=30),
            },
            {
                "slug": "source-conflict",
                "article_id": _uuid(303),
                "source": sources[1],
                "event": events[2],
                "topic": "civic",
                "importance": Decimal("0.7500"),
                "novelty": Decimal("0.3000"),
                "quality": Decimal("0.9000"),
                "relevance": Decimal("0.4000"),
                "published_at": NOW - timedelta(minutes=35),
            },
            {
                "slug": "fill",
                "article_id": _uuid(304),
                "source": sources[3],
                "event": events[3],
                "topic": "finance",
                "importance": Decimal("0.7000"),
                "novelty": Decimal("0.3500"),
                "quality": Decimal("0.9000"),
                "relevance": Decimal("0.3000"),
                "published_at": NOW - timedelta(minutes=40),
            },
            {
                "slug": "protected",
                "article_id": _uuid(305),
                "source": sources[0],
                "event": events[4],
                "topic": "transport",
                "importance": Decimal("0.0000"),
                "novelty": Decimal("0.1000"),
                "quality": Decimal("0.9000"),
                "relevance": Decimal("0.9000"),
                "published_at": NOW - timedelta(minutes=45),
            },
            {
                "slug": "ineligible",
                "article_id": _uuid(306),
                "source": sources[4],
                "event": events[0],
                "topic": "weather",
                "importance": Decimal("0.8500"),
                "novelty": Decimal("0.2000"),
                "quality": Decimal("0.2000"),
                "relevance": Decimal("0.7000"),
                "published_at": NOW - timedelta(minutes=50),
            },
        )

        article_ids: list[UUID] = []
        by_slug: dict[str, UUID] = {}
        for ordinal, spec in enumerate(article_specs, start=1):
            article = NormalizedArticle(
                id=spec["article_id"],
                title=f"Deterministic article {ordinal}",
                summary=f"Summary {ordinal}",
                canonical_url=f"https://example.com/deterministic/{ordinal}",
                canonicalization_version="1.0",
                primary_source_id=spec["source"].id,
                published_at=spec["published_at"],
                ingested_at=NOW,
                language_code="en",
                normalized_text=f"Deterministic text {ordinal}",
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
                novelty_score=spec["novelty"],
                source_quality_score=spec["quality"],
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
            session.add(
                ArticleParameterRelevance(
                    evaluation_run_id=evaluation_run.id,
                    parameter_id=parameter.id,
                    parameter_snapshot_hash="a" * 64,
                    relevance=spec["relevance"],
                    reason_code="clear_match",
                )
            )
            article_ids.append(article.id)
            by_slug[spec["slug"]] = article.id

        return {
            "user_id": user.id,
            "article_ids": tuple(article_ids),
            "article_by_slug": by_slug,
        }


def _payload(result, configuration) -> bytes:
    explainer = DeterministicRankingExplainer()
    explanations = [
        explainer.explain(
            result.ranking_run_id,
            record,
            configuration_version=result.identity.configuration_version,
            contribution_limit=configuration.explanation_contribution_limit,
        ).model_dump(mode="json")
        for record in result.records
    ]
    data = {
        "ranking_run_id": str(result.ranking_run_id),
        "status": result.status.value,
        "selected_count": result.selected_count,
        "excluded_count": result.excluded_count,
        "selected_cap_vector": result.selected_cap_vector,
        "unsatisfied_limits": result.unsatisfied_limits,
        "records": [
            {
                "article_id": str(record.article_id),
                "final_score": f"{record.final_score:.8f}",
                "personal_signed": f"{record.personal_signed:.8f}",
                "eligible": record.eligible,
                "eligibility_reason": record.eligibility_reason.value,
                "explicit_protected": record.explicit_protected,
                "selection_reason": record.selection.reason.value,
                "selection_position": record.selection.position,
                "initial_position": record.initial_position,
            }
            for record in result.records
        ],
        "explanations": explanations,
    }
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()


async def test_ranking_replays_byte_stably_for_one_hundred_identical_runs(
    ranking_database,
) -> None:
    seeded = await _seed_determinism_context(ranking_database)
    configuration = replace(
        ranking_configuration(),
        event_cap=10,
        topic_cap=10,
        source_cap=1,
    )
    repository = SQLAlchemyRankingRepository(ranking_database)
    service = PersonalRankingService(
        repository,
        StaticRankingConfigurationProvider(configuration),
        DeterministicRankingScorer(),
        FixedClock(),
    )

    results = []
    payloads: list[bytes] = []
    for index in range(100):
        result = await service.rank(
            seeded["user_id"],
            f"determinism-{index}",
            seeded["article_ids"],
            requested_count=4,
            ranking_at=NOW,
        )
        results.append(result)
        payloads.append(_payload(result, configuration))

    first = results[0]
    assert all(result.status is RankingStatus.COMPLETE for result in results)
    assert len({result.ranking_run_id for result in results}) == 1
    assert len(set(payloads)) == 1

    ordered_article_ids = [record.article_id for record in first.records]
    assert ordered_article_ids.index(
        seeded["article_by_slug"]["tie-low-id"]
    ) < ordered_article_ids.index(seeded["article_by_slug"]["tie-high-id"])

    by_article = {record.article_id: record for record in first.records}
    assert by_article[seeded["article_by_slug"]["protected"]].selection.position == 1
    assert by_article[seeded["article_by_slug"]["tie-low-id"]].selection.position == 2
    assert by_article[seeded["article_by_slug"]["tie-high-id"]].selection.position == 3
    assert by_article[seeded["article_by_slug"]["fill"]].selection.position == 4
    assert (
        by_article[seeded["article_by_slug"]["source-conflict"]].selection.reason.value
        == "rejected_source_cap"
    )
    assert (
        by_article[seeded["article_by_slug"]["ineligible"]].selection.reason.value
        == "ineligible"
    )

    async with ranking_database.session() as session:
        run_count = await session.scalar(select(func.count()).select_from(RankingRun))

    assert run_count == 1
