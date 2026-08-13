from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from anxious_news_bot.ranking.domain import EligibilityReason, RankingConfiguration
from anxious_news_bot.ranking.services.configuration import (
    canonical_configuration_hash,
    freshness_window,
)
from tests.fixtures.ranking import ranking_configuration

RANKING_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def test_configuration_requires_convex_coefficients_and_personal_floor() -> None:
    with pytest.raises(ValueError, match="sum exactly to 1.00000"):
        RankingConfiguration(
            version="1.0",
            tie_policy_version="1.0",
            retention_policy_version="1.0",
            personal_coefficient=Decimal("0.45000"),
            importance_coefficient=Decimal("0.20000"),
            freshness_coefficient=Decimal("0.15000"),
            quality_coefficient=Decimal("0.10000"),
            novelty_coefficient=Decimal("0.09000"),
            freshness_horizon_seconds=259200,
            future_tolerance_seconds=300,
            minimum_source_quality=Decimal("0.35000"),
            maximum_candidate_count=500,
            event_cap=2,
            topic_cap=3,
            source_cap=3,
            explicit_weight_threshold=Decimal("0.75"),
            explicit_relevance_threshold=Decimal("0.6000"),
            explanation_contribution_limit=3,
        )

    with pytest.raises(ValueError, match="at least 0.40000"):
        RankingConfiguration(
            version="1.0",
            tie_policy_version="1.0",
            retention_policy_version="1.0",
            personal_coefficient=Decimal("0.39000"),
            importance_coefficient=Decimal("0.26000"),
            freshness_coefficient=Decimal("0.15000"),
            quality_coefficient=Decimal("0.10000"),
            novelty_coefficient=Decimal("0.10000"),
            freshness_horizon_seconds=259200,
            future_tolerance_seconds=300,
            minimum_source_quality=Decimal("0.35000"),
            maximum_candidate_count=500,
            event_cap=2,
            topic_cap=3,
            source_cap=3,
            explicit_weight_threshold=Decimal("0.75"),
            explicit_relevance_threshold=Decimal("0.6000"),
            explanation_contribution_limit=3,
        )


def test_freshness_is_linear_at_boundaries_and_respects_future_tolerance() -> None:
    configuration = ranking_configuration()

    assert freshness_window(
        configuration,
        RANKING_AT,
        ranking_at=RANKING_AT,
    ).factor == Decimal("1.00000000")

    assert freshness_window(
        configuration,
        RANKING_AT - timedelta(hours=36),
        ranking_at=RANKING_AT,
    ).factor == Decimal("0.50000000")

    at_horizon = freshness_window(
        configuration,
        RANKING_AT - timedelta(seconds=configuration.freshness_horizon_seconds),
        ranking_at=RANKING_AT,
    )
    assert at_horizon.factor == Decimal("0.00000000")
    assert at_horizon.reason is None

    obsolete = freshness_window(
        configuration,
        RANKING_AT - timedelta(seconds=configuration.freshness_horizon_seconds + 1),
        ranking_at=RANKING_AT,
    )
    assert obsolete.factor == Decimal("0.00000000")
    assert obsolete.reason is EligibilityReason.OBSOLETE_PUBLICATION

    tolerated_future = freshness_window(
        configuration,
        RANKING_AT + timedelta(seconds=configuration.future_tolerance_seconds),
        ranking_at=RANKING_AT,
    )
    assert tolerated_future.factor == Decimal("1.00000000")
    assert tolerated_future.reason is None

    future = freshness_window(
        configuration,
        RANKING_AT + timedelta(seconds=configuration.future_tolerance_seconds + 1),
        ranking_at=RANKING_AT,
    )
    assert future.factor == Decimal("1.00000000")
    assert future.reason is EligibilityReason.FUTURE_PUBLICATION


def test_configuration_hash_is_stable_versioned_and_uses_supplied_ranking_time() -> (
    None
):
    configuration = ranking_configuration()
    same_hash = canonical_configuration_hash(configuration)

    assert same_hash == canonical_configuration_hash(configuration)
    assert len(same_hash) == 64

    changed = RankingConfiguration(
        version="1.1",
        tie_policy_version=configuration.tie_policy_version,
        retention_policy_version=configuration.retention_policy_version,
        personal_coefficient=configuration.personal_coefficient,
        importance_coefficient=configuration.importance_coefficient,
        freshness_coefficient=configuration.freshness_coefficient,
        quality_coefficient=configuration.quality_coefficient,
        novelty_coefficient=configuration.novelty_coefficient,
        freshness_horizon_seconds=configuration.freshness_horizon_seconds,
        future_tolerance_seconds=configuration.future_tolerance_seconds,
        minimum_source_quality=configuration.minimum_source_quality,
        maximum_candidate_count=configuration.maximum_candidate_count,
        event_cap=configuration.event_cap,
        topic_cap=configuration.topic_cap,
        source_cap=configuration.source_cap,
        explicit_weight_threshold=configuration.explicit_weight_threshold,
        explicit_relevance_threshold=configuration.explicit_relevance_threshold,
        explanation_contribution_limit=configuration.explanation_contribution_limit,
    )
    assert canonical_configuration_hash(changed) != same_hash

    earlier = freshness_window(
        configuration,
        RANKING_AT - timedelta(hours=12),
        ranking_at=RANKING_AT,
    ).factor
    later = freshness_window(
        configuration,
        RANKING_AT - timedelta(hours=12),
        ranking_at=RANKING_AT + timedelta(hours=12),
    ).factor
    assert earlier == Decimal("0.83333333")
    assert later == Decimal("0.66666667")
