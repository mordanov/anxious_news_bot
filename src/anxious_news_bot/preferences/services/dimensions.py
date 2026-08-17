from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from anxious_news_bot.preferences.domain import PriorAnswer, QuestionDimensionContext


@dataclass(frozen=True, slots=True)
class QuestionnaireDimension:
    key: str
    guidance: str


DIMENSIONS = (
    QuestionnaireDimension("topic_politics", "interest in politics and government"),
    QuestionnaireDimension("topic_economy", "interest in economics and employment"),
    QuestionnaireDimension("topic_business", "interest in companies and markets"),
    QuestionnaireDimension("topic_science", "interest in scientific discoveries"),
    QuestionnaireDimension(
        "topic_technology", "interest in technology and digital life"
    ),
    QuestionnaireDimension("topic_health", "interest in health and medicine"),
    QuestionnaireDimension("topic_climate", "interest in climate and environment"),
    QuestionnaireDimension("topic_culture", "interest in arts and culture"),
    QuestionnaireDimension("topic_sports", "interest in sports"),
    QuestionnaireDimension(
        "geography_scope", "local versus national or global coverage"
    ),
    QuestionnaireDimension("regional_focus", "regions or countries to prioritize"),
    QuestionnaireDimension("reporting_depth", "brief summaries versus deep reporting"),
    QuestionnaireDimension("article_length", "preferred article length"),
    QuestionnaireDimension("update_frequency", "preferred frequency of updates"),
    QuestionnaireDimension("breaking_news", "appetite for fast breaking-news alerts"),
    QuestionnaireDimension(
        "follow_up_coverage", "interest in follow-ups as events develop"
    ),
    QuestionnaireDimension(
        "source_authority", "institutional versus independent sources"
    ),
    QuestionnaireDimension(
        "source_variety", "single authoritative source versus many sources"
    ),
    QuestionnaireDimension(
        "primary_sources", "interest in documents and direct evidence"
    ),
    QuestionnaireDimension(
        "tone_balance", "neutral, analytical, positive, or critical tone"
    ),
    QuestionnaireDimension(
        "viewpoint_diversity", "range of perspectives and disagreement"
    ),
    QuestionnaireDimension(
        "opinion_content", "reported news versus columns and commentary"
    ),
    QuestionnaireDimension("investigative_reporting", "interest in investigations"),
    QuestionnaireDimension(
        "solutions_journalism", "interest in responses and solutions"
    ),
    QuestionnaireDimension("human_interest", "people-centered narratives"),
    QuestionnaireDimension("data_density", "statistics and data versus narrative"),
    QuestionnaireDimension(
        "format_preference", "text, audio, video, or visual formats"
    ),
    QuestionnaireDimension(
        "explainer_style", "background explainers versus event updates"
    ),
    QuestionnaireDimension("practical_impact", "direct effect on daily decisions"),
    QuestionnaireDimension(
        "impact_timeframe", "immediate versus long-term consequences"
    ),
    QuestionnaireDimension("policy_detail", "detail about laws and public policy"),
    QuestionnaireDimension(
        "event_type", "planned events versus unexpected developments"
    ),
    QuestionnaireDimension(
        "novelty_preference", "new topics versus familiar interests"
    ),
    QuestionnaireDimension("controversy_tolerance", "comfort with divisive subjects"),
    QuestionnaireDimension(
        "uncertainty_tolerance", "early uncertain reports versus confirmed facts"
    ),
    QuestionnaireDimension(
        "fact_density", "fact-heavy coverage versus accessible summaries"
    ),
    QuestionnaireDimension(
        "story_structure", "chronological, analytical, or narrative structure"
    ),
    QuestionnaireDimension("historical_context", "amount of historical background"),
    QuestionnaireDimension("expert_commentary", "importance of expert interpretation"),
    QuestionnaireDimension("actionability", "information that enables concrete action"),
    QuestionnaireDimension(
        "topic_law", "interest in courts, legal cases, and judicial decisions"
    ),
    QuestionnaireDimension(
        "topic_entertainment", "interest in film, television, music, and celebrity"
    ),
    QuestionnaireDimension(
        "topic_religion", "interest in religion, faith, and spiritual affairs"
    ),
    QuestionnaireDimension(
        "topic_defense", "interest in military affairs and national security"
    ),
    QuestionnaireDimension(
        "topic_personal_finance",
        "interest in personal finance, investing, and wealth management",
    ),
    QuestionnaireDimension(
        "geopolitics", "interest in international relations and foreign policy"
    ),
    QuestionnaireDimension(
        "source_transparency",
        "importance of bylines, sourcing, corrections, and editorial independence",
    ),
    QuestionnaireDimension(
        "reading_level", "preferred vocabulary complexity and reading level"
    ),
    QuestionnaireDimension(
        "visual_richness",
        "preference for data visualizations, infographics, and charts",
    ),
    QuestionnaireDimension(
        "cross_discipline",
        "interest in articles bridging multiple fields or disciplines",
    ),
)
DIMENSION_BY_KEY = {dimension.key: dimension for dimension in DIMENSIONS}

LEGACY_ALIASES = {
    "depth": "reporting_depth",
    "news_topic_focus": "novelty_preference",
    "news_topic_science_subtopic": "topic_science",
    "news_topic_general_breadth": "novelty_preference",
    "geographic_scope": "geography_scope",
    "news_geography_priority": "geography_scope",
    "news_tone": "tone_balance",
    "news_tone_balance": "tone_balance",
    "tone": "tone_balance",
    "story_length": "article_length",
    "news_length_detail": "article_length",
    "update_frequency": "update_frequency",
    "news_update_urgency": "breaking_news",
    "source_style": "source_authority",
    "news_source_style_authority": "source_authority",
    "depth_level": "reporting_depth",
    "news_story_structure": "story_structure",
    "format_preference": "format_preference",
    "format": "format_preference",
    "news_format_mix": "format_preference",
    "event_type": "event_type",
    "impact_level": "practical_impact",
    "news_impact_timeframe": "impact_timeframe",
    "perspective": "viewpoint_diversity",
    "timeliness": "breaking_news",
    "topic_area": "novelty_preference",
}


def canonical_dimension_key(value: str) -> str:
    key = value.strip().lower()
    if key in DIMENSION_BY_KEY:
        return key
    return LEGACY_ALIASES.get(key, key)


def consolidated_dimension_context(
    dimension_context: tuple[QuestionDimensionContext, ...],
) -> tuple[QuestionDimensionContext, ...]:
    consolidated: dict[str, QuestionDimensionContext] = {}
    for item in dimension_context:
        key = canonical_dimension_key(item.dimension_key)
        previous = consolidated.get(key)
        consolidated[key] = QuestionDimensionContext(
            dimension_key=key,
            exposure_count=item.exposure_count
            + (previous.exposure_count if previous else 0),
            last_exposed_at=max(
                item.last_exposed_at,
                previous.last_exposed_at if previous else item.last_exposed_at,
            ),
        )
    return tuple(
        sorted(
            consolidated.values(),
            key=lambda item: (
                item.exposure_count,
                item.last_exposed_at,
                item.dimension_key,
            ),
        )
    )


def available_dimensions(
    prior_answers: tuple[PriorAnswer, ...],
    dimension_context: tuple[QuestionDimensionContext, ...] = (),
    *,
    minimum: int = 10,
) -> tuple[QuestionnaireDimension, ...]:
    exposures = {
        item.dimension_key: item
        for item in consolidated_dimension_context(dimension_context)
    }
    for answer in reversed(prior_answers):
        key = canonical_dimension_key(answer.dimension_key)
        if key not in exposures:
            exposures[key] = QuestionDimensionContext(
                dimension_key=key,
                exposure_count=1,
                last_exposed_at=datetime.min.replace(tzinfo=UTC),
            )

    unseen = [dimension for dimension in DIMENSIONS if dimension.key not in exposures]
    if len(unseen) >= minimum:
        return tuple(unseen)

    previously_seen = sorted(
        (dimension for dimension in DIMENSIONS if dimension.key in exposures),
        key=lambda dimension: (
            exposures[dimension.key].exposure_count,
            exposures[dimension.key].last_exposed_at,
            dimension.key,
        ),
    )
    return tuple((unseen + previously_seen)[: max(minimum, len(unseen))])
