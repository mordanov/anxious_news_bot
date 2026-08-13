from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from anxious_news_bot.news.domain import DecisionOutcome
from anxious_news_bot.ranking.domain import (
    ArticleEvaluation,
    EligibilityReason,
    EvaluationStatus,
    RankingArticleSnapshot,
    RankingConfiguration,
    RankingPreference,
)
from anxious_news_bot.ranking.services.configuration import freshness_window
from anxious_news_bot.ranking.services.diversify import classify_explicit_signals

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    eligible: bool
    reason: EligibilityReason
    explicit_protected: bool
    explicit_veto: bool


def _active_nonzero_preferences(
    preferences: tuple[RankingPreference, ...],
) -> tuple[RankingPreference, ...]:
    return tuple(
        preference
        for preference in preferences
        if preference.active and preference.weight != ZERO
    )


def _complete_relevance_map(
    evaluation: ArticleEvaluation | None,
    *,
    article_snapshot: RankingArticleSnapshot,
) -> dict[object, Decimal]:
    if evaluation is None or evaluation.status is not EvaluationStatus.COMPLETE:
        return {}
    if (
        evaluation.identity.article_id != article_snapshot.article_id
        or evaluation.identity.article_analysis_id
        != article_snapshot.article_analysis_id
    ):
        return {}
    return {item.parameter_id: item.relevance for item in evaluation.relevances}


def determine_eligibility(
    article_snapshot: RankingArticleSnapshot,
    configuration: RankingConfiguration,
    preferences: tuple[RankingPreference, ...],
    evaluation: ArticleEvaluation | None,
    *,
    ranking_at: datetime,
) -> EligibilityDecision:
    active_preferences = tuple(
        preference for preference in preferences if preference.active
    )
    active_nonzero_preferences = _active_nonzero_preferences(preferences)
    classification = classify_explicit_signals(
        configuration,
        preferences,
        evaluation,
        article_snapshot=article_snapshot,
    )
    freshness = freshness_window(
        configuration,
        article_snapshot.published_at,
        ranking_at=ranking_at,
    )
    evaluation_map = _complete_relevance_map(
        evaluation,
        article_snapshot=article_snapshot,
    )
    active_ids = {preference.id for preference in active_preferences}
    required_ids = {preference.id for preference in active_nonzero_preferences}
    found_ids = set(evaluation_map)

    if getattr(article_snapshot, "article_analysis_id", None) is None:
        return EligibilityDecision(
            eligible=False,
            reason=EligibilityReason.MISSING_GENERIC_ANALYSIS,
            explicit_protected=False,
            explicit_veto=classification.veto,
        )
    if any(
        value is None
        for value in (
            article_snapshot.importance_score,
            article_snapshot.novelty_score,
            article_snapshot.source_quality_score,
        )
    ):
        return EligibilityDecision(
            eligible=False,
            reason=EligibilityReason.INCOMPLETE_GENERIC_ANALYSIS,
            explicit_protected=False,
            explicit_veto=classification.veto,
        )
    if active_nonzero_preferences and (
        not required_ids.issubset(found_ids) or not found_ids.issubset(active_ids)
    ):
        return EligibilityDecision(
            eligible=False,
            reason=EligibilityReason.INCOMPLETE_PERSONAL_EVALUATION,
            explicit_protected=False,
            explicit_veto=classification.veto,
        )
    if article_snapshot.source_quality_score < configuration.minimum_source_quality:
        return EligibilityDecision(
            eligible=False,
            reason=EligibilityReason.SOURCE_QUALITY_BELOW_MINIMUM,
            explicit_protected=False,
            explicit_veto=classification.veto,
        )
    if freshness.reason is EligibilityReason.INVALID_PUBLISHED_AT:
        return EligibilityDecision(
            eligible=False,
            reason=EligibilityReason.INVALID_PUBLISHED_AT,
            explicit_protected=False,
            explicit_veto=classification.veto,
        )
    if freshness.reason is EligibilityReason.FUTURE_PUBLICATION:
        return EligibilityDecision(
            eligible=False,
            reason=EligibilityReason.FUTURE_PUBLICATION,
            explicit_protected=False,
            explicit_veto=classification.veto,
        )
    if freshness.reason is EligibilityReason.OBSOLETE_PUBLICATION:
        return EligibilityDecision(
            eligible=False,
            reason=EligibilityReason.OBSOLETE_PUBLICATION,
            explicit_protected=False,
            explicit_veto=classification.veto,
        )
    if article_snapshot.duplicate_outcome is DecisionOutcome.DUPLICATE:
        return EligibilityDecision(
            eligible=False,
            reason=EligibilityReason.DISQUALIFYING_DUPLICATE,
            explicit_protected=False,
            explicit_veto=classification.veto,
        )
    if classification.veto:
        return EligibilityDecision(
            eligible=False,
            reason=EligibilityReason.EXPLICIT_VETO,
            explicit_protected=False,
            explicit_veto=True,
        )
    return EligibilityDecision(
        eligible=True,
        reason=EligibilityReason.ELIGIBLE,
        explicit_protected=classification.protected,
        explicit_veto=False,
    )


__all__ = [
    "EligibilityDecision",
    "determine_eligibility",
]
