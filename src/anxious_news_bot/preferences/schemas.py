from __future__ import annotations

import re
import unicodedata
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

from anxious_news_bot.preferences.domain import PreferenceOrigin


def _tuple(value: Any) -> Any:
    return tuple(value) if isinstance(value, list) else value


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _unique_strings(values: tuple[str, ...]) -> tuple[str, ...]:
    if len({_normalized(value) for value in values}) != len(values):
        raise ValueError("items must be unique after normalization")
    return values


StrictText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1),
]
SemanticKey = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$",
        min_length=3,
        max_length=160,
    ),
]
WeightText = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^(?:-?(?:0\.(?:0[1-9]|[1-9][0-9]))|0\.00|-?1\.00)$",
    ),
]


def parse_weight(value: str) -> Decimal:
    return Decimal(value)


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class GeneratedOptionSchema(StrictSchema):
    ordinal: Annotated[int, Field(strict=True, ge=1, le=4)]
    label: Annotated[StrictText, StringConstraints(max_length=80)]


Options = Annotated[
    tuple[GeneratedOptionSchema, ...],
    BeforeValidator(_tuple),
    Field(min_length=4, max_length=4),
]


class GeneratedQuestionSchema(StrictSchema):
    ordinal: Annotated[int, Field(strict=True, ge=1, le=10)]
    dimension_key: Annotated[SemanticKey, StringConstraints(max_length=100)]
    text: Annotated[StrictText, StringConstraints(min_length=5, max_length=160)]
    options: Options

    @model_validator(mode="after")
    def validate_options(self) -> GeneratedQuestionSchema:
        if tuple(option.ordinal for option in self.options) != (1, 2, 3, 4):
            raise ValueError("option ordinals must be exactly 1 through 4")
        _unique_strings(tuple(option.label for option in self.options))
        return self


Questions = Annotated[
    tuple[GeneratedQuestionSchema, ...],
    BeforeValidator(_tuple),
    Field(min_length=10, max_length=10),
]


class QuestionnaireGenerationSchema(StrictSchema):
    schema_version: Literal["1.0"]
    questions: Questions

    @model_validator(mode="after")
    def validate_questions(self) -> QuestionnaireGenerationSchema:
        if tuple(question.ordinal for question in self.questions) != tuple(
            range(1, 11)
        ):
            raise ValueError("question ordinals must be exactly 1 through 10")
        _unique_strings(tuple(question.dimension_key for question in self.questions))
        _unique_strings(tuple(question.text for question in self.questions))
        return self


Reason = Annotated[StrictText, StringConstraints(max_length=500)]
ParameterName = Annotated[StrictText, StringConstraints(max_length=160)]
Description = Annotated[StrictText, StringConstraints(max_length=1000)]
Instructions = Annotated[StrictText, StringConstraints(max_length=2000)]


class CreateChangeSchema(StrictSchema):
    action: Literal["create"]
    semantic_key: SemanticKey
    name: ParameterName
    description: Description
    evaluation_instructions: Instructions
    target_weight: WeightText
    reason: Reason

    @property
    def weight(self) -> Decimal:
        return parse_weight(self.target_weight)


class AdjustChangeSchema(StrictSchema):
    action: Literal["adjust"]
    parameter_id: UUID
    target_weight: WeightText
    reason: Reason

    @property
    def weight(self) -> Decimal:
        return parse_weight(self.target_weight)


class RefineChangeSchema(StrictSchema):
    action: Literal["refine"]
    parameter_id: UUID
    name: ParameterName | None = None
    description: Description | None = None
    evaluation_instructions: Instructions | None = None
    reason: Reason

    @model_validator(mode="after")
    def at_least_one_change(self) -> RefineChangeSchema:
        if not any(
            (
                self.name is not None,
                self.description is not None,
                self.evaluation_instructions is not None,
            )
        ):
            raise ValueError("refine requires at least one descriptive field")
        return self


class DeactivateChangeSchema(StrictSchema):
    action: Literal["deactivate"]
    parameter_id: UUID
    reason: Reason


class ReactivateChangeSchema(StrictSchema):
    action: Literal["reactivate"]
    parameter_id: UUID
    reason: Reason


PreferenceChangeSchema = Annotated[
    CreateChangeSchema
    | AdjustChangeSchema
    | RefineChangeSchema
    | DeactivateChangeSchema
    | ReactivateChangeSchema,
    Field(discriminator="action"),
]


class BasePreferenceChangesSchema(StrictSchema):
    schema_version: Literal["1.0"]
    base_profile_revision: Annotated[int, Field(strict=True, ge=0)]
    changes: Annotated[
        tuple[PreferenceChangeSchema, ...],
        BeforeValidator(_tuple),
        Field(min_length=1, max_length=20),
    ]

    @model_validator(mode="after")
    def unique_targets(self) -> BasePreferenceChangesSchema:
        targets = [
            change.parameter_id
            for change in self.changes
            if hasattr(change, "parameter_id")
        ]
        if len(targets) != len(set(targets)):
            raise ValueError("a parameter may be targeted only once")
        creates = [
            change.semantic_key
            for change in self.changes
            if isinstance(change, CreateChangeSchema)
        ]
        if len(creates) != len(set(creates)):
            raise ValueError("create semantic keys must be unique")
        return self


class PreferenceChangesSchema(BasePreferenceChangesSchema):
    questionnaire_id: UUID

    @property
    def source(self) -> PreferenceOrigin:
        return PreferenceOrigin.QUESTIONNAIRE

    @property
    def source_request_id(self) -> UUID:
        return self.questionnaire_id


class ExplicitPreferenceChangesSchema(BasePreferenceChangesSchema):
    request_id: UUID

    @property
    def source(self) -> PreferenceOrigin:
        return PreferenceOrigin.EXPLICIT

    @property
    def source_request_id(self) -> UUID:
        return self.request_id


class EquivalenceSchema(StrictSchema):
    schema_version: Literal["1.0"]
    outcome: Literal["equivalent", "distinct"]
    candidate_parameter_id: UUID | None = None
    confidence: Annotated[Decimal, Field(strict=True, ge=0, le=1)]
    reason: Reason


CHANGE_ADAPTER = TypeAdapter(PreferenceChangeSchema)
QUESTIONNAIRE_CHANGES_ADAPTER = TypeAdapter(PreferenceChangesSchema)
EXPLICIT_CHANGES_ADAPTER = TypeAdapter(ExplicitPreferenceChangesSchema)
YES_NO_WORDS = re.compile(
    r"^(yes|no|да|нет|rather yes|rather no|скорее да|скорее нет)$", re.IGNORECASE
)
