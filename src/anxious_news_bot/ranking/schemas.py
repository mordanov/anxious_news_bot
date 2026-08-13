from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from anxious_news_bot.news.domain import DecisionOutcome
from anxious_news_bot.preferences.domain import PreferenceOrigin
from anxious_news_bot.ranking.domain import (
    ArticleParameterRelevance,
    ContributionSnapshot,
    FactorSnapshot,
    RankingArticleSnapshot,
    RankingConfiguration,
    RankingIdentity,
    RankingPreference,
    SelectionOutcome,
    SelectionReason,
)


def _tuple(value: Any) -> Any:
    return tuple(value) if isinstance(value, list) else value


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


DigestText = Annotated[
    str,
    StringConstraints(
        strict=True, pattern=r"^[a-f0-9]{64}$", min_length=64, max_length=64
    ),
]
WeightText = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^(?:-?(?:0\.(?:0[1-9]|[1-9][0-9]))|0\.00|-?1\.00)$",
    ),
]
RelevanceText = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^(?:-1\.0000|-0\.(?:[0-9]{3}[1-9]|[0-9]{2}[1-9][0-9]|[0-9][1-9][0-9]{2}|[1-9][0-9]{3})|0\.0000|0\.[0-9]{4}|1\.0000)$",
    ),
]
FactorInputText = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^(?:0\.[0-9]{4}|1\.0000)$"),
]
CoefficientText = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^(?:0\.[0-9]{5}|1\.00000)$"),
]
FactorText = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^(?:0\.[0-9]{8}|1\.00000000)$"),
]
SignedScoreText = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^(?:-1\.00000000|-0\.[0-9]{8}|0\.[0-9]{8}|1\.00000000)$",
    ),
]

AccumulatorText = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^(?:0|[1-9][0-9]{0,2})\.[0-9]{8}$",
    ),
]
SignedAccumulatorText = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^(?:-?(?:0|[1-9][0-9]{0,2}))\.[0-9]{8}$",
    ),
]
ReasonCode = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$",
        min_length=3,
        max_length=80,
    ),
]
TopicKey = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=160),
]
VersionText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=100),
]


class RankingPreferenceSchema(StrictSchema):
    id: UUID
    user_id: UUID
    semantic_key: Annotated[TopicKey, StringConstraints(max_length=160)]
    name: Annotated[TopicKey, StringConstraints(max_length=160)]
    description: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=1000
        ),
    ]
    evaluation_instructions: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=2000
        ),
    ]
    weight: WeightText
    origin: PreferenceOrigin
    effective_authority: PreferenceOrigin
    active: bool

    @property
    def weight_decimal(self) -> Decimal:
        return Decimal(self.weight)

    def to_domain(self) -> RankingPreference:
        return RankingPreference(
            id=self.id,
            user_id=self.user_id,
            semantic_key=self.semantic_key,
            name=self.name,
            description=self.description,
            evaluation_instructions=self.evaluation_instructions,
            weight=self.weight_decimal,
            origin=self.origin,
            effective_authority=self.effective_authority,
            active=self.active,
        )


class ArticlePreferenceRelevanceSchema(StrictSchema):
    parameter_id: UUID
    relevance: RelevanceText
    reason_code: ReasonCode

    @property
    def relevance_decimal(self) -> Decimal:
        return Decimal(self.relevance)

    def to_domain(self) -> ArticleParameterRelevance:
        return ArticleParameterRelevance(
            parameter_id=self.parameter_id,
            relevance=self.relevance_decimal,
            reason_code=self.reason_code,
        )


class ArticlePreferenceEvaluationSchema(StrictSchema):
    schema_version: Literal["1.0"]
    article_id: UUID
    article_analysis_id: UUID
    profile_revision: Annotated[int, Field(strict=True, ge=0)]
    parameter_set_hash: DigestText
    relevances: Annotated[
        tuple[ArticlePreferenceRelevanceSchema, ...],
        BeforeValidator(_tuple),
        Field(max_length=100),
    ]

    @model_validator(mode="after")
    def validate_unique_parameters(self) -> ArticlePreferenceEvaluationSchema:
        parameter_ids = tuple(item.parameter_id for item in self.relevances)
        if len(parameter_ids) != len(set(parameter_ids)):
            raise ValueError("relevances must not repeat parameter ids")
        return self


class RankingConfigurationSchema(StrictSchema):
    version: VersionText
    tie_policy_version: VersionText
    retention_policy_version: VersionText
    personal_coefficient: CoefficientText
    importance_coefficient: CoefficientText
    freshness_coefficient: CoefficientText
    quality_coefficient: CoefficientText
    novelty_coefficient: CoefficientText
    freshness_horizon_seconds: Annotated[int, Field(strict=True, gt=0)]
    future_tolerance_seconds: Annotated[int, Field(strict=True, ge=0)]
    minimum_source_quality: CoefficientText
    maximum_candidate_count: Annotated[int, Field(strict=True, gt=0, le=500)]
    event_cap: Annotated[int, Field(strict=True, gt=0)]
    topic_cap: Annotated[int, Field(strict=True, gt=0)]
    source_cap: Annotated[int, Field(strict=True, gt=0)]
    explicit_weight_threshold: WeightText
    explicit_relevance_threshold: RelevanceText
    explanation_contribution_limit: Annotated[int, Field(strict=True, gt=0, le=10)]

    @property
    def coefficients(self) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
        return (
            Decimal(self.personal_coefficient),
            Decimal(self.importance_coefficient),
            Decimal(self.freshness_coefficient),
            Decimal(self.quality_coefficient),
            Decimal(self.novelty_coefficient),
        )

    @model_validator(mode="after")
    def validate_coefficients(self) -> RankingConfigurationSchema:
        if sum(self.coefficients, start=Decimal("0.00000")) != Decimal("1.00000"):
            raise ValueError("coefficients must sum exactly to 1.00000")
        if Decimal(self.personal_coefficient) < Decimal("0.40000"):
            raise ValueError("personal coefficient must be at least 0.40000")
        return self

    def to_domain(self) -> RankingConfiguration:
        return RankingConfiguration(
            version=self.version,
            tie_policy_version=self.tie_policy_version,
            retention_policy_version=self.retention_policy_version,
            personal_coefficient=Decimal(self.personal_coefficient),
            importance_coefficient=Decimal(self.importance_coefficient),
            freshness_coefficient=Decimal(self.freshness_coefficient),
            quality_coefficient=Decimal(self.quality_coefficient),
            novelty_coefficient=Decimal(self.novelty_coefficient),
            freshness_horizon_seconds=self.freshness_horizon_seconds,
            future_tolerance_seconds=self.future_tolerance_seconds,
            minimum_source_quality=Decimal(self.minimum_source_quality),
            maximum_candidate_count=self.maximum_candidate_count,
            event_cap=self.event_cap,
            topic_cap=self.topic_cap,
            source_cap=self.source_cap,
            explicit_weight_threshold=Decimal(self.explicit_weight_threshold),
            explicit_relevance_threshold=Decimal(self.explicit_relevance_threshold),
            explanation_contribution_limit=self.explanation_contribution_limit,
        )


class FactorSchema(StrictSchema):
    importance: FactorText
    freshness: FactorText
    quality: FactorText
    novelty: FactorText

    def to_domain(self) -> FactorSnapshot:
        return FactorSnapshot(
            importance=Decimal(self.importance),
            freshness=Decimal(self.freshness),
            quality=Decimal(self.quality),
            novelty=Decimal(self.novelty),
        )


class ContributionSchema(StrictSchema):
    parameter_id: UUID
    parameter_name: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=160
        ),
    ]
    origin: PreferenceOrigin
    effective_authority: PreferenceOrigin
    weight: WeightText
    relevance: RelevanceText
    contribution: SignedScoreText

    def to_domain(self) -> ContributionSnapshot:
        return ContributionSnapshot(
            parameter_id=self.parameter_id,
            parameter_name=self.parameter_name,
            origin=self.origin,
            effective_authority=self.effective_authority,
            weight=Decimal(self.weight),
            relevance=Decimal(self.relevance),
            contribution=Decimal(self.contribution),
        )


class RankingArticleSnapshotSchema(StrictSchema):
    article_id: UUID
    article_analysis_id: UUID
    source_id: UUID
    event_group_id: UUID | None = None
    topic_key: TopicKey | None = None
    published_at: datetime | None = None
    importance_score: FactorInputText | None = None
    novelty_score: FactorInputText | None = None
    source_quality_score: FactorInputText | None = None
    duplicate_outcome: DecisionOutcome | None = None
    title: Annotated[
        str | None,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=500
        ),
    ] = None
    summary: Annotated[
        str | None,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=4000
        ),
    ] = None
    normalized_text: Annotated[
        str | None,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=20_000
        ),
    ] = None
    language_code: Annotated[
        str | None,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=35
        ),
    ] = None
    evaluation_run_id: UUID | None = None

    def to_domain(self) -> RankingArticleSnapshot:
        return RankingArticleSnapshot(
            article_id=self.article_id,
            article_analysis_id=self.article_analysis_id,
            source_id=self.source_id,
            event_group_id=self.event_group_id,
            topic_key=self.topic_key,
            published_at=self.published_at,
            importance_score=Decimal(self.importance_score)
            if self.importance_score is not None
            else None,
            novelty_score=Decimal(self.novelty_score)
            if self.novelty_score is not None
            else None,
            source_quality_score=Decimal(self.source_quality_score)
            if self.source_quality_score is not None
            else None,
            duplicate_outcome=self.duplicate_outcome,
            title=self.title,
            summary=self.summary,
            normalized_text=self.normalized_text,
            language_code=self.language_code,
            evaluation_run_id=self.evaluation_run_id,
        )


class RankingIdentitySchema(StrictSchema):
    request_id: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=200
        ),
    ]
    user_id: UUID
    profile_revision: Annotated[int, Field(strict=True, ge=0)]
    candidate_set_hash: DigestText
    configuration_version: VersionText
    ranking_at: datetime
    requested_count: Annotated[int, Field(strict=True, gt=0)]

    def to_domain(self) -> RankingIdentity:
        return RankingIdentity(
            request_id=self.request_id,
            user_id=self.user_id,
            profile_revision=self.profile_revision,
            candidate_set_hash=self.candidate_set_hash,
            configuration_version=self.configuration_version,
            ranking_at=self.ranking_at,
            requested_count=self.requested_count,
        )


class SelectionSchema(StrictSchema):
    selected: bool
    position: Annotated[int | None, Field(strict=True, ge=1)] = None
    reason: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=100
        ),
    ]
    explicit_protected: bool
    diversity_pass: Annotated[int | None, Field(strict=True, ge=1)] = None

    def to_domain(self) -> SelectionOutcome:
        return SelectionOutcome(
            selected=self.selected,
            reason=SelectionReason(self.reason),
            position=self.position,
            explicit_protected=self.explicit_protected,
            diversity_pass=self.diversity_pass,
        )


class RankingResultSchema(StrictSchema):
    ranking_run_id: UUID
    article_id: UUID
    article_analysis_id: UUID
    source_id: UUID
    event_group_id: UUID | None = None
    topic_key: TopicKey | None = None
    evaluation_run_id: UUID | None = None
    configuration_version: VersionText
    personal_state: Literal["complete", "no_active_parameters", "all_weights_zero"]
    personal_numerator: SignedAccumulatorText
    personal_denominator: AccumulatorText
    personal_signed: SignedScoreText
    personal_factor: FactorText
    factors: FactorSchema
    unrounded_score: FactorText
    final_score: FactorText
    eligible: bool
    eligibility_reason: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=100
        ),
    ]
    explicit_protected: bool
    explicit_veto: bool
    initial_position: Annotated[int | None, Field(strict=True, ge=1)] = None
    selection: SelectionSchema
    contributions: Annotated[
        tuple[ContributionSchema, ...],
        BeforeValidator(_tuple),
        Field(default_factory=tuple),
    ]


class RankingExplanationSchema(StrictSchema):
    schema_version: Literal["1.0"]
    ranking_run_id: UUID
    article_id: UUID
    configuration_version: VersionText
    personal_signed: SignedScoreText
    personal_factor: FactorText
    factors: FactorSchema
    final_score: FactorText
    eligible: bool
    eligibility_reason: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=100
        ),
    ] = "eligible"
    selection: SelectionSchema
    top_contributions: Annotated[
        tuple[ContributionSchema, ...],
        BeforeValidator(_tuple),
        Field(max_length=10),
    ]


__all__ = [
    "ArticlePreferenceEvaluationSchema",
    "ArticlePreferenceRelevanceSchema",
    "ContributionSchema",
    "FactorSchema",
    "RankingArticleSnapshotSchema",
    "RankingConfigurationSchema",
    "RankingExplanationSchema",
    "RankingIdentitySchema",
    "RankingPreferenceSchema",
    "RankingResultSchema",
]
