from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select

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
from anxious_news_bot.ranking.domain import EvaluationStatus
from anxious_news_bot.ranking.infrastructure.models import (
    ArticleRankingRecord,
    RankingAudit,
    RankingConfigurationSnapshot,
    RankingParameterContribution,
)
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


def _score_8(value: Decimal) -> Decimal:
    return Decimal(f"{Decimal(value):.8f}")


def _score_16(value: Decimal) -> Decimal:
    return Decimal(f"{Decimal(value):.16f}")


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()


async def _seed_explainability_context(ranking_database) -> dict[str, object]:
    async with ranking_database.session() as session:
        user = ApplicationUser(telegram_user_id=820, language_code="en")
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
                id=_uuid(400 + index),
                name=f"source-{index}",
                source_type=SourceType.RSS,
                endpoint_url=f"https://example.com/explain/{index}.xml",
                region="World",
                language_code="en",
                enabled=True,
                polling_interval_seconds=300,
            )
            for index in range(1, 3)
        ]
        events = [
            EventGroup(
                id=_uuid(500 + index),
                label=f"Explain event {index}",
            )
            for index in range(1, 3)
        ]
        parameters = (
            PreferenceParameter(
                id=_uuid(601),
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
            ),
            PreferenceParameter(
                id=_uuid(602),
                user_id=user.id,
                semantic_key="celebrity_gossip",
                name="Celebrity gossip",
                description="Entertainment and celebrity rumors.",
                evaluation_instructions="Avoid celebrity gossip coverage.",
                weight=Decimal("-0.40"),
                origin=PreferenceOrigin.QUESTIONNAIRE,
                active=True,
                created_at=NOW + timedelta(seconds=1),
                updated_at=NOW + timedelta(seconds=1),
            ),
        )
        session.add_all((cycle, *sources, *events, *parameters))
        await session.flush()

        parameter_hash = parameter_set_hash(
            (
                ranking_preference(
                    parameter_id=parameters[0].id,
                    user_id=user.id,
                    semantic_key=parameters[0].semantic_key,
                    name=parameters[0].name,
                    description=parameters[0].description,
                    evaluation_instructions=parameters[0].evaluation_instructions,
                    weight="0.80",
                    origin=PreferenceOrigin.EXPLICIT,
                    effective_authority=PreferenceOrigin.EXPLICIT,
                ),
                ranking_preference(
                    parameter_id=parameters[1].id,
                    user_id=user.id,
                    semantic_key=parameters[1].semantic_key,
                    name=parameters[1].name,
                    description=parameters[1].description,
                    evaluation_instructions=parameters[1].evaluation_instructions,
                    weight="-0.40",
                    origin=PreferenceOrigin.QUESTIONNAIRE,
                    effective_authority=PreferenceOrigin.QUESTIONNAIRE,
                ),
            )
        )

        article_specs = (
            {
                "article_id": _uuid(701),
                "source": sources[0],
                "event": events[0],
                "topic": "local",
                "importance": Decimal("0.8000"),
                "novelty": Decimal("0.3000"),
                "quality": Decimal("0.9000"),
                "published_at": NOW - timedelta(hours=2),
                "relevances": (Decimal("0.9000"), Decimal("0.2500")),
            },
            {
                "article_id": _uuid(702),
                "source": sources[1],
                "event": events[1],
                "topic": "culture",
                "importance": Decimal("0.7000"),
                "novelty": Decimal("0.5000"),
                "quality": Decimal("0.9000"),
                "published_at": NOW - timedelta(hours=4),
                "relevances": (Decimal("0.4000"), Decimal("0.9000")),
            },
        )

        article_ids: list[UUID] = []
        for ordinal, spec in enumerate(article_specs, start=1):
            article = NormalizedArticle(
                id=spec["article_id"],
                title=f"Explainability article {ordinal}",
                summary=f"Explainability summary {ordinal}",
                canonical_url=f"https://example.com/explainability/{ordinal}",
                canonicalization_version="1.0",
                primary_source_id=spec["source"].id,
                published_at=spec["published_at"],
                ingested_at=NOW,
                language_code="en",
                normalized_text=f"Explainability normalized text {ordinal}",
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
            for parameter, relevance in zip(
                parameters,
                spec["relevances"],
                strict=True,
            ):
                session.add(
                    ArticleParameterRelevance(
                        evaluation_run_id=evaluation_run.id,
                        parameter_id=parameter.id,
                        parameter_snapshot_hash="a" * 64,
                        relevance=relevance,
                        reason_code="clear_match",
                    )
                )
            article_ids.append(article.id)

        return {
            "user_id": user.id,
            "article_ids": tuple(article_ids),
        }


def _input_payload(identity, record) -> dict[str, object]:
    return {
        "article_id": str(record.article_id),
        "article_analysis_id": str(record.article_analysis_id),
        "source_id": str(record.source_id),
        "event_group_id": str(record.event_group_id) if record.event_group_id else None,
        "topic_key": record.topic_key,
        "published_at": record.published_at.isoformat()
        if record.published_at
        else None,
        "evaluation_run_id": str(record.evaluation_run_id)
        if record.evaluation_run_id
        else None,
        "profile_revision": identity.profile_revision,
        "candidate_set_hash": identity.candidate_set_hash,
        "ranking_at": identity.ranking_at.isoformat(),
    }


def _factor_payload(configuration, record) -> dict[str, object]:
    return {
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


def _contribution_payload(record) -> dict[str, object]:
    return {
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


def _score_payload(record) -> dict[str, object]:
    return {
        "personal_numerator": f"{record.personal_numerator:.8f}",
        "personal_denominator": f"{record.personal_denominator:.8f}",
        "personal_signed": f"{record.personal_signed:.8f}",
        "unrounded_score": f"{Decimal(record.unrounded_score):.16f}",
        "final_score": f"{record.final_score:.8f}",
    }


def _selection_payload(record) -> dict[str, object]:
    return {
        "eligible": record.eligible,
        "eligibility_reason": record.eligibility_reason.value,
        "explicit_protected": record.explicit_protected,
        "explicit_veto": record.explicit_veto,
        "selected": record.selection.selected,
        "selection_reason": record.selection.reason.value,
        "position": record.selection.position,
        "diversity_pass": record.selection.diversity_pass,
    }


async def test_retained_ranking_records_reconstruct_scores_explanations_and_hashes(
    ranking_database,
) -> None:
    seeded = await _seed_explainability_context(ranking_database)
    configuration = replace(ranking_configuration(), source_cap=10, topic_cap=10)
    repository = SQLAlchemyRankingRepository(ranking_database)
    service = PersonalRankingService(
        repository,
        StaticRankingConfigurationProvider(configuration),
        DeterministicRankingScorer(),
        FixedClock(),
    )

    result = await service.rank(
        seeded["user_id"],
        "explainability",
        seeded["article_ids"],
        requested_count=2,
        ranking_at=NOW,
    )

    explainer = DeterministicRankingExplainer()

    async with ranking_database.session() as session:
        config_row = await session.scalar(select(RankingConfigurationSnapshot))
        rows = tuple(
            await session.scalars(
                select(ArticleRankingRecord).order_by(
                    ArticleRankingRecord.initial_position
                )
            )
        )
        contributions = tuple(
            await session.scalars(
                select(RankingParameterContribution).order_by(
                    RankingParameterContribution.article_ranking_id,
                    RankingParameterContribution.parameter_id,
                )
            )
        )
        audits = tuple(
            await session.scalars(
                select(RankingAudit).order_by(RankingAudit.article_id)
            )
        )

    assert config_row is not None
    stored_by_article = {row.article_id: row for row in rows}
    audit_by_article = {row.article_id: row for row in audits}
    contributions_by_record: dict[UUID, list[RankingParameterContribution]] = {}
    for contribution in contributions:
        contributions_by_record.setdefault(contribution.article_ranking_id, []).append(
            contribution
        )

    for record in result.records:
        stored = stored_by_article[record.article_id]
        stored_contributions = contributions_by_record[stored.id]
        numerator = sum(
            (Decimal(item.contribution) for item in stored_contributions),
            start=Decimal("0.00000000"),
        )
        denominator = sum(
            (abs(Decimal(item.weight)) for item in stored_contributions),
            start=Decimal("0.00000000"),
        )
        if denominator == Decimal("0.00000000"):
            signed = Decimal("0.00000000")
            factor = Decimal("0.50000000")
        else:
            signed_raw = numerator / denominator
            signed = _score_8(signed_raw)
            factor = _score_8((signed_raw + Decimal("1")) / Decimal("2"))

        assert _score_8(numerator) == Decimal(stored.personal_numerator)
        assert _score_8(denominator) == Decimal(stored.personal_denominator)
        assert signed == Decimal(stored.personal_signed)
        assert factor == Decimal(stored.personal_factor)

        reconstructed = _score_8(
            Decimal(config_row.personal_coefficient) * Decimal(stored.personal_factor)
            + Decimal(config_row.importance_coefficient) * Decimal(stored.importance)
            + Decimal(config_row.freshness_coefficient) * Decimal(stored.freshness)
            + Decimal(config_row.quality_coefficient) * Decimal(stored.quality)
            + Decimal(config_row.novelty_coefficient) * Decimal(stored.novelty)
        )
        assert reconstructed == Decimal(stored.final_score)

        explanation = explainer.explain(
            result.ranking_run_id,
            record,
            configuration_version=result.identity.configuration_version,
            contribution_limit=configuration.explanation_contribution_limit,
        )
        expected_top = [
            contribution.parameter_id for contribution in explanation.top_contributions
        ]
        stored_top = [
            contribution.parameter_id
            for contribution in sorted(
                stored_contributions,
                key=lambda item: item.explanation_ordinal or 99,
            )
            if contribution.explanation_ordinal is not None
        ]
        assert expected_top == stored_top

        audit = audit_by_article[record.article_id]
        assert audit.input_hash == _hash(_input_payload(result.identity, record))
        assert audit.factor_hash == _hash(_factor_payload(configuration, record))
        assert audit.contribution_hash == _hash(_contribution_payload(record))
        assert audit.score_hash == _hash(_score_payload(record))
        assert audit.selection_hash == _hash(_selection_payload(record))
        assert Decimal(audit.final_score) == _score_8(record.final_score)
        assert audit.final_position == record.selection.position
