from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from difflib import SequenceMatcher

from anxious_news_bot.news.domain import (
    DecisionOutcome,
    DeduplicationResult,
    NormalizedArticle,
    NormalizedArticleCandidate,
)

_SCORE_QUANTUM = Decimal("0.00001")
_SPACE = re.compile(r"\s+")


def normalize_comparison_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = "".join(
        character if character.isalnum() else " " for character in normalized
    )
    return _SPACE.sub(" ", normalized).strip()


def text_similarity(left: str, right: str) -> Decimal:
    left_value = normalize_comparison_text(left)
    right_value = normalize_comparison_text(right)
    if not left_value or not right_value:
        return Decimal("0.00000")
    return Decimal(
        str(SequenceMatcher(None, left_value, right_value, autojunk=False).ratio())
    ).quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP)


class DeterministicArticleDeduplicator:
    def __init__(
        self,
        *,
        title_threshold: Decimal = Decimal("0.85"),
        content_threshold: Decimal = Decimal("0.80"),
        review_threshold: Decimal = Decimal("0.72"),
        algorithm_version: str = "duplicate-v1",
    ) -> None:
        thresholds = (title_threshold, content_threshold, review_threshold)
        if any(value < 0 or value > 1 for value in thresholds):
            raise ValueError("duplicate thresholds must be between zero and one")
        if review_threshold > min(title_threshold, content_threshold):
            raise ValueError("review threshold must not exceed duplicate thresholds")
        if not algorithm_version:
            raise ValueError("algorithm_version must not be empty")
        self._title_threshold = title_threshold
        self._content_threshold = content_threshold
        self._review_threshold = review_threshold
        self._algorithm_version = algorithm_version

    def classify(
        self,
        candidate: NormalizedArticleCandidate,
        candidates: Sequence[NormalizedArticle],
    ) -> DeduplicationResult:
        ordered = sorted(candidates, key=lambda item: item.id.int)
        thresholds = {
            "title": self._format(self._title_threshold),
            "content": self._format(self._content_threshold),
            "review": self._format(self._review_threshold),
        }
        order = [str(item.id) for item in ordered]
        exact = next(
            (item for item in ordered if item.canonical_url == candidate.canonical_url),
            None,
        )
        if exact is not None:
            return DeduplicationResult(
                DecisionOutcome.DUPLICATE,
                matched_article_id=exact.id,
                thresholds=thresholds,
                algorithm_version=self._algorithm_version,
                evidence={
                    "reason": "exact_canonical_url",
                    "candidate_order": order,
                },
            )

        comparisons: list[
            tuple[
                int, Decimal, int, NormalizedArticle, Decimal, Decimal, DecisionOutcome
            ]
        ] = []
        for item in ordered:
            title_score = text_similarity(candidate.title, item.title)
            content_score = text_similarity(
                candidate.normalized_text, item.normalized_text
            )
            if (
                title_score >= self._title_threshold
                or content_score >= self._content_threshold
            ):
                outcome = DecisionOutcome.DUPLICATE
                priority = 2
            elif max(title_score, content_score) >= self._review_threshold:
                outcome = DecisionOutcome.REVIEW
                priority = 1
            else:
                outcome = DecisionOutcome.DISTINCT
                priority = 0
            comparisons.append(
                (
                    priority,
                    max(title_score, content_score),
                    -item.id.int,
                    item,
                    title_score,
                    content_score,
                    outcome,
                )
            )

        if not comparisons:
            return DeduplicationResult(
                DecisionOutcome.DISTINCT,
                thresholds=thresholds,
                algorithm_version=self._algorithm_version,
                evidence={"candidate_order": order, "comparisons": []},
            )

        _, _, _, selected, title_score, content_score, outcome = max(comparisons)
        evidence = {
            "candidate_order": order,
            "selected_candidate_id": str(selected.id),
            "comparisons": [
                {
                    "article_id": str(item.id),
                    "title_similarity": self._format(item_title),
                    "content_similarity": self._format(item_content),
                    "outcome": item_outcome.value,
                }
                for _, _, _, item, item_title, item_content, item_outcome in comparisons
            ],
        }
        return DeduplicationResult(
            outcome,
            matched_article_id=(
                selected.id if outcome is not DecisionOutcome.DISTINCT else None
            ),
            title_similarity=title_score,
            content_similarity=content_score,
            thresholds=thresholds,
            algorithm_version=self._algorithm_version,
            evidence=evidence,
        )

    @staticmethod
    def _format(value: Decimal) -> str:
        return str(value.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP))
