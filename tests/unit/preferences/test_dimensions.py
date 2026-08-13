from datetime import UTC, datetime, timedelta

from anxious_news_bot.preferences.domain import PriorAnswer, QuestionDimensionContext
from anxious_news_bot.preferences.services.dimensions import (
    DIMENSIONS,
    available_dimensions,
    canonical_dimension_key,
    consolidated_dimension_context,
)


def test_normalizes_legacy_dimension_aliases() -> None:
    assert canonical_dimension_key("news_tone_balance") == "tone_balance"
    assert canonical_dimension_key("geographic_scope") == "geography_scope"
    assert canonical_dimension_key("news_format_mix") == "format_preference"
    assert canonical_dimension_key("tone") == "tone_balance"
    assert canonical_dimension_key("depth") == "reporting_depth"


def test_consolidates_legacy_exposure_aliases() -> None:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    context = (
        QuestionDimensionContext("news_tone", 2, now),
        QuestionDimensionContext("tone", 3, now + timedelta(minutes=1)),
    )

    result = consolidated_dimension_context(context)

    assert result == (
        QuestionDimensionContext(
            "tone_balance",
            5,
            now + timedelta(minutes=1),
        ),
    )


def test_excludes_semantically_covered_dimensions() -> None:
    prior = (
        PriorAnswer("Tone?", "Neutral", "news_tone"),
        PriorAnswer("Sources?", "Major outlets", "news_source_style_authority"),
    )
    keys = {dimension.key for dimension in available_dimensions(prior)}
    assert "tone_balance" not in keys
    assert "source_authority" not in keys
    assert len(keys) >= 10


def test_rotates_least_used_and_least_recent_dimensions_after_catalog_exhaustion() -> (
    None
):
    now = datetime(2026, 8, 13, tzinfo=UTC)
    context = tuple(
        QuestionDimensionContext(
            dimension_key=dimension.key,
            exposure_count=2 if index < 10 else 1,
            last_exposed_at=now + timedelta(minutes=index),
        )
        for index, dimension in enumerate(DIMENSIONS)
    )

    selected = available_dimensions((), context)

    assert len(selected) == 10
    assert all(
        next(
            item.exposure_count
            for item in context
            if item.dimension_key == dimension.key
        )
        == 1
        for dimension in selected
    )
