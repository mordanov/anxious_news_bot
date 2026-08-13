from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext

from anxious_news_bot.config import Settings
from anxious_news_bot.ranking.domain import (
    DECIMAL_CONTEXT,
    EligibilityReason,
    RankingConfiguration,
    quantize_score,
)

ZERO = Decimal("0")
ONE = Decimal("1")


def _decimal_text(value: Decimal, places: int) -> str:
    return f"{value:.{places}f}"


def relaxation_vectors(
    configuration: RankingConfiguration,
) -> tuple[tuple[int, int, int], ...]:
    maximum = configuration.maximum_candidate_count
    return (
        (
            configuration.event_cap,
            configuration.topic_cap,
            configuration.source_cap,
        ),
        (
            configuration.event_cap,
            configuration.topic_cap,
            maximum,
        ),
        (
            configuration.event_cap,
            maximum,
            maximum,
        ),
        (
            maximum,
            maximum,
            maximum,
        ),
    )


def canonical_configuration_payload(
    configuration: RankingConfiguration,
) -> dict[str, object]:
    return {
        "version": configuration.version,
        "tie_policy_version": configuration.tie_policy_version,
        "retention_policy_version": configuration.retention_policy_version,
        "coefficients": {
            "personal": _decimal_text(configuration.personal_coefficient, 5),
            "importance": _decimal_text(configuration.importance_coefficient, 5),
            "freshness": _decimal_text(configuration.freshness_coefficient, 5),
            "quality": _decimal_text(configuration.quality_coefficient, 5),
            "novelty": _decimal_text(configuration.novelty_coefficient, 5),
        },
        "freshness_horizon_seconds": configuration.freshness_horizon_seconds,
        "future_tolerance_seconds": configuration.future_tolerance_seconds,
        "minimum_source_quality": _decimal_text(
            configuration.minimum_source_quality,
            5,
        ),
        "maximum_candidate_count": configuration.maximum_candidate_count,
        "event_cap": configuration.event_cap,
        "topic_cap": configuration.topic_cap,
        "source_cap": configuration.source_cap,
        "explicit_weight_threshold": _decimal_text(
            configuration.explicit_weight_threshold,
            2,
        ),
        "explicit_relevance_threshold": _decimal_text(
            configuration.explicit_relevance_threshold,
            4,
        ),
        "explanation_contribution_limit": configuration.explanation_contribution_limit,
        "relaxation_vectors": relaxation_vectors(configuration),
    }


def canonical_configuration_hash(configuration: RankingConfiguration) -> str:
    payload = json.dumps(
        canonical_configuration_payload(configuration),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class FreshnessWindow:
    factor: Decimal
    reason: EligibilityReason | None = None


def freshness_window(
    configuration: RankingConfiguration,
    published_at: datetime | None,
    *,
    ranking_at: datetime,
) -> FreshnessWindow:
    if published_at is None or published_at.tzinfo is None:
        return FreshnessWindow(
            factor=Decimal("0.00000000"),
            reason=EligibilityReason.INVALID_PUBLISHED_AT,
        )
    with localcontext(DECIMAL_CONTEXT):
        delta_seconds = Decimal(str((ranking_at - published_at).total_seconds()))
        future_seconds = -delta_seconds if delta_seconds < ZERO else ZERO
        if future_seconds > configuration.future_tolerance_seconds:
            return FreshnessWindow(
                factor=Decimal("1.00000000"),
                reason=EligibilityReason.FUTURE_PUBLICATION,
            )
        age_seconds = max(delta_seconds, ZERO)
        factor = max(
            ZERO,
            ONE - (age_seconds / Decimal(configuration.freshness_horizon_seconds)),
        )
    reason = (
        EligibilityReason.OBSOLETE_PUBLICATION
        if age_seconds > configuration.freshness_horizon_seconds
        else None
    )
    return FreshnessWindow(
        factor=quantize_score(factor),
        reason=reason,
    )


class ValidatedRankingConfigurationProvider:
    def __init__(self, configuration: RankingConfiguration) -> None:
        self._configuration = configuration

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
    ) -> ValidatedRankingConfigurationProvider:
        return cls(
            RankingConfiguration(
                version=settings.ranking_configuration_version,
                tie_policy_version=settings.ranking_tie_policy_version,
                retention_policy_version=settings.ranking_retention_policy_version,
                personal_coefficient=settings.ranking_personal_coefficient,
                importance_coefficient=settings.ranking_importance_coefficient,
                freshness_coefficient=settings.ranking_freshness_coefficient,
                quality_coefficient=settings.ranking_quality_coefficient,
                novelty_coefficient=settings.ranking_novelty_coefficient,
                freshness_horizon_seconds=settings.ranking_freshness_horizon_seconds,
                future_tolerance_seconds=settings.ranking_future_tolerance_seconds,
                minimum_source_quality=settings.ranking_minimum_source_quality,
                maximum_candidate_count=settings.ranking_maximum_candidates,
                event_cap=settings.ranking_event_cap,
                topic_cap=settings.ranking_topic_cap,
                source_cap=settings.ranking_source_cap,
                explicit_weight_threshold=settings.ranking_explicit_weight_threshold,
                explicit_relevance_threshold=(
                    settings.ranking_explicit_relevance_threshold
                ),
                explanation_contribution_limit=(
                    settings.ranking_explanation_contribution_limit
                ),
            )
        )

    def current(self) -> RankingConfiguration:
        return self._configuration


__all__ = [
    "FreshnessWindow",
    "ValidatedRankingConfigurationProvider",
    "canonical_configuration_hash",
    "canonical_configuration_payload",
    "freshness_window",
    "relaxation_vectors",
]
