from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from anxious_news_bot.ranking.domain import RankingPreference
from tests.fixtures.ranking import ranking_preference


@dataclass(frozen=True, slots=True)
class ReviewedParameterEvaluation:
    preference: RankingPreference
    relevance: str
    reason_code: str
    expected_direction: str
    expected_metric: str


@dataclass(frozen=True, slots=True)
class ReviewedEvaluationCase:
    slug: str
    language_code: str
    article_id: UUID
    article_analysis_id: UUID
    profile_revision: int
    article_title: str
    article_summary: str | None
    article_text: str
    evaluations: tuple[ReviewedParameterEvaluation, ...]


USER_ID = uuid4()

_MATCHING = ReviewedEvaluationCase(
    slug="matching-positive",
    language_code="en",
    article_id=uuid4(),
    article_analysis_id=uuid4(),
    profile_revision=3,
    article_title="Kirov opens a new tram line",
    article_summary="City officials confirmed the line will connect local districts.",
    article_text=(
        "Kirov city officials approved a new tram line and neighborhood reporting "
        "focuses on local transport, city hall votes, and district residents."
    ),
    evaluations=(
        ReviewedParameterEvaluation(
            preference=ranking_preference(
                parameter_id=uuid4(),
                user_id=USER_ID,
                semantic_key="kirov_city_news",
                name="Kirov city news",
                weight="0.85",
            ),
            relevance="0.9250",
            reason_code="clear_match",
            expected_direction="aligned",
            expected_metric="0.9250",
        ),
    ),
)

_NEUTRAL = ReviewedEvaluationCase(
    slug="neutral-coverage",
    language_code="en",
    article_id=uuid4(),
    article_analysis_id=uuid4(),
    profile_revision=3,
    article_title="Rainfall totals rise across the region",
    article_summary="Meteorologists summarized routine weather measurements.",
    article_text=(
        "Regional weather stations published rainfall totals and temperature charts "
        "without discussing agricultural policy or farm subsidies."
    ),
    evaluations=(
        ReviewedParameterEvaluation(
            preference=ranking_preference(
                parameter_id=uuid4(),
                user_id=USER_ID,
                semantic_key="farm_subsidies",
                name="Farm subsidies",
                weight="0.60",
            ),
            relevance="0.0000",
            reason_code="neutral_topic",
            expected_direction="neutral",
            expected_metric="0.0000",
        ),
    ),
)

_CONTRADICTION = ReviewedEvaluationCase(
    slug="contradiction-positive",
    language_code="en",
    article_id=uuid4(),
    article_analysis_id=uuid4(),
    profile_revision=3,
    article_title="Highway expansion replaces city tram project",
    article_summary="Officials canceled local rail plans in favor of roads.",
    article_text=(
        "The city scrapped the tram project and redirected funding away from public "
        "transport toward highway expansion."
    ),
    evaluations=(
        ReviewedParameterEvaluation(
            preference=ranking_preference(
                parameter_id=uuid4(),
                user_id=USER_ID,
                semantic_key="public_transport",
                name="Public transport",
                weight="0.75",
            ),
            relevance="-0.8500",
            reason_code="strong_conflict",
            expected_direction="contradiction",
            expected_metric="-0.8500",
        ),
    ),
)

_MULTILINGUAL = ReviewedEvaluationCase(
    slug="multilingual-russian",
    language_code="ru",
    article_id=uuid4(),
    article_analysis_id=uuid4(),
    profile_revision=3,
    article_title="Киров обсуждает новые городские маршруты",
    article_summary="Муниципалитет представил план городского транспорта.",
    article_text=(
        "В Кирове обсудили новые городские маршруты, работу муниципального "
        "транспорта и обращения жителей районов."
    ),
    evaluations=(
        ReviewedParameterEvaluation(
            preference=ranking_preference(
                parameter_id=uuid4(),
                user_id=USER_ID,
                semantic_key="kirov_transport",
                name="Kirov transport",
                weight="0.80",
            ),
            relevance="0.8000",
            reason_code="language_match",
            expected_direction="aligned",
            expected_metric="0.8000",
        ),
    ),
)

_BROAD_SPECIFIC = ReviewedEvaluationCase(
    slug="broad-vs-specific",
    language_code="en",
    article_id=uuid4(),
    article_analysis_id=uuid4(),
    profile_revision=3,
    article_title="Kirov city council debates a school budget",
    article_summary="The story is local, civic, and narrowly focused on Kirov.",
    article_text=(
        "Kirov city council members debated the municipal school budget and heard "
        "testimony from local families and district teachers."
    ),
    evaluations=(
        ReviewedParameterEvaluation(
            preference=ranking_preference(
                parameter_id=uuid4(),
                user_id=USER_ID,
                semantic_key="russia_news",
                name="Russia news",
                weight="0.55",
            ),
            relevance="0.5000",
            reason_code="broad_match",
            expected_direction="aligned",
            expected_metric="0.5000",
        ),
        ReviewedParameterEvaluation(
            preference=ranking_preference(
                parameter_id=uuid4(),
                user_id=USER_ID,
                semantic_key="kirov_city_news",
                name="Kirov city news",
                weight="0.90",
            ),
            relevance="0.9500",
            reason_code="specific_match",
            expected_direction="aligned",
            expected_metric="0.9500",
        ),
    ),
)

_NEGATIVE_WEIGHT = ReviewedEvaluationCase(
    slug="negative-weight",
    language_code="en",
    article_id=uuid4(),
    article_analysis_id=uuid4(),
    profile_revision=3,
    article_title="Celebrity gossip dominates regional portals",
    article_summary="Entertainment rumors crowded out local public-interest stories.",
    article_text=(
        "Celebrity gossip and entertainment rumors dominated regional homepages, "
        "with no substantive civic reporting in the lead stories."
    ),
    evaluations=(
        ReviewedParameterEvaluation(
            preference=ranking_preference(
                parameter_id=uuid4(),
                user_id=USER_ID,
                semantic_key="celebrity_gossip",
                name="Celebrity gossip",
                weight="-0.80",
            ),
            relevance="0.8750",
            reason_code="undesired_match",
            expected_direction="contradiction",
            expected_metric="-0.8750",
        ),
    ),
)

_ZERO_WEIGHT = ReviewedEvaluationCase(
    slug="zero-weight",
    language_code="en",
    article_id=uuid4(),
    article_analysis_id=uuid4(),
    profile_revision=3,
    article_title="Long-form profile of a local artist",
    article_summary="The article strongly matches an inactive preference dimension.",
    article_text=(
        "A long-form profile covered an artist's exhibition, local gallery plans, "
        "and detailed interviews about public culture projects."
    ),
    evaluations=(
        ReviewedParameterEvaluation(
            preference=ranking_preference(
                parameter_id=uuid4(),
                user_id=USER_ID,
                semantic_key="arts_features",
                name="Arts features",
                weight="0.00",
            ),
            relevance="0.9500",
            reason_code="strong_match",
            expected_direction="neutral",
            expected_metric="0.0000",
        ),
    ),
)

REVIEWED_EVALUATION_CASES = (
    _MATCHING,
    _NEUTRAL,
    _CONTRADICTION,
    _MULTILINGUAL,
    _BROAD_SPECIFIC,
    _NEGATIVE_WEIGHT,
    _ZERO_WEIGHT,
)

__all__ = [
    "REVIEWED_EVALUATION_CASES",
    "ReviewedEvaluationCase",
    "ReviewedParameterEvaluation",
]
