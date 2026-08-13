from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from anxious_news_bot.news.domain import DecisionOutcome
from anxious_news_bot.ranking.domain import (
    ArticleEvaluation,
    ArticleEvaluationIdentity,
    ArticleParameterRelevance,
    EligibilityReason,
    EvaluationStatus,
)
from anxious_news_bot.ranking.services.eligibility import determine_eligibility
from tests.fixtures.ranking import (
    article_snapshot,
    ranking_configuration,
    ranking_preference,
)

RANKING_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _uuid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012d}")


def _evaluation(
    article_id: UUID, analysis_id: UUID, preferences, relevance: str = "0.7500"
):
    return ArticleEvaluation(
        run_id=uuid4(),
        identity=ArticleEvaluationIdentity(
            user_id=preferences[0].user_id if preferences else _uuid(999),
            article_id=article_id,
            article_analysis_id=analysis_id,
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
                relevance=Decimal(relevance),
                reason_code="clear_match",
            )
            for preference in preferences
        ),
    )


def test_determine_eligibility_handles_incomplete_generic_and_personal_evidence() -> (
    None
):
    preferences = (
        ranking_preference(
            parameter_id=_uuid(1),
            user_id=_uuid(10),
            name="Local",
            weight="0.80",
        ),
    )
    incomplete_generic_article = article_snapshot(
        article_id=_uuid(100),
        article_analysis_id=_uuid(200),
        source_id=_uuid(300),
        published_at=RANKING_AT,
        importance_score=None,
    )

    generic = determine_eligibility(
        incomplete_generic_article,
        ranking_configuration(),
        preferences,
        None,
        ranking_at=RANKING_AT,
    )
    assert generic.eligible is False
    assert generic.reason is EligibilityReason.INCOMPLETE_GENERIC_ANALYSIS

    incomplete_personal = determine_eligibility(
        article_snapshot(
            article_id=_uuid(101),
            article_analysis_id=_uuid(201),
            source_id=_uuid(301),
            published_at=RANKING_AT,
        ),
        ranking_configuration(),
        preferences,
        None,
        ranking_at=RANKING_AT,
    )
    assert incomplete_personal.eligible is False
    assert (
        incomplete_personal.reason is EligibilityReason.INCOMPLETE_PERSONAL_EVALUATION
    )


def test_determine_eligibility_allows_zero_weight_relevance_in_complete_evaluation() -> (
    None
):
    preferences = (
        ranking_preference(
            parameter_id=_uuid(20),
            user_id=_uuid(10),
            name="Weighted",
            weight="0.80",
        ),
        ranking_preference(
            parameter_id=_uuid(21),
            user_id=_uuid(10),
            name="Neutral",
            weight="0.00",
        ),
    )
    article = article_snapshot(
        article_id=_uuid(120),
        article_analysis_id=_uuid(220),
        source_id=_uuid(320),
        published_at=RANKING_AT,
    )

    decision = determine_eligibility(
        article,
        ranking_configuration(),
        preferences,
        _evaluation(article.article_id, article.article_analysis_id, preferences),
        ranking_at=RANKING_AT,
    )

    assert decision.eligible is True
    assert decision.reason is EligibilityReason.ELIGIBLE


def test_determine_eligibility_enforces_source_quality_and_publication_rules() -> None:
    preferences = ()
    configuration = ranking_configuration()

    low_quality = determine_eligibility(
        article_snapshot(
            article_id=_uuid(102),
            article_analysis_id=_uuid(202),
            source_id=_uuid(302),
            published_at=RANKING_AT,
            source_quality_score=Decimal("0.3000"),
        ),
        configuration,
        preferences,
        None,
        ranking_at=RANKING_AT,
    )
    assert low_quality.reason is EligibilityReason.SOURCE_QUALITY_BELOW_MINIMUM

    missing_published_at = determine_eligibility(
        article_snapshot(
            article_id=_uuid(103),
            article_analysis_id=_uuid(203),
            source_id=_uuid(303),
            published_at=None,
        ),
        configuration,
        preferences,
        None,
        ranking_at=RANKING_AT,
    )
    assert missing_published_at.reason is EligibilityReason.INVALID_PUBLISHED_AT

    future = determine_eligibility(
        article_snapshot(
            article_id=_uuid(104),
            article_analysis_id=_uuid(204),
            source_id=_uuid(304),
            published_at=RANKING_AT
            + timedelta(seconds=configuration.future_tolerance_seconds + 1),
        ),
        configuration,
        preferences,
        None,
        ranking_at=RANKING_AT,
    )
    assert future.reason is EligibilityReason.FUTURE_PUBLICATION

    obsolete = determine_eligibility(
        article_snapshot(
            article_id=_uuid(105),
            article_analysis_id=_uuid(205),
            source_id=_uuid(305),
            published_at=RANKING_AT
            - timedelta(seconds=configuration.freshness_horizon_seconds + 1),
        ),
        configuration,
        preferences,
        None,
        ranking_at=RANKING_AT,
    )
    assert obsolete.reason is EligibilityReason.OBSOLETE_PUBLICATION


def test_determine_eligibility_rejects_duplicates_and_explicit_vetoes() -> None:
    preference = ranking_preference(
        parameter_id=_uuid(2),
        user_id=_uuid(11),
        name="Avoid celebrity politics",
        weight="0.80",
    )
    article = article_snapshot(
        article_id=_uuid(106),
        article_analysis_id=_uuid(206),
        source_id=_uuid(306),
        published_at=RANKING_AT,
        duplicate_outcome=DecisionOutcome.DUPLICATE,
    )
    evaluation = _evaluation(
        article.article_id, article.article_analysis_id, (preference,)
    )

    duplicate = determine_eligibility(
        article,
        ranking_configuration(),
        (),
        None,
        ranking_at=RANKING_AT,
    )
    assert duplicate.reason is EligibilityReason.DISQUALIFYING_DUPLICATE

    veto_article = article_snapshot(
        article_id=_uuid(107),
        article_analysis_id=_uuid(207),
        source_id=_uuid(307),
        published_at=RANKING_AT,
    )
    veto = determine_eligibility(
        veto_article,
        ranking_configuration(),
        (preference,),
        ArticleEvaluation(
            run_id=evaluation.run_id,
            identity=_evaluation(
                veto_article.article_id,
                veto_article.article_analysis_id,
                (preference,),
            ).identity,
            status=EvaluationStatus.COMPLETE,
            relevances=(
                ArticleParameterRelevance(
                    parameter_id=preference.id,
                    relevance=Decimal("-0.7000"),
                    reason_code="clear_mismatch",
                ),
            ),
        ),
        ranking_at=RANKING_AT,
    )
    assert veto.eligible is False
    assert veto.explicit_veto is True
    assert veto.reason is EligibilityReason.EXPLICIT_VETO


def test_determine_eligibility_uses_deterministic_reason_precedence() -> None:
    preference = ranking_preference(
        parameter_id=_uuid(3),
        user_id=_uuid(12),
        weight="0.80",
    )
    article = article_snapshot(
        article_id=_uuid(108),
        article_analysis_id=_uuid(208),
        source_id=_uuid(308),
        published_at=RANKING_AT
        + timedelta(seconds=ranking_configuration().future_tolerance_seconds + 1),
        source_quality_score=Decimal("0.1000"),
        duplicate_outcome=DecisionOutcome.DUPLICATE,
    )
    decision = determine_eligibility(
        article,
        ranking_configuration(),
        (preference,),
        None,
        ranking_at=RANKING_AT,
    )

    assert decision.eligible is False
    assert decision.reason is EligibilityReason.INCOMPLETE_PERSONAL_EVALUATION
