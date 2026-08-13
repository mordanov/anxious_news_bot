from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
)

StrictText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=False, min_length=1),
]
Topic = Annotated[StrictText, StringConstraints(max_length=100)]
Country = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[A-Z]{2}$"),
]
City = Annotated[StrictText, StringConstraints(max_length=120)]
Location = Annotated[StrictText, StringConstraints(max_length=120)]
Person = Annotated[StrictText, StringConstraints(max_length=160)]
Organization = Annotated[StrictText, StringConstraints(max_length=200)]
EventType = Annotated[StrictText, StringConstraints(max_length=100)]
Score = Annotated[
    float,
    Field(strict=True, ge=0, le=1, allow_inf_nan=False),
]


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError("items must be unique")
    return values


def _json_array(value: Any) -> Any:
    return tuple(value) if isinstance(value, list) else value


Topics = Annotated[
    tuple[Topic, ...],
    BeforeValidator(_json_array),
    Field(max_length=20),
    AfterValidator(_unique),
]
Countries = Annotated[
    tuple[Country, ...],
    BeforeValidator(_json_array),
    Field(max_length=20),
    AfterValidator(_unique),
]
Cities = Annotated[
    tuple[City, ...],
    BeforeValidator(_json_array),
    Field(max_length=30),
    AfterValidator(_unique),
]
Locations = Annotated[
    tuple[Location, ...],
    BeforeValidator(_json_array),
    Field(max_length=30),
    AfterValidator(_unique),
]
People = Annotated[
    tuple[Person, ...],
    BeforeValidator(_json_array),
    Field(max_length=50),
    AfterValidator(_unique),
]
Organizations = Annotated[
    tuple[Organization, ...],
    BeforeValidator(_json_array),
    Field(max_length=50),
    AfterValidator(_unique),
]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SemanticMetadataSchema(StrictSchema):
    representation_id: Annotated[StrictText, StringConstraints(max_length=200)] = Field(
        default=None
    )
    model: Annotated[StrictText, StringConstraints(max_length=200)] = Field(
        default=None
    )


class EnrichmentErrorSchema(StrictSchema):
    section: Annotated[StrictText, StringConstraints(max_length=100)]
    code: Annotated[StrictText, StringConstraints(max_length=100)]


class EnrichmentSectionsSchema(StrictSchema):
    topics: Topics = Field(default=None)
    countries: Countries = Field(default=None)
    cities: Cities = Field(default=None)
    locations: Locations = Field(default=None)
    people: People = Field(default=None)
    organizations: Organizations = Field(default=None)
    event_type: EventType = Field(default=None)
    importance: Score = Field(default=None)
    novelty: Score = Field(default=None)
    source_quality: Score = Field(default=None)
    semantic_metadata: SemanticMetadataSchema = Field(default=None)


class EnrichmentResultSchema(StrictSchema):
    schema_version: Literal["1.0"]
    status: Literal["complete", "partial", "invalid", "failed"]
    sections: EnrichmentSectionsSchema
    errors: Annotated[
        tuple[EnrichmentErrorSchema, ...],
        BeforeValidator(_json_array),
        Field(max_length=20),
    ] = ()


SECTION_ADAPTERS: dict[str, TypeAdapter[Any]] = {
    "topics": TypeAdapter(Topics),
    "countries": TypeAdapter(Countries),
    "cities": TypeAdapter(Cities),
    "locations": TypeAdapter(Locations),
    "people": TypeAdapter(People),
    "organizations": TypeAdapter(Organizations),
    "event_type": TypeAdapter(EventType),
    "importance": TypeAdapter(Score),
    "novelty": TypeAdapter(Score),
    "source_quality": TypeAdapter(Score),
    "semantic_metadata": TypeAdapter(SemanticMetadataSchema),
}


class EnrichmentEnvelopeSchema(StrictSchema):
    schema_version: Literal["1.0"]
    status: Literal["complete", "partial", "invalid", "failed"]
    sections: dict[str, Any]
    errors: Annotated[
        tuple[EnrichmentErrorSchema, ...],
        BeforeValidator(_json_array),
        Field(max_length=20),
    ] = ()

    @field_validator("sections")
    @classmethod
    def reject_unknown_sections(cls, sections: dict[str, Any]) -> dict[str, Any]:
        unknown = sections.keys() - SECTION_ADAPTERS.keys()
        if unknown:
            raise ValueError(f"unknown enrichment sections: {sorted(unknown)!r}")
        return sections
