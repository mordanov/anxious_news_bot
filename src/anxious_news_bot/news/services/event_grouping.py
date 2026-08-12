from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from anxious_news_bot.news.domain import (
    DecisionOutcome,
    EventGroupingResult,
    NormalizedArticle,
)
from anxious_news_bot.news.services.deduplicate import text_similarity

_SCORE_QUANTUM = Decimal("0.00001")


def _overlap(left: tuple[str, ...], right: tuple[str, ...]) -> Decimal:
    left_values = {item.strip().casefold() for item in left if item.strip()}
    right_values = {item.strip().casefold() for item in right if item.strip()}
    union = left_values | right_values
    if not union:
        return Decimal("0.00000")
    return (Decimal(len(left_values & right_values)) / Decimal(len(union))).quantize(
        _SCORE_QUANTUM, rounding=ROUND_HALF_UP
    )


class DeterministicEventGrouper:
    def __init__(
        self,
        *,
        window_hours: int = 48,
        title_weight: Decimal = Decimal("0.50"),
        content_weight: Decimal = Decimal("0.30"),
        topic_weight: Decimal = Decimal("0.10"),
        geography_weight: Decimal = Decimal("0.10"),
        anchor_threshold: Decimal = Decimal("0.55"),
        assignment_threshold: Decimal = Decimal("0.62"),
        review_threshold: Decimal = Decimal("0.52"),
        algorithm_version: str = "event-v1",
    ) -> None:
        if window_hours < 1:
            raise ValueError("window_hours must be positive")
        weights = (title_weight, content_weight, topic_weight, geography_weight)
        if any(value < 0 or value > 1 for value in weights) or sum(weights) != 1:
            raise ValueError("event weights must be within zero and one and sum to one")
        thresholds = (anchor_threshold, assignment_threshold, review_threshold)
        if any(value < 0 or value > 1 for value in thresholds):
            raise ValueError("event thresholds must be between zero and one")
        if review_threshold >= assignment_threshold:
            raise ValueError("review threshold must be below assignment threshold")
        if not algorithm_version:
            raise ValueError("algorithm_version must not be empty")
        self._window = timedelta(hours=window_hours)
        self._weights = {
            "title": title_weight,
            "content": content_weight,
            "topic": topic_weight,
            "geography": geography_weight,
        }
        self._anchor_threshold = anchor_threshold
        self._assignment_threshold = assignment_threshold
        self._review_threshold = review_threshold
        self._algorithm_version = algorithm_version

    def group_event(
        self,
        article: NormalizedArticle,
        candidates: Sequence[NormalizedArticle],
    ) -> EventGroupingResult:
        excluded = {"same_source": 0, "language": 0, "outside_window": 0}
        comparisons: list[tuple[int, Decimal, int, NormalizedArticle, dict]] = []
        article_time = article.published_at or article.ingested_at
        article_basis = "published_at" if article.published_at else "ingested_at"

        for candidate in sorted(candidates, key=lambda item: item.id.int):
            if candidate.id == article.id or candidate.primary_source_id == article.primary_source_id:
                excluded["same_source"] += 1
                continue
            if candidate.language_code != article.language_code:
                excluded["language"] += 1
                continue
            candidate_time = candidate.published_at or candidate.ingested_at
            if abs(candidate_time - article_time) > self._window:
                excluded["outside_window"] += 1
                continue

            title_score = text_similarity(article.title, candidate.title)
            content_score = text_similarity(
                article.normalized_text, candidate.normalized_text
            )
            topic_score = _overlap(article.topic_metadata, candidate.topic_metadata)
            geography_score = _overlap(
                article.geographic_relevance, candidate.geographic_relevance
            )
            score = (
                self._weights["title"] * title_score
                + self._weights["content"] * content_score
                + self._weights["topic"] * topic_score
                + self._weights["geography"] * geography_score
            ).quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP)
            shared_metadata = topic_score > 0 or geography_score > 0
            anchor_passed = (
                shared_metadata or title_score >= self._anchor_threshold
            )
            if anchor_passed and score >= self._assignment_threshold:
                outcome = DecisionOutcome.SAME_EVENT
                priority = 2
            elif anchor_passed and score >= self._review_threshold:
                outcome = DecisionOutcome.REVIEW
                priority = 1
            else:
                outcome = DecisionOutcome.DISTINCT
                priority = 0
            evidence = {
                "matched_article_id": str(candidate.id),
                "algorithm_version": self._algorithm_version,
                "window_hours": int(self._window.total_seconds() // 3600),
                "time_basis": {
                    "article": article_basis,
                    "candidate": (
                        "published_at"
                        if candidate.published_at
                        else "ingested_at"
                    ),
                },
                "signals": {
                    "title_similarity": self._format(title_score),
                    "content_similarity": self._format(content_score),
                    "topic_overlap": self._format(topic_score),
                    "geography_overlap": self._format(geography_score),
                },
                "weights": {
                    key: self._format(value) for key, value in self._weights.items()
                },
                "thresholds": {
                    "anchor": self._format(self._anchor_threshold),
                    "assignment": self._format(self._assignment_threshold),
                    "review": self._format(self._review_threshold),
                },
                "anchor": {
                    "passed": anchor_passed,
                    "shared_topic_or_geography": shared_metadata,
                },
                "source_urls": [
                    item.canonical_url
                    for item in sorted((article, candidate), key=lambda item: item.id.int)
                ],
            }
            if (
                article.event_group_id is not None
                and candidate.event_group_id is not None
                and article.event_group_id != candidate.event_group_id
            ):
                evidence["reassignment"] = {
                    "from_event_group_id": str(article.event_group_id),
                    "to_event_group_id": str(candidate.event_group_id),
                }
            comparisons.append(
                (priority, score, -candidate.id.int, candidate, evidence)
            )

        if not comparisons:
            return EventGroupingResult(
                DecisionOutcome.DISTINCT,
                evidence={
                    "algorithm_version": self._algorithm_version,
                    "excluded": excluded,
                },
            )

        priority, score, _, selected, evidence = max(comparisons)
        del priority
        evidence["excluded"] = excluded
        outcome = (
            DecisionOutcome.SAME_EVENT
            if score >= self._assignment_threshold and evidence["anchor"]["passed"]
            else DecisionOutcome.REVIEW
            if score >= self._review_threshold and evidence["anchor"]["passed"]
            else DecisionOutcome.DISTINCT
        )
        return EventGroupingResult(
            outcome,
            event_group_id=(
                selected.event_group_id
                if outcome is DecisionOutcome.SAME_EVENT
                else None
            ),
            score=score,
            evidence=evidence,
        )

    @staticmethod
    def _format(value: Decimal) -> str:
        return str(value.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP))
