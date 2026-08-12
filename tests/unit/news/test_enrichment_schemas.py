from decimal import Decimal

import pytest
from pydantic import ValidationError

from anxious_news_bot.news.schemas import (
    SECTION_ADAPTERS,
    EnrichmentResultSchema,
)


def valid_result() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "status": "complete",
        "sections": {
            "topics": ["economy"],
            "countries": ["ES"],
            "cities": ["Madrid"],
            "locations": ["Community of Madrid"],
            "people": ["Ada Lovelace"],
            "organizations": ["Example Org"],
            "event_type": "policy",
            "importance": Decimal("0.75"),
            "novelty": Decimal("0.5"),
            "source_quality": Decimal(1),
            "semantic_metadata": {
                "representation_id": "article-embedding",
                "model": "example-v1",
            },
        },
        "errors": [],
    }


def test_complete_contract_is_strict_and_bounded() -> None:
    result = EnrichmentResultSchema.model_validate(valid_result())

    assert result.schema_version == "1.0"
    assert result.sections.importance == Decimal("0.75")

    invalid = valid_result()
    invalid["sections"] = {**invalid["sections"], "importance": "0.75"}
    with pytest.raises(ValidationError):
        EnrichmentResultSchema.model_validate(invalid)

    invalid = valid_result()
    invalid["sections"] = {**invalid["sections"], "topics": ["x"] * 21}
    with pytest.raises(ValidationError):
        EnrichmentResultSchema.model_validate(invalid)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("importance", Decimal("-0.01")),
        ("novelty", Decimal("1.01")),
        ("source_quality", 2),
        ("countries", ["Spain"]),
        ("locations", ["x"] * 31),
        ("event_type", ""),
    ],
)
def test_invalid_scores_and_section_values_are_rejected(
    path: str, value: object
) -> None:
    invalid = valid_result()
    invalid["sections"] = {**invalid["sections"], path: value}

    with pytest.raises(ValidationError):
        EnrichmentResultSchema.model_validate(invalid)


@pytest.mark.parametrize(
    "payload",
    [
        {**valid_result(), "user_id": 123},
        {
            **valid_result(),
            "sections": {**valid_result()["sections"], "personal_interest": 0.9},
        },
        {
            **valid_result(),
            "errors": [{"section": "topics", "code": "bad", "detail": "raw"}],
        },
    ],
)
def test_unknown_fields_including_user_data_are_rejected(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        EnrichmentResultSchema.model_validate(payload)


def test_sections_can_be_validated_independently() -> None:
    topics = SECTION_ADAPTERS["topics"].validate_python(["world"])
    locations = SECTION_ADAPTERS["locations"].validate_python(["Madrid region"])

    assert topics == ("world",)
    assert locations == ("Madrid region",)
    with pytest.raises(ValidationError):
        SECTION_ADAPTERS["importance"].validate_python(Decimal("1.1"))
