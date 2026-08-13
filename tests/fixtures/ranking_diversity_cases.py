from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import UUID

from anxious_news_bot.ranking.domain import RankingConfiguration, RankingRecord
from tests.fixtures.ranking import ranking_configuration, ranking_record


def _uuid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012d}")


@dataclass(frozen=True, slots=True)
class ReviewedDiversityCase:
    slug: str
    configuration: RankingConfiguration
    requested_count: int
    records: tuple[RankingRecord, ...]
    expected_selected_ids: tuple[UUID, ...]
    expected_selected_cap_vector: tuple[int, int, int]
    expected_unsatisfied_limits: tuple[str, ...]
    sufficient_alternatives: bool
    protected_article_ids: tuple[UUID, ...] = ()


_BALANCED_CONFIGURATION = replace(
    ranking_configuration(),
    event_cap=1,
    topic_cap=2,
    source_cap=2,
)
_BALANCED_REPEATS = ReviewedDiversityCase(
    slug="balanced-repeats",
    configuration=_BALANCED_CONFIGURATION,
    requested_count=3,
    records=(
        ranking_record(
            article_id=_uuid(101),
            article_analysis_id=_uuid(1101),
            source_id=_uuid(2101),
            event_group_id=_uuid(3101),
            topic_key="local",
            final_score="0.95000000",
            unrounded_score="0.9500000000000000",
            initial_position=1,
        ),
        ranking_record(
            article_id=_uuid(102),
            article_analysis_id=_uuid(1102),
            source_id=_uuid(2102),
            event_group_id=_uuid(3101),
            topic_key="finance",
            final_score="0.94000000",
            unrounded_score="0.9400000000000000",
            initial_position=2,
        ),
        ranking_record(
            article_id=_uuid(103),
            article_analysis_id=_uuid(1103),
            source_id=_uuid(2103),
            event_group_id=_uuid(3103),
            topic_key="local",
            final_score="0.93000000",
            unrounded_score="0.9300000000000000",
            initial_position=3,
        ),
        ranking_record(
            article_id=_uuid(104),
            article_analysis_id=_uuid(1104),
            source_id=_uuid(2101),
            event_group_id=_uuid(3104),
            topic_key="science",
            final_score="0.92000000",
            unrounded_score="0.9200000000000000",
            initial_position=4,
        ),
    ),
    expected_selected_ids=(_uuid(101), _uuid(103), _uuid(104)),
    expected_selected_cap_vector=(
        _BALANCED_CONFIGURATION.event_cap,
        _BALANCED_CONFIGURATION.topic_cap,
        _BALANCED_CONFIGURATION.source_cap,
    ),
    expected_unsatisfied_limits=(),
    sufficient_alternatives=True,
)

_RELAXED_CONFIGURATION = replace(
    ranking_configuration(),
    event_cap=1,
    topic_cap=1,
    source_cap=1,
)
_PROTECTED_SOURCE_RELAXATION = ReviewedDiversityCase(
    slug="protected-source-relaxation",
    configuration=_RELAXED_CONFIGURATION,
    requested_count=3,
    records=(
        ranking_record(
            article_id=_uuid(201),
            article_analysis_id=_uuid(1201),
            source_id=_uuid(2201),
            event_group_id=_uuid(3201),
            topic_key="local",
            final_score="0.95000000",
            unrounded_score="0.9500000000000000",
            initial_position=1,
        ),
        ranking_record(
            article_id=_uuid(202),
            article_analysis_id=_uuid(1202),
            source_id=_uuid(2202),
            event_group_id=_uuid(3201),
            topic_key="finance",
            final_score="0.94000000",
            unrounded_score="0.9400000000000000",
            initial_position=2,
        ),
        ranking_record(
            article_id=_uuid(203),
            article_analysis_id=_uuid(1203),
            source_id=_uuid(2203),
            event_group_id=_uuid(3203),
            topic_key="finance",
            final_score="0.93000000",
            unrounded_score="0.9300000000000000",
            initial_position=3,
        ),
        ranking_record(
            article_id=_uuid(204),
            article_analysis_id=_uuid(1204),
            source_id=_uuid(2201),
            event_group_id=_uuid(3204),
            topic_key="science",
            final_score="0.92000000",
            unrounded_score="0.9200000000000000",
            explicit_protected=True,
            initial_position=4,
        ),
    ),
    expected_selected_ids=(_uuid(204), _uuid(201), _uuid(203)),
    expected_selected_cap_vector=(
        _RELAXED_CONFIGURATION.event_cap,
        _RELAXED_CONFIGURATION.topic_cap,
        _RELAXED_CONFIGURATION.maximum_candidate_count,
    ),
    expected_unsatisfied_limits=("source",),
    sufficient_alternatives=False,
    protected_article_ids=(_uuid(204),),
)

REVIEWED_DIVERSITY_CASES = (
    _BALANCED_REPEATS,
    _PROTECTED_SOURCE_RELAXATION,
)

__all__ = [
    "REVIEWED_DIVERSITY_CASES",
    "ReviewedDiversityCase",
]
