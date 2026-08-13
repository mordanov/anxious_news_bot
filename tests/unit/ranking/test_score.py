from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from anxious_news_bot.preferences.domain import PreferenceOrigin
from anxious_news_bot.ranking.domain import (
    ArticleEvaluation,
    ArticleEvaluationIdentity,
    ArticleParameterRelevance,
    EligibilityReason,
    EvaluationStatus,
    PersonalState,
)
from anxious_news_bot.ranking.services.score import (
    DeterministicRankingScorer,
    contribution,
)
from tests.fixtures.ranking import (
    article_snapshot,
    ranking_configuration,
    ranking_preference,
)

RANKING_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _uuid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012d}")


def _evaluation(
    article_id: UUID,
    article_analysis_id: UUID,
    preferences,
    relevance_map: dict[UUID, str],
    *,
    status: EvaluationStatus = EvaluationStatus.COMPLETE,
) -> ArticleEvaluation:
    return ArticleEvaluation(
        run_id=uuid4(),
        identity=ArticleEvaluationIdentity(
            user_id=preferences[0].user_id if preferences else _uuid(999),
            article_id=article_id,
            article_analysis_id=article_analysis_id,
            profile_revision=3,
            parameter_set_hash="a" * 64,
            schema_version="1.0",
            evaluator_name="test-evaluator",
            evaluator_version="1.0",
            prompt_version="1.0",
        ),
        status=status,
        relevances=tuple(
            ArticleParameterRelevance(
                parameter_id=preference.id,
                relevance=Decimal(relevance_map[preference.id]),
                reason_code="clear_match",
            )
            for preference in preferences
            if preference.id in relevance_map
        ),
    )


def _score(preferences, relevance_map: dict[UUID, str] | None = None):
    scorer = DeterministicRankingScorer()
    article = article_snapshot(
        article_id=_uuid(100),
        article_analysis_id=_uuid(200),
        source_id=_uuid(300),
        published_at=RANKING_AT,
        importance_score=Decimal("0.1234"),
        novelty_score=Decimal("0.5678"),
        source_quality_score=Decimal("0.8765"),
    )
    evaluation = (
        _evaluation(
            article.article_id,
            article.article_analysis_id,
            preferences,
            relevance_map or {},
        )
        if relevance_map is not None
        else None
    )
    return scorer.score(
        article,
        ranking_configuration(),
        preferences,
        evaluation,
        ranking_at=RANKING_AT,
    )


def test_contribution_uses_exact_decimal_for_positive_negative_zero_and_boundaries() -> (
    None
):
    assert contribution(Decimal("0.80"), Decimal("0.7500")) == Decimal("0.60000000")
    assert contribution(Decimal("-0.80"), Decimal("0.7500")) == Decimal("-0.60000000")
    assert contribution(Decimal("0.00"), Decimal("1.0000")) == Decimal("0.00000000")
    assert contribution(Decimal("1.00"), Decimal("1.0000")) == Decimal("1.00000000")
    assert contribution(Decimal("-1.00"), Decimal("1.0000")) == Decimal("-1.00000000")


def test_score_uses_weighted_mean_normalization_and_cancelling_contributions() -> None:
    weighted_preferences = (
        ranking_preference(
            parameter_id=_uuid(1),
            user_id=_uuid(10),
            name="Primary",
            weight="0.90",
        ),
        ranking_preference(
            parameter_id=_uuid(2),
            user_id=_uuid(10),
            name="Secondary",
            weight="0.10",
        ),
    )
    weighted = _score(
        weighted_preferences,
        {
            weighted_preferences[0].id: "1.0000",
            weighted_preferences[1].id: "0.0000",
        },
    )

    assert weighted.personal_state is PersonalState.COMPLETE
    assert weighted.personal_numerator == Decimal("0.90000000")
    assert weighted.personal_denominator == Decimal("1.00000000")
    assert weighted.personal_signed == Decimal("0.90000000")
    assert weighted.personal_factor == Decimal("0.95000000")

    cancelling_preferences = (
        ranking_preference(
            parameter_id=_uuid(3),
            user_id=_uuid(11),
            name="Positive",
            weight="0.50",
        ),
        ranking_preference(
            parameter_id=_uuid(4),
            user_id=_uuid(11),
            name="Negative",
            weight="-0.50",
        ),
    )
    cancelling = _score(
        cancelling_preferences,
        {
            cancelling_preferences[0].id: "1.0000",
            cancelling_preferences[1].id: "1.0000",
        },
    )

    assert cancelling.personal_signed == Decimal("0.00000000")
    assert cancelling.personal_factor == Decimal("0.50000000")


def test_score_distinguishes_no_active_and_all_zero_profiles() -> None:
    no_active = _score(
        (
            ranking_preference(
                parameter_id=_uuid(5),
                user_id=_uuid(12),
                active=False,
            ),
        ),
        None,
    )
    assert no_active.personal_state is PersonalState.NO_ACTIVE_PARAMETERS
    assert no_active.personal_signed == Decimal("0.00000000")
    assert no_active.personal_factor == Decimal("0.50000000")
    assert no_active.eligible is True

    all_zero = _score(
        (
            ranking_preference(
                parameter_id=_uuid(6),
                user_id=_uuid(13),
                name="Zero A",
                weight="0.00",
                origin=PreferenceOrigin.EXPLICIT,
            ),
            ranking_preference(
                parameter_id=_uuid(7),
                user_id=_uuid(13),
                name="Zero B",
                weight="0.00",
                origin=PreferenceOrigin.QUESTIONNAIRE,
            ),
        ),
        None,
    )
    assert all_zero.personal_state is PersonalState.ALL_WEIGHTS_ZERO
    assert all_zero.personal_signed == Decimal("0.00000000")
    assert all_zero.personal_factor == Decimal("0.50000000")
    assert all_zero.eligible is True


def test_score_marks_missing_relevance_as_ineligible_without_silent_neutral_fallback() -> (
    None
):
    preferences = (
        ranking_preference(
            parameter_id=_uuid(8),
            user_id=_uuid(14),
            name="Covered",
            weight="0.80",
        ),
        ranking_preference(
            parameter_id=_uuid(9),
            user_id=_uuid(14),
            name="Missing",
            weight="0.60",
        ),
    )

    record = _score(
        preferences,
        {
            preferences[0].id: "1.0000",
        },
    )

    assert record.eligible is False
    assert record.eligibility_reason is EligibilityReason.INCOMPLETE_PERSONAL_EVALUATION
    assert record.personal_state is PersonalState.COMPLETE
    assert record.contributions == ()


def test_score_ignores_zero_weight_relevance_but_keeps_complete_evaluation() -> None:
    preferences = (
        ranking_preference(
            parameter_id=_uuid(18),
            user_id=_uuid(16),
            name="Weighted",
            weight="0.80",
        ),
        ranking_preference(
            parameter_id=_uuid(19),
            user_id=_uuid(16),
            name="Neutral",
            weight="0.00",
        ),
    )

    record = _score(
        preferences,
        {
            preferences[0].id: "0.7500",
            preferences[1].id: "-1.0000",
        },
    )

    assert record.eligible is True
    assert record.personal_state is PersonalState.COMPLETE
    assert record.personal_numerator == Decimal("0.60000000")
    assert record.personal_denominator == Decimal("0.80000000")
    assert record.personal_signed == Decimal("0.75000000")
    assert [item.parameter_id for item in record.contributions] == [preferences[0].id]


def test_score_quantizes_once_at_eight_places() -> None:
    preferences = (
        ranking_preference(
            parameter_id=_uuid(10),
            user_id=_uuid(15),
            name="Repeating A",
            weight="0.33",
        ),
        ranking_preference(
            parameter_id=_uuid(11),
            user_id=_uuid(15),
            name="Repeating B",
            weight="0.34",
        ),
    )

    record = _score(
        preferences,
        {
            preferences[0].id: "1.0000",
            preferences[1].id: "0.0000",
        },
    )

    assert record.personal_signed == Decimal("0.49253731")
    assert record.unrounded_score != record.final_score
    assert record.final_score == Decimal("0.65493090")


def test_score_rejects_binary_float_inputs() -> None:
    with pytest.raises(TypeError):
        contribution(0.50, Decimal("0.5000"))

    with pytest.raises(TypeError):
        contribution(Decimal("0.50"), 0.5000)
