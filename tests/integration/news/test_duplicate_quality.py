from __future__ import annotations

import json
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from uuid import UUID, uuid5

from anxious_news_bot.news.domain import (
    DecisionOutcome,
    NormalizedArticle,
    NormalizedArticleCandidate,
)
from anxious_news_bot.news.services.deduplicate import DeterministicArticleDeduplicator

FIXTURE = (
    Path(__file__).parents[2]
    / "fixtures"
    / "duplicates"
    / "multilingual_labeled_groups.json"
)
NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)
NAMESPACE = UUID("596adf11-f422-4d41-b7d6-8a309c22627c")


def _candidate(record: dict[str, str]) -> NormalizedArticleCandidate:
    return NormalizedArticleCandidate(
        source_id=uuid5(NAMESPACE, f"source:{record['id']}"),
        title=record["title"],
        summary=None,
        canonical_url=f"https://candidate.example/{record['id']}",
        original_url=f"https://candidate.example/{record['id']}",
        published_at=NOW,
        ingested_at=NOW,
        language_code=record["language"],
        normalized_text=record["content"],
    )


def _article(record: dict[str, str]) -> NormalizedArticle:
    return NormalizedArticle(
        id=uuid5(NAMESPACE, f"article:{record['id']}"),
        title=record["title"],
        summary=None,
        canonical_url=f"https://existing.example/{record['id']}",
        canonicalization_version="1.0",
        primary_source_id=uuid5(NAMESPACE, f"source:{record['id']}"),
        published_at=NOW,
        ingested_at=NOW,
        language_code=record["language"],
        normalized_text=record["content"],
        created_in_cycle_id=uuid5(NAMESPACE, "cycle"),
    )


def _records() -> list[dict[str, str]]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    records: list[dict[str, str]] = []
    for language, groups in fixture["languages"].items():
        for group in groups:
            for index, variant in enumerate(fixture["variants"]):
                records.append(
                    {
                        "id": f"{group['label']}-{index}",
                        "label": group["label"],
                        "language": language,
                        "title": group["title"] + variant["title_suffix"],
                        "content": group["content"] + variant["content_suffix"],
                    }
                )
    return records


def acceptance_metrics() -> dict[str, float | int]:
    deduplicator = DeterministicArticleDeduplicator()
    duplicate_total = duplicate_consolidated = 0
    unrelated_total = unrelated_separated = false_merges = 0

    for left, right in combinations(_records(), 2):
        if left["language"] != right["language"]:
            continue
        expected_duplicate = left["label"] == right["label"]
        outcome = deduplicator.classify(_candidate(left), [_article(right)]).outcome
        if expected_duplicate:
            duplicate_total += 1
            duplicate_consolidated += outcome is DecisionOutcome.DUPLICATE
        else:
            unrelated_total += 1
            separated = outcome is not DecisionOutcome.DUPLICATE
            unrelated_separated += separated
            false_merges += not separated

    consolidation_rate = duplicate_consolidated / duplicate_total
    unrelated_separation_rate = unrelated_separated / unrelated_total
    duplicate_precision = duplicate_consolidated / (
        duplicate_consolidated + false_merges
    )

    return {
        "duplicate_pairs": duplicate_total,
        "unrelated_pairs": unrelated_total,
        "duplicate_consolidation_rate": consolidation_rate,
        "unrelated_separation_rate": unrelated_separation_rate,
        "duplicate_precision": duplicate_precision,
        "false_merges": false_merges,
    }


def test_multilingual_duplicate_acceptance_metrics() -> None:
    metrics = acceptance_metrics()

    assert metrics["duplicate_pairs"] >= 50
    assert metrics["unrelated_pairs"] >= 250
    assert metrics["duplicate_consolidation_rate"] >= 0.95
    assert metrics["unrelated_separation_rate"] >= 0.99
    assert metrics["duplicate_precision"] >= 0.99
