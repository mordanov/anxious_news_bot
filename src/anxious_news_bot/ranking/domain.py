from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from enum import StrEnum
from uuid import UUID

from anxious_news_bot.news.domain import DecisionOutcome
from anxious_news_bot.preferences.domain import PreferenceOrigin

DECIMAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
WEIGHT_QUANTUM = Decimal("0.01")
RELEVANCE_QUANTUM = Decimal("0.0001")
FACTOR_INPUT_QUANTUM = Decimal("0.0001")
COEFFICIENT_QUANTUM = Decimal("0.00001")
SCORE_QUANTUM = Decimal("0.00000001")
COEFFICIENT_SUM = Decimal("1.00000")
PERSONAL_COEFFICIENT_FLOOR = Decimal("0.40000")
MAXIMUM_CANDIDATE_COUNT = 500
MAXIMUM_ACTIVE_PARAMETERS = 100
MAXIMUM_EXPLANATION_CONTRIBUTIONS = 10
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_REASON_CODE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


class EvaluationStatus(StrEnum):
    PENDING = "pending"
    EVALUATING = "evaluating"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"
    STALE = "stale"


class EvaluationAttemptStatus(StrEnum):
    RECEIVED = "received"
    INVALID = "invalid"
    TRANSIENT_FAILURE = "transient_failure"
    ACCEPTED = "accepted"
    FAILED = "failed"


class RankingStatus(StrEnum):
    PENDING = "pending"
    SCORING = "scoring"
    DIVERSIFYING = "diversifying"
    COMPLETE = "complete"
    FAILED = "failed"
    STALE = "stale"


class PersonalState(StrEnum):
    COMPLETE = "complete"
    NO_ACTIVE_PARAMETERS = "no_active_parameters"
    ALL_WEIGHTS_ZERO = "all_weights_zero"


class EligibilityReason(StrEnum):
    ELIGIBLE = "eligible"
    MISSING_GENERIC_ANALYSIS = "missing_generic_analysis"
    INCOMPLETE_GENERIC_ANALYSIS = "incomplete_generic_analysis"
    INCOMPLETE_PERSONAL_EVALUATION = "incomplete_personal_evaluation"
    SOURCE_QUALITY_BELOW_MINIMUM = "source_quality_below_minimum"
    INVALID_PUBLISHED_AT = "invalid_published_at"
    FUTURE_PUBLICATION = "future_publication"
    OBSOLETE_PUBLICATION = "obsolete_publication"
    DISQUALIFYING_DUPLICATE = "disqualifying_duplicate"
    EXPLICIT_VETO = "explicit_veto"


class SelectionReason(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    SELECTED = "selected"
    INELIGIBLE = "ineligible"
    REJECTED_EVENT_CAP = "rejected_event_cap"
    REJECTED_TOPIC_CAP = "rejected_topic_cap"
    REJECTED_SOURCE_CAP = "rejected_source_cap"
    SHORTAGE = "shortage"
    EXHAUSTED_POOL = "exhausted_pool"


class RetentionScope(StrEnum):
    RAW_RESPONSES = "raw_responses"
    EVALUATION_DETAIL = "evaluation_detail"
    RANKING_DETAIL = "ranking_detail"


def parse_exact_decimal(
    value: str | Decimal,
    *,
    places: int | None = None,
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
    allow_negative_zero: bool = False,
) -> Decimal:
    if isinstance(value, Decimal):
        candidate = value
    elif isinstance(value, str):
        try:
            candidate = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("value must be a decimal") from exc
    else:
        raise TypeError("value must be a decimal string or Decimal")
    if not candidate.is_finite():
        raise ValueError("value must be finite")
    if not allow_negative_zero and candidate.is_zero() and candidate.as_tuple().sign:
        raise ValueError("negative zero is not allowed")
    if places is not None and candidate.as_tuple().exponent != -places:
        raise ValueError(f"value must use exactly {places} decimal places")
    if minimum is not None and candidate < minimum:
        raise ValueError(f"value must be at least {minimum}")
    if maximum is not None and candidate > maximum:
        raise ValueError(f"value must be at most {maximum}")
    return candidate


def quantize_score(value: Decimal) -> Decimal:
    with localcontext(DECIMAL_CONTEXT):
        quantized = value.quantize(SCORE_QUANTUM)
    return Decimal("0.00000000") if quantized.is_zero() else quantized


def _require_text(value: str, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if len(value) > maximum:
        raise ValueError(f"{field_name} must be at most {maximum} characters")
    return value


def _require_digest(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ValueError(f"{field_name} must be a 64-character lowercase hex digest")
    return value


@dataclass(frozen=True, slots=True)
class RankingPreference:
    id: UUID
    user_id: UUID
    semantic_key: str
    name: str
    description: str
    evaluation_instructions: str
    weight: Decimal
    origin: PreferenceOrigin
    effective_authority: PreferenceOrigin
    active: bool

    def __post_init__(self) -> None:
        _require_text(self.semantic_key, "semantic_key", maximum=160)
        _require_text(self.name, "name", maximum=160)
        _require_text(self.description, "description", maximum=1000)
        _require_text(
            self.evaluation_instructions,
            "evaluation_instructions",
            maximum=2000,
        )
        parse_exact_decimal(
            self.weight,
            places=2,
            minimum=Decimal("-1.00"),
            maximum=Decimal("1.00"),
        )
        if not isinstance(self.origin, PreferenceOrigin):
            raise TypeError("origin must be a PreferenceOrigin")
        if not isinstance(self.effective_authority, PreferenceOrigin):
            raise TypeError("effective_authority must be a PreferenceOrigin")
        if not isinstance(self.active, bool):
            raise TypeError("active must be a bool")


@dataclass(frozen=True, slots=True)
class ArticleEvaluationIdentity:
    user_id: UUID
    article_id: UUID
    article_analysis_id: UUID
    profile_revision: int
    parameter_set_hash: str
    schema_version: str
    evaluator_name: str
    evaluator_version: str
    prompt_version: str

    def __post_init__(self) -> None:
        if self.profile_revision < 0:
            raise ValueError("profile_revision must be non-negative")
        _require_digest(self.parameter_set_hash, "parameter_set_hash")
        _require_text(self.schema_version, "schema_version", maximum=20)
        _require_text(self.evaluator_name, "evaluator_name", maximum=100)
        _require_text(self.evaluator_version, "evaluator_version", maximum=100)
        _require_text(self.prompt_version, "prompt_version", maximum=100)


@dataclass(frozen=True, slots=True)
class ArticleParameterRelevance:
    parameter_id: UUID
    relevance: Decimal
    reason_code: str

    def __post_init__(self) -> None:
        parse_exact_decimal(
            self.relevance,
            places=4,
            minimum=Decimal("-1.0000"),
            maximum=Decimal("1.0000"),
        )
        if not isinstance(self.reason_code, str) or not _REASON_CODE.fullmatch(
            self.reason_code
        ):
            raise ValueError("reason_code must be a canonical identifier")
        if len(self.reason_code) < 3 or len(self.reason_code) > 80:
            raise ValueError("reason_code must be between 3 and 80 characters")


@dataclass(frozen=True, slots=True)
class ArticleEvaluation:
    run_id: UUID
    identity: ArticleEvaluationIdentity
    status: EvaluationStatus
    relevances: tuple[ArticleParameterRelevance, ...]
    accepted_attempt_id: UUID | None = None
    attempt_count: int = 0
    completed_at: datetime | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, EvaluationStatus):
            raise TypeError("status must be an EvaluationStatus")
        if self.attempt_count < 0:
            raise ValueError("attempt_count must be non-negative")
        if len(self.relevances) > MAXIMUM_ACTIVE_PARAMETERS:
            raise ValueError("relevances must be bounded to the configured maximum")
        parameter_ids = [item.parameter_id for item in self.relevances]
        if len(parameter_ids) != len(set(parameter_ids)):
            raise ValueError("relevances must not contain duplicate parameter ids")
        if self.error_code is not None:
            _require_text(self.error_code, "error_code", maximum=100)


@dataclass(frozen=True, slots=True)
class RankingConfiguration:
    version: str
    tie_policy_version: str
    retention_policy_version: str
    personal_coefficient: Decimal
    importance_coefficient: Decimal
    freshness_coefficient: Decimal
    quality_coefficient: Decimal
    novelty_coefficient: Decimal
    freshness_horizon_seconds: int
    future_tolerance_seconds: int
    minimum_source_quality: Decimal
    maximum_candidate_count: int
    event_cap: int
    topic_cap: int
    source_cap: int
    explicit_weight_threshold: Decimal
    explicit_relevance_threshold: Decimal
    explanation_contribution_limit: int

    def __post_init__(self) -> None:
        for field_name in (
            "version",
            "tie_policy_version",
            "retention_policy_version",
        ):
            _require_text(getattr(self, field_name), field_name, maximum=100)
        coefficients = self.coefficients
        for value in coefficients:
            parse_exact_decimal(
                value,
                places=5,
                minimum=Decimal("0.00000"),
                maximum=Decimal("1.00000"),
            )
        if sum(coefficients, start=Decimal("0.00000")) != COEFFICIENT_SUM:
            raise ValueError("coefficients must sum exactly to 1.00000")
        if self.personal_coefficient < PERSONAL_COEFFICIENT_FLOOR:
            raise ValueError("personal coefficient must be at least 0.40000")
        if self.freshness_horizon_seconds <= 0:
            raise ValueError("freshness_horizon_seconds must be positive")
        if self.future_tolerance_seconds < 0:
            raise ValueError("future_tolerance_seconds must be non-negative")
        parse_exact_decimal(
            self.minimum_source_quality,
            places=5,
            minimum=Decimal("0.00000"),
            maximum=Decimal("1.00000"),
        )
        if not 1 <= self.maximum_candidate_count <= MAXIMUM_CANDIDATE_COUNT:
            raise ValueError("maximum_candidate_count must be between 1 and 500")
        for field_name in ("event_cap", "topic_cap", "source_cap"):
            if getattr(self, field_name) <= 0:
                raise ValueError(f"{field_name} must be positive")
        parse_exact_decimal(
            self.explicit_weight_threshold,
            places=2,
            minimum=Decimal("0.00"),
            maximum=Decimal("1.00"),
        )
        parse_exact_decimal(
            self.explicit_relevance_threshold,
            places=4,
            minimum=Decimal("0.0000"),
            maximum=Decimal("1.0000"),
        )
        if (
            not 1
            <= self.explanation_contribution_limit
            <= MAXIMUM_EXPLANATION_CONTRIBUTIONS
        ):
            raise ValueError("explanation_contribution_limit must be between 1 and 10")

    @property
    def coefficients(self) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
        return (
            self.personal_coefficient,
            self.importance_coefficient,
            self.freshness_coefficient,
            self.quality_coefficient,
            self.novelty_coefficient,
        )


@dataclass(frozen=True, slots=True)
class FactorSnapshot:
    importance: Decimal
    freshness: Decimal
    quality: Decimal
    novelty: Decimal

    def __post_init__(self) -> None:
        for field_name in ("importance", "freshness", "quality", "novelty"):
            parse_exact_decimal(
                getattr(self, field_name),
                places=8,
                minimum=Decimal("0.00000000"),
                maximum=Decimal("1.00000000"),
            )


@dataclass(frozen=True, slots=True)
class RankingArticleSnapshot:
    article_id: UUID
    article_analysis_id: UUID | None
    source_id: UUID
    event_group_id: UUID | None
    topic_key: str | None
    published_at: datetime | None
    importance_score: Decimal | None
    novelty_score: Decimal | None
    source_quality_score: Decimal | None
    duplicate_outcome: DecisionOutcome | None
    title: str | None = None
    summary: str | None = None
    normalized_text: str | None = None
    language_code: str | None = None
    evaluation_run_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.topic_key is not None:
            _require_text(self.topic_key, "topic_key", maximum=160)
        if self.title is not None:
            _require_text(self.title, "title", maximum=500)
        if self.summary is not None:
            _require_text(self.summary, "summary", maximum=4000)
        if self.normalized_text is not None:
            _require_text(self.normalized_text, "normalized_text", maximum=20_000)
        if self.language_code is not None:
            _require_text(self.language_code, "language_code", maximum=35)
        for field_name in (
            "importance_score",
            "novelty_score",
            "source_quality_score",
        ):
            value = getattr(self, field_name)
            if value is not None:
                parse_exact_decimal(
                    value,
                    places=4,
                    minimum=Decimal("0.0000"),
                    maximum=Decimal("1.0000"),
                )
        if self.duplicate_outcome is not None and not isinstance(
            self.duplicate_outcome, DecisionOutcome
        ):
            raise TypeError("duplicate_outcome must be a DecisionOutcome")


@dataclass(frozen=True, slots=True)
class RankingIdentity:
    request_id: str
    user_id: UUID
    profile_revision: int
    candidate_set_hash: str
    configuration_version: str
    ranking_at: datetime
    requested_count: int

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id", maximum=200)
        if self.profile_revision < 0:
            raise ValueError("profile_revision must be non-negative")
        _require_digest(self.candidate_set_hash, "candidate_set_hash")
        _require_text(self.configuration_version, "configuration_version", maximum=100)
        if self.requested_count <= 0:
            raise ValueError("requested_count must be positive")


@dataclass(frozen=True, slots=True)
class ContributionSnapshot:
    parameter_id: UUID
    parameter_name: str
    origin: PreferenceOrigin
    effective_authority: PreferenceOrigin
    weight: Decimal
    relevance: Decimal
    contribution: Decimal

    def __post_init__(self) -> None:
        _require_text(self.parameter_name, "parameter_name", maximum=160)
        if not isinstance(self.origin, PreferenceOrigin):
            raise TypeError("origin must be a PreferenceOrigin")
        if not isinstance(self.effective_authority, PreferenceOrigin):
            raise TypeError("effective_authority must be a PreferenceOrigin")
        parse_exact_decimal(
            self.weight,
            places=2,
            minimum=Decimal("-1.00"),
            maximum=Decimal("1.00"),
        )
        parse_exact_decimal(
            self.relevance,
            places=4,
            minimum=Decimal("-1.0000"),
            maximum=Decimal("1.0000"),
        )
        parse_exact_decimal(
            self.contribution,
            places=8,
            minimum=Decimal("-1.00000000"),
            maximum=Decimal("1.00000000"),
        )


@dataclass(frozen=True, slots=True)
class SelectionOutcome:
    selected: bool
    reason: SelectionReason
    position: int | None = None
    explicit_protected: bool = False
    diversity_pass: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.selected, bool):
            raise TypeError("selected must be a bool")
        if not isinstance(self.reason, SelectionReason):
            raise TypeError("reason must be a SelectionReason")
        if self.position is not None and self.position <= 0:
            raise ValueError("position must be positive when provided")
        if self.diversity_pass is not None and self.diversity_pass <= 0:
            raise ValueError("diversity_pass must be positive when provided")


@dataclass(frozen=True, slots=True)
class RankingRecord:
    article_id: UUID
    article_analysis_id: UUID | None
    source_id: UUID
    event_group_id: UUID | None
    topic_key: str | None
    published_at: datetime | None
    evaluation_run_id: UUID | None
    personal_state: PersonalState
    personal_numerator: Decimal
    personal_denominator: Decimal
    personal_signed: Decimal
    personal_factor: Decimal
    factors: FactorSnapshot
    unrounded_score: Decimal
    final_score: Decimal
    eligible: bool
    eligibility_reason: EligibilityReason
    explicit_protected: bool
    explicit_veto: bool
    selection: SelectionOutcome
    contributions: tuple[ContributionSnapshot, ...] = ()
    initial_position: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.personal_state, PersonalState):
            raise TypeError("personal_state must be a PersonalState")
        if self.personal_denominator < 0:
            raise ValueError("personal_denominator must be non-negative")
        parse_exact_decimal(
            self.personal_signed,
            places=8,
            minimum=Decimal("-1.00000000"),
            maximum=Decimal("1.00000000"),
        )
        parse_exact_decimal(
            self.personal_factor,
            places=8,
            minimum=Decimal("0.00000000"),
            maximum=Decimal("1.00000000"),
        )
        parse_exact_decimal(
            quantize_score(self.unrounded_score),
            places=8,
            minimum=Decimal("0.00000000"),
            maximum=Decimal("1.00000000"),
        )
        parse_exact_decimal(
            self.final_score,
            places=8,
            minimum=Decimal("0.00000000"),
            maximum=Decimal("1.00000000"),
        )
        if not isinstance(self.eligible, bool):
            raise TypeError("eligible must be a bool")
        if not isinstance(self.eligibility_reason, EligibilityReason):
            raise TypeError("eligibility_reason must be an EligibilityReason")
        if not isinstance(self.explicit_protected, bool):
            raise TypeError("explicit_protected must be a bool")
        if not isinstance(self.explicit_veto, bool):
            raise TypeError("explicit_veto must be a bool")
        if self.initial_position is not None and self.initial_position <= 0:
            raise ValueError("initial_position must be positive when provided")
        parameter_ids = [item.parameter_id for item in self.contributions]
        if len(parameter_ids) != len(set(parameter_ids)):
            raise ValueError("contributions must not contain duplicate parameter ids")


@dataclass(frozen=True, slots=True)
class RankingResult:
    ranking_run_id: UUID
    identity: RankingIdentity
    status: RankingStatus
    records: tuple[RankingRecord, ...]
    selected_count: int
    excluded_count: int
    selected_cap_vector: tuple[int, int, int] | None = None
    unsatisfied_limits: tuple[str, ...] = ()
    completed_at: datetime | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, RankingStatus):
            raise TypeError("status must be a RankingStatus")
        if self.selected_count < 0 or self.excluded_count < 0:
            raise ValueError("selected_count and excluded_count must be non-negative")
        if self.selected_count > self.identity.requested_count:
            raise ValueError("selected_count must not exceed requested_count")
        if self.selected_cap_vector is not None:
            if len(self.selected_cap_vector) != 3 or any(
                value <= 0 for value in self.selected_cap_vector
            ):
                raise ValueError("selected_cap_vector must contain three positive caps")
        if self.error_code is not None:
            _require_text(self.error_code, "error_code", maximum=100)


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    raw_response_days: int
    detail_days: int
    batch_size: int

    def __post_init__(self) -> None:
        if self.raw_response_days < 0:
            raise ValueError("raw_response_days must be non-negative")
        if self.detail_days < 0:
            raise ValueError("detail_days must be non-negative")
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")


@dataclass(frozen=True, slots=True)
class RankingRetentionResult:
    raw_texts_removed: int = 0
    raw_responses_removed: int = 0
    evaluation_details_removed: int = 0
    ranking_details_removed: int = 0
    compact_audit_rows_preserved: int = 0
    already_running: bool = False
