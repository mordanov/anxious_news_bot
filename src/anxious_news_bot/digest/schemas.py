"""Strict indexed content models for untrusted composer responses."""

from __future__ import annotations

from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
)

SCHEMA_VERSION = "1.0"
MAX_ITEMS = 20
TITLE_MAX_LENGTH = 500
SUMMARY_MAX_LENGTH = 1200


class ContentValidationError(ValueError):
    """The model response did not satisfy the trusted content boundary."""


class DigestContentItemSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    index: StrictInt = Field(ge=1, le=MAX_ITEMS)
    title: StrictStr = Field(min_length=1, max_length=TITLE_MAX_LENGTH)
    summary: StrictStr = Field(min_length=1, max_length=SUMMARY_MAX_LENGTH)

    @field_validator("title", "summary")
    @classmethod
    def require_visible_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must contain visible text")
        return value


class DigestContentResponseSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: StrictStr
    items: list[DigestContentItemSchema] = Field(
        min_length=1,
        max_length=MAX_ITEMS,
    )

    @field_validator("schema_version")
    @classmethod
    def require_schema_version(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(f"must be '{SCHEMA_VERSION}'")
        return value


def validate_composer_response(
    response: dict[str, Any], expected_count: int
) -> tuple[dict[str, Any], ...]:
    """Validate strict schema and exact one-to-one index coverage."""
    if isinstance(expected_count, bool) or not 1 <= expected_count <= MAX_ITEMS:
        raise ContentValidationError(f"expected_count must be 1..{MAX_ITEMS}")
    try:
        document = DigestContentResponseSchema.model_validate(response, strict=True)
    except ValidationError as exc:
        raise ContentValidationError(str(exc)) from exc
    if len(document.items) != expected_count:
        raise ContentValidationError(
            f"expected {expected_count} items, got {len(document.items)}"
        )
    indexes = tuple(item.index for item in document.items)
    expected_indexes = tuple(range(1, expected_count + 1))
    if len(set(indexes)) != len(indexes):
        raise ContentValidationError("duplicate content index")
    if set(indexes) != set(expected_indexes):
        raise ContentValidationError(f"indexes must be exactly 1..{expected_count}")
    ordered = sorted(document.items, key=lambda item: item.index)
    return tuple(item.model_dump() for item in ordered)
