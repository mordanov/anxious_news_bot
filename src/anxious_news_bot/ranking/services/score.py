from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Final

from anxious_news_bot.ranking.domain import (
    DECIMAL_CONTEXT,
    ArticleEvaluation,
    ContributionSnapshot,
    FactorSnapshot,
    PersonalState,
    RankingArticleSnapshot,
    RankingConfiguration,
    RankingPreference,
    RankingRecord,
    SelectionOutcome,
    SelectionReason,
    quantize_score,
)
from anxious_news_bot.ranking.services.configuration import freshness_window
from anxious_news_bot.ranking.services.eligibility import determine_eligibility

ZERO: Final = Decimal("0")
HALF: Final = Decimal("0.5")


def _require_decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    return value


def contribution(weight: Decimal, relevance: Decimal) -> Decimal:
    weight_decimal = _require_decimal(weight, "weight")
    relevance_decimal = _require_decimal(relevance, "relevance")
    with localcontext(DECIMAL_CONTEXT):
        return quantize_score(weight_decimal * relevance_decimal)


def _quantize_factor(value: Decimal) -> Decimal:
    return quantize_score(_require_decimal(value, "factor"))


def stable_ranking_key(record: RankingRecord) -> tuple[object, ...]:
    published_order = (
        -record.published_at.timestamp() if record.published_at is not None else 0
    )
    return (
        -record.final_score,
        -record.personal_signed,
        -record.factors.importance,
        record.published_at is None,
        published_order,
        str(record.article_id),
    )


class DeterministicRankingScorer:
    def score(
        self,
        article_snapshot: RankingArticleSnapshot,
        configuration: RankingConfiguration,
        preferences: tuple[RankingPreference, ...],
        evaluation: ArticleEvaluation | None,
        *,
        ranking_at: datetime,
    ) -> RankingRecord:
        active_preferences = tuple(
            preference for preference in preferences if preference.active
        )
        active_nonzero_preferences = tuple(
            preference for preference in active_preferences if preference.weight != ZERO
        )
        evaluation_map = self._complete_evaluation_map(
            evaluation,
            article_snapshot=article_snapshot,
        )
        freshness = freshness_window(
            configuration,
            article_snapshot.published_at,
            ranking_at=ranking_at,
        )
        importance_raw = article_snapshot.importance_score or ZERO
        novelty_raw = article_snapshot.novelty_score or ZERO
        quality_raw = article_snapshot.source_quality_score or ZERO

        if not active_preferences:
            personal_state = PersonalState.NO_ACTIVE_PARAMETERS
            numerator_raw = ZERO
            denominator_raw = ZERO
            personal_signed_raw = ZERO
            personal_factor_raw = HALF
            contributions: tuple[ContributionSnapshot, ...] = ()
        elif not active_nonzero_preferences:
            personal_state = PersonalState.ALL_WEIGHTS_ZERO
            numerator_raw = ZERO
            denominator_raw = ZERO
            personal_signed_raw = ZERO
            personal_factor_raw = HALF
            contributions = ()
        else:
            active_ids = {preference.id for preference in active_preferences}
            required_ids = {preference.id for preference in active_nonzero_preferences}
            found_ids = set(evaluation_map)
            coverage = required_ids.issubset(found_ids) and found_ids.issubset(
                active_ids
            )
            if coverage:
                personal_state = PersonalState.COMPLETE
                contributions = tuple(
                    ContributionSnapshot(
                        parameter_id=preference.id,
                        parameter_name=preference.name,
                        origin=preference.origin,
                        effective_authority=preference.effective_authority,
                        weight=preference.weight,
                        relevance=evaluation_map[preference.id],
                        contribution=contribution(
                            preference.weight,
                            evaluation_map[preference.id],
                        ),
                    )
                    for preference in active_nonzero_preferences
                )
                with localcontext(DECIMAL_CONTEXT):
                    numerator_raw = sum(
                        (item.contribution for item in contributions),
                        start=ZERO,
                    )
                    denominator_raw = sum(
                        (
                            abs(preference.weight)
                            for preference in active_nonzero_preferences
                        ),
                        start=ZERO,
                    )
                    personal_signed_raw = numerator_raw / denominator_raw
                    personal_factor_raw = (
                        personal_signed_raw + Decimal("1")
                    ) / Decimal("2")
            else:
                personal_state = PersonalState.COMPLETE
                contributions = ()
                with localcontext(DECIMAL_CONTEXT):
                    numerator_raw = ZERO
                    denominator_raw = sum(
                        (
                            abs(preference.weight)
                            for preference in active_nonzero_preferences
                        ),
                        start=ZERO,
                    )
                    personal_signed_raw = ZERO
                    personal_factor_raw = HALF

        decision = determine_eligibility(
            article_snapshot,
            configuration,
            active_preferences,
            evaluation,
            ranking_at=ranking_at,
        )
        factors = FactorSnapshot(
            importance=_quantize_factor(importance_raw),
            freshness=_quantize_factor(freshness.factor),
            quality=_quantize_factor(quality_raw),
            novelty=_quantize_factor(novelty_raw),
        )
        personal_numerator = quantize_score(numerator_raw)
        personal_denominator = quantize_score(denominator_raw)
        personal_signed = quantize_score(personal_signed_raw)
        personal_factor = quantize_score(personal_factor_raw)
        with localcontext(DECIMAL_CONTEXT):
            unrounded_score = (
                configuration.personal_coefficient * personal_factor
                + configuration.importance_coefficient * factors.importance
                + configuration.freshness_coefficient * factors.freshness
                + configuration.quality_coefficient * factors.quality
                + configuration.novelty_coefficient * factors.novelty
            )
        selection = SelectionOutcome(
            selected=False,
            reason=SelectionReason.NOT_EVALUATED
            if decision.eligible
            else SelectionReason.INELIGIBLE,
            explicit_protected=decision.explicit_protected,
        )
        return RankingRecord(
            article_id=article_snapshot.article_id,
            article_analysis_id=article_snapshot.article_analysis_id,
            source_id=article_snapshot.source_id,
            event_group_id=article_snapshot.event_group_id,
            topic_key=article_snapshot.topic_key,
            published_at=article_snapshot.published_at,
            evaluation_run_id=evaluation.run_id if evaluation is not None else None,
            personal_state=personal_state,
            personal_numerator=personal_numerator,
            personal_denominator=personal_denominator,
            personal_signed=personal_signed,
            personal_factor=personal_factor,
            factors=factors,
            unrounded_score=unrounded_score,
            final_score=quantize_score(unrounded_score),
            eligible=decision.eligible,
            eligibility_reason=decision.reason,
            explicit_protected=decision.explicit_protected,
            explicit_veto=decision.explicit_veto,
            selection=selection,
            contributions=contributions,
        )

    @staticmethod
    def _complete_evaluation_map(
        evaluation: ArticleEvaluation | None,
        *,
        article_snapshot: RankingArticleSnapshot,
    ) -> dict[object, Decimal]:
        if evaluation is None or evaluation.status.value != "complete":
            return {}
        if (
            evaluation.identity.article_id != article_snapshot.article_id
            or evaluation.identity.article_analysis_id
            != article_snapshot.article_analysis_id
        ):
            return {}
        return {
            relevance.parameter_id: relevance.relevance
            for relevance in evaluation.relevances
        }


def order_records(records: tuple[RankingRecord, ...]) -> tuple[RankingRecord, ...]:
    return tuple(sorted(records, key=stable_ranking_key))


def with_initial_positions(
    records: tuple[RankingRecord, ...],
) -> tuple[RankingRecord, ...]:
    return tuple(
        replace(record, initial_position=index)
        for index, record in enumerate(records, start=1)
    )


__all__ = [
    "DeterministicRankingScorer",
    "contribution",
    "order_records",
    "stable_ranking_key",
    "with_initial_positions",
]
