from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from anxious_news_bot.ranking.domain import ContributionSnapshot, RankingRecord
from anxious_news_bot.ranking.schemas import RankingExplanationSchema


def _decimal_text(value: Decimal, places: int) -> str:
    return f"{value:.{places}f}"


def top_contributions(
    contributions: tuple[ContributionSnapshot, ...],
    limit: int,
) -> tuple[ContributionSnapshot, ...]:
    ordered = sorted(
        contributions,
        key=lambda item: (-abs(item.contribution), item.parameter_id.int),
    )
    return tuple(ordered[:limit])


class DeterministicRankingExplainer:
    def explain(
        self,
        ranking_run_id: UUID,
        record: RankingRecord,
        *,
        configuration_version: str,
        contribution_limit: int,
    ) -> RankingExplanationSchema:
        return RankingExplanationSchema(
            schema_version="1.0",
            ranking_run_id=ranking_run_id,
            article_id=record.article_id,
            configuration_version=configuration_version,
            personal_signed=_decimal_text(record.personal_signed, 8),
            personal_factor=_decimal_text(record.personal_factor, 8),
            factors={
                "importance": _decimal_text(record.factors.importance, 8),
                "freshness": _decimal_text(record.factors.freshness, 8),
                "quality": _decimal_text(record.factors.quality, 8),
                "novelty": _decimal_text(record.factors.novelty, 8),
            },
            final_score=_decimal_text(record.final_score, 8),
            eligible=record.eligible,
            eligibility_reason=record.eligibility_reason.value,
            selection={
                "selected": record.selection.selected,
                "position": record.selection.position,
                "reason": record.selection.reason.value,
                "explicit_protected": record.selection.explicit_protected,
                "diversity_pass": record.selection.diversity_pass,
            },
            top_contributions=[
                {
                    "parameter_id": contribution.parameter_id,
                    "parameter_name": contribution.parameter_name,
                    "origin": contribution.origin,
                    "effective_authority": contribution.effective_authority,
                    "weight": _decimal_text(contribution.weight, 2),
                    "relevance": _decimal_text(contribution.relevance, 4),
                    "contribution": _decimal_text(contribution.contribution, 8),
                }
                for contribution in top_contributions(
                    record.contributions,
                    contribution_limit,
                )
            ],
        )


__all__ = [
    "DeterministicRankingExplainer",
    "top_contributions",
]
