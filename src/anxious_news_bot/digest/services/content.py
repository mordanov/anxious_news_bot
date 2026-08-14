"""Deterministic ranked-item grounding and content validation."""

from __future__ import annotations

import re
from collections.abc import Sequence

from anxious_news_bot.digest.domain import (
    StructuredDigestItem,
    content_hash,
)

CONTENT_MAX_INPUT_CHARS = 2000
_SPACE = re.compile(r"\s+")


def _normalize(value: object) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()


def prepare_composer_inputs(
    ranked_items: Sequence[dict],
    *,
    max_input_chars: int = CONTENT_MAX_INPUT_CHARS,
) -> list[dict]:
    """Prepare bounded grounding inputs for the composer."""
    if max_input_chars < 1:
        raise ValueError("max_input_chars must be positive")
    if len(ranked_items) > 20:
        raise ValueError("at most 20 ranked items may be composed")
    positions = tuple(item.get("position") for item in ranked_items)
    if positions != tuple(range(1, len(ranked_items) + 1)):
        raise ValueError("ranked item positions must be contiguous from 1")
    inputs = []
    for item in ranked_items:
        title = _normalize(item.get("title"))[:500]
        summary = _normalize(item.get("summary"))
        normalized_text = _normalize(item.get("normalized_text"))

        # Use summary first, fall back to bounded normalized text
        grounding = summary if summary else normalized_text[:max_input_chars]
        if len(grounding) > max_input_chars:
            grounding = grounding[:max_input_chars]

        inputs.append(
            {
                "index": item["position"],
                "title": title,
                "grounding": grounding,
            }
        )
    return inputs


def merge_composed_content(
    composed_items: tuple[dict, ...],
    ranked_items: Sequence[dict],
) -> tuple[StructuredDigestItem, ...]:
    """Merge validated model output with deterministic application data."""
    expected_indexes = tuple(range(1, len(ranked_items) + 1))
    ranked_positions = tuple(item.get("position") for item in ranked_items)
    composed_indexes = tuple(item.get("index") for item in composed_items)
    if (
        ranked_positions != expected_indexes
        or len(composed_indexes) != len(expected_indexes)
        or len(set(composed_indexes)) != len(composed_indexes)
        or set(composed_indexes) != set(expected_indexes)
    ):
        raise ValueError(
            "composed output must cover exactly each ranked item index once"
        )
    items_by_index = {item["index"]: item for item in composed_items}
    result: list[StructuredDigestItem] = []

    for ranked in ranked_items:
        position = ranked["position"]
        composed = items_by_index.get(position)
        if composed is None:
            raise ValueError(f"missing composed item for position {position}")

        item_data = {
            "position": position,
            "article_id": str(ranked["article_id"]),
            "title": composed["title"],
            "summary": composed["summary"],
            "source_name": ranked["source_name"],
            "published_at": ranked["published_at"].isoformat(),
            "canonical_url": ranked["canonical_url"],
        }
        item_hash = content_hash(item_data)

        result.append(
            StructuredDigestItem(
                position=position,
                article_id=ranked["article_id"],
                article_analysis_id=ranked["article_analysis_id"],
                event_group_id=ranked.get("event_group_id"),
                ranking_run_id=ranked["ranking_run_id"],
                title=composed["title"],
                summary=composed["summary"],
                source_name=ranked["source_name"],
                published_at=ranked["published_at"],
                canonical_url=ranked["canonical_url"],
                score=ranked["score"],
                content_hash=item_hash,
            )
        )

    # Validate contiguous positions
    positions = sorted(item.position for item in result)
    expected = list(range(1, len(result) + 1))
    if positions != expected:
        raise ValueError("items must have contiguous positions from 1")

    return tuple(result)
