from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

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
    ArticleEvaluation,
    ArticleParameterRelevance,
    EvaluationStatus,
)
from anxious_news_bot.ranking.errors import EvaluationError
from anxious_news_bot.ranking.infrastructure.models import (
    ArticleParameterRelevance as ArticleParameterRelevanceModel,
)
from anxious_news_bot.ranking.infrastructure.models import (
    ArticlePreferenceEvaluationAttempt,
    ArticlePreferenceEvaluationRun,
)
from anxious_news_bot.ranking.infrastructure.persistence import (
    SQLAlchemyRankingRepository,
)
from anxious_news_bot.ranking.services.evaluate import ArticleEvaluationService
from tests.fixtures.ranking import FixedClock

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
                    "TRUNCATE article_parameter_relevances, "
                    "article_preference_evaluation_attempts, "
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


@pytest_asyncio.fixture
async def ranking_repository(ranking_database):
    return SQLAlchemyRankingRepository(ranking_database)


async def _seed_context(
    database: Database,
    *,
    telegram_user_id: int,
    preference_weights: tuple[str, ...] = ("0.80",),
    profile_revision: int = 3,
    analysis_version: str = "generic-v1",
    article_suffix: str | None = None,
):
    suffix = article_suffix or uuid4().hex
    async with database.session() as session:
        user = ApplicationUser(telegram_user_id=telegram_user_id, language_code="en")
        session.add(user)
        await session.flush()
        profile = PreferenceProfile(user_id=user.id, revision=profile_revision)
        source = NewsSource(
            id=uuid4(),
            name=f"source-{suffix}",
            source_type=SourceType.RSS,
            endpoint_url=f"https://{suffix}.example/feed",
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
        article = NormalizedArticle(
            id=uuid4(),
            title=f"Article {suffix}",
            summary="A focused local civic article.",
            canonical_url=f"https://example.com/{suffix}",
            canonicalization_version="1.0",
            primary_source_id=source.id,
            published_at=NOW,
            ingested_at=NOW,
            language_code="en",
            normalized_text=(
                "Kirov city council discussed local transport funding and neighborhood "
                "services in a detailed civic report."
            ),
            created_in_cycle_id=cycle.id,
        )
        analysis = ArticleAnalysis(
            id=uuid4(),
            article_id=article.id,
            status=AnalysisStatus.COMPLETE,
            schema_version="1.0",
            analyzer_name="generic-analyzer",
            analyzer_version=analysis_version,
            created_at=NOW,
            importance_score=Decimal("0.8000"),
            novelty_score=Decimal("0.3000"),
            source_quality_score=Decimal("0.9000"),
        )
        parameters = [
            PreferenceParameter(
                id=uuid4(),
                user_id=user.id,
                semantic_key=f"preference_{index}",
                name=f"Preference {index}",
                description=f"Preference description {index}",
                evaluation_instructions=f"Evaluate preference {index}",
                weight=Decimal(weight),
                origin=PreferenceOrigin.EXPLICIT,
                active=True,
                created_at=NOW,
                updated_at=NOW,
            )
            for index, weight in enumerate(preference_weights, start=1)
        ]
        session.add_all((profile, source, cycle, article, analysis, *parameters))
        await session.flush()
        return {
            "user_id": user.id,
            "article_id": article.id,
            "analysis_id": analysis.id,
            "parameter_ids": tuple(parameter.id for parameter in parameters),
            "preference_weights": tuple(
                Decimal(weight) for weight in preference_weights
            ),
        }


class OneShotEvaluator:
    def __init__(self, builder) -> None:
        self.builder = builder
        self.calls = 0

    async def evaluate(self, article_snapshot, profile_snapshot, evaluation_identity):
        self.calls += 1
        return self.builder(article_snapshot, profile_snapshot, evaluation_identity)


def _valid_builder(
    parameter_ids: tuple[UUID, ...], *, reason_code: str = "clear_match"
):
    def builder(article_snapshot, profile_snapshot, evaluation_identity):
        return {
            "schema_version": "1.0",
            "article_id": article_snapshot.article_id,
            "article_analysis_id": article_snapshot.article_analysis_id,
            "profile_revision": profile_snapshot.revision,
            "parameter_set_hash": evaluation_identity.parameter_set_hash,
            "relevances": [
                {
                    "parameter_id": parameter_id,
                    "relevance": "0.7500",
                    "reason_code": reason_code,
                }
                for parameter_id in parameter_ids
            ],
        }

    return builder


def _invalid_builder(parameter_ids: tuple[UUID, ...]):
    def builder(article_snapshot, profile_snapshot, evaluation_identity):
        value = _valid_builder(parameter_ids)(
            article_snapshot, profile_snapshot, evaluation_identity
        )
        value["relevances"][0]["reason_code"] = "Bad Reason"
        return value

    return builder


def _service(repository, evaluator):
    return ArticleEvaluationService(
        repository,
        evaluator,
        FixedClock(),
        evaluator_name="integration-evaluator",
        evaluator_version="1.0",
        prompt_version="prompt-v1",
        retry_attempts=3,
    )


async def test_identity_replay_append_only_attempts_and_unique_accepted_attempt(
    ranking_database,
    ranking_repository,
) -> None:
    seeded = await _seed_context(ranking_database, telegram_user_id=501)
    evaluator = OneShotEvaluator(_valid_builder(seeded["parameter_ids"]))
    service = _service(ranking_repository, evaluator)

    first = await service.evaluate(seeded["user_id"], seeded["article_id"])
    second = await service.evaluate(seeded["user_id"], seeded["article_id"])

    assert first.status is EvaluationStatus.COMPLETE
    assert second.run_id == first.run_id
    assert evaluator.calls == 1

    async with ranking_database.session() as session:
        run_count = await session.scalar(
            select(func.count()).select_from(ArticlePreferenceEvaluationRun)
        )
        attempt_rows = (
            await session.scalars(select(ArticlePreferenceEvaluationAttempt))
        ).all()
        distinct_accepted = await session.scalar(
            select(
                func.count(
                    func.distinct(ArticlePreferenceEvaluationRun.accepted_attempt_id)
                )
            ).where(ArticlePreferenceEvaluationRun.accepted_attempt_id.is_not(None))
        )
    assert run_count == 1
    assert len(attempt_rows) == 1
    assert distinct_accepted == 1

    second_run = ArticlePreferenceEvaluationRun(
        user_id=seeded["user_id"],
        article_id=seeded["article_id"],
        article_analysis_id=seeded["analysis_id"],
        profile_revision=99,
        parameter_set_hash="f" * 64,
        schema_version="1.0",
        evaluator_name="integration-evaluator",
        evaluator_version="2.0",
        prompt_version="prompt-v2",
        status=EvaluationStatus.PENDING,
        attempt_count=0,
    )
    async with ranking_database.session() as session:
        session.add(second_run)
        await session.flush()
        second_run.accepted_attempt_id = attempt_rows[0].id
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_accept_evaluation_rejects_incomplete_coverage_and_wrong_user_parameters(
    ranking_database,
    ranking_repository,
) -> None:
    seeded = await _seed_context(
        ranking_database,
        telegram_user_id=502,
        preference_weights=("0.70", "0.50"),
    )
    other = await _seed_context(ranking_database, telegram_user_id=503)
    (
        article_snapshot,
        profile_snapshot,
        preferences,
    ) = await ranking_repository.load_evaluation_context(
        seeded["user_id"],
        seeded["article_id"],
    )
    claim = await ranking_repository.claim_evaluation(
        _service(
            ranking_repository,
            OneShotEvaluator(_valid_builder(seeded["parameter_ids"])),
        ).build_identity(
            seeded["user_id"],
            article_snapshot,
            profile_snapshot,
            preferences,
        )
    )

    missing = ArticleEvaluation(
        run_id=claim.run_id,
        identity=claim.identity,
        status=EvaluationStatus.COMPLETE,
        relevances=(
            ArticleParameterRelevance(
                parameter_id=seeded["parameter_ids"][0],
                relevance=Decimal("0.7500"),
                reason_code="clear_match",
            ),
        ),
    )
    with pytest.raises(EvaluationError, match="exactly once"):
        await ranking_repository.accept_evaluation(claim.run_id, None, missing)

    wrong_user = ArticleEvaluation(
        run_id=claim.run_id,
        identity=claim.identity,
        status=EvaluationStatus.COMPLETE,
        relevances=(
            ArticleParameterRelevance(
                parameter_id=seeded["parameter_ids"][0],
                relevance=Decimal("0.7500"),
                reason_code="clear_match",
            ),
            ArticleParameterRelevance(
                parameter_id=other["parameter_ids"][0],
                relevance=Decimal("0.7500"),
                reason_code="clear_match",
            ),
        ),
    )
    with pytest.raises(EvaluationError, match="exactly once"):
        await ranking_repository.accept_evaluation(claim.run_id, None, wrong_user)

    async with ranking_database.session() as session:
        relevance_count = await session.scalar(
            select(func.count()).select_from(ArticleParameterRelevanceModel)
        )
    assert relevance_count == 0


async def test_concurrent_claims_share_one_versioned_run(
    ranking_database,
) -> None:
    seeded = await _seed_context(ranking_database, telegram_user_id=504)
    repository_a = SQLAlchemyRankingRepository(ranking_database)
    repository_b = SQLAlchemyRankingRepository(ranking_database)
    (
        article_snapshot,
        profile_snapshot,
        preferences,
    ) = await repository_a.load_evaluation_context(
        seeded["user_id"], seeded["article_id"]
    )
    identity = _service(
        repository_a, OneShotEvaluator(_valid_builder(seeded["parameter_ids"]))
    ).build_identity(
        seeded["user_id"],
        article_snapshot,
        profile_snapshot,
        preferences,
    )

    first, second = await asyncio.gather(
        repository_a.claim_evaluation(identity),
        repository_b.claim_evaluation(identity),
    )

    assert {first.run_id, second.run_id} == {first.run_id}
    assert {first.status, second.status} == {
        EvaluationStatus.PENDING,
        EvaluationStatus.EVALUATING,
    }

    async with ranking_database.session() as session:
        run_count = await session.scalar(
            select(func.count()).select_from(ArticlePreferenceEvaluationRun)
        )
    assert run_count == 1


async def test_new_versions_preserve_prior_valid_evidence_and_allow_later_reprocessing(
    ranking_database,
    ranking_repository,
) -> None:
    seeded = await _seed_context(ranking_database, telegram_user_id=505)
    complete_service = _service(
        ranking_repository,
        OneShotEvaluator(_valid_builder(seeded["parameter_ids"])),
    )
    first = await complete_service.evaluate(seeded["user_id"], seeded["article_id"])
    assert first.status is EvaluationStatus.COMPLETE

    async with ranking_database.session() as session:
        parameter = await session.get(PreferenceParameter, seeded["parameter_ids"][0])
        profile = await session.get(PreferenceProfile, seeded["user_id"])
        profile.revision += 1
        parameter.weight = Decimal("0.95")
        session.add(
            ArticleAnalysis(
                id=uuid4(),
                article_id=seeded["article_id"],
                status=AnalysisStatus.COMPLETE,
                schema_version="1.0",
                analyzer_name="generic-analyzer",
                analyzer_version="generic-v2",
                created_at=NOW,
                importance_score=Decimal("0.8200"),
                novelty_score=Decimal("0.3500"),
                source_quality_score=Decimal("0.9100"),
            )
        )

    invalid_service = _service(
        ranking_repository,
        OneShotEvaluator(_invalid_builder(seeded["parameter_ids"])),
    )
    failed = await invalid_service.evaluate(seeded["user_id"], seeded["article_id"])
    assert failed.status is EvaluationStatus.INCOMPLETE

    async with ranking_database.session() as session:
        runs = (
            await session.scalars(
                select(ArticlePreferenceEvaluationRun).order_by(
                    ArticlePreferenceEvaluationRun.profile_revision,
                    ArticlePreferenceEvaluationRun.created_at,
                )
            )
        ).all()
        relevance_count = await session.scalar(
            select(func.count()).select_from(ArticleParameterRelevanceModel)
        )
    assert [run.status for run in runs] == [
        EvaluationStatus.COMPLETE,
        EvaluationStatus.INCOMPLETE,
    ]
    assert relevance_count == 1

    recovered_service = _service(
        ranking_repository,
        OneShotEvaluator(_valid_builder(seeded["parameter_ids"])),
    )
    recovered = await recovered_service.evaluate(
        seeded["user_id"], seeded["article_id"]
    )
    assert recovered.status is EvaluationStatus.COMPLETE

    async with ranking_database.session() as session:
        runs = (
            await session.scalars(
                select(ArticlePreferenceEvaluationRun).order_by(
                    ArticlePreferenceEvaluationRun.profile_revision,
                    ArticlePreferenceEvaluationRun.created_at,
                )
            )
        ).all()
        attempt_counts = [run.attempt_count for run in runs]
        relevance_count = await session.scalar(
            select(func.count()).select_from(ArticleParameterRelevanceModel)
        )
    assert [run.status for run in runs] == [
        EvaluationStatus.COMPLETE,
        EvaluationStatus.COMPLETE,
    ]
    assert attempt_counts == [1, 2]
    assert relevance_count == 2
