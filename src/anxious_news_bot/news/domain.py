from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID


class SourceType(StrEnum):
    RSS = "rss"
    ATOM = "atom"


class CycleStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class SourceRunStatus(StrEnum):
    PENDING = "pending"
    FETCHING = "fetching"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    NOT_MODIFIED = "not_modified"
    FAILED = "failed"


class ProvenanceStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class DecisionType(StrEnum):
    EXACT_URL = "exact_url"
    NEAR_DUPLICATE = "near_duplicate"
    EVENT_RELATED = "event_related"


class DecisionOutcome(StrEnum):
    DUPLICATE = "duplicate"
    REVIEW = "review"
    DISTINCT = "distinct"
    SAME_EVENT = "same_event"


class EventGroupStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"


class AnalysisStatus(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    COMPLETE = "complete"
    PARTIAL = "partial"
    INVALID = "invalid"
    FAILED = "failed"


class FetchStatus(StrEnum):
    FETCHED = "fetched"
    NOT_MODIFIED = "not_modified"


class AggregationStatus(StrEnum):
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    ALREADY_RUNNING = "already_running"


@dataclass(frozen=True, slots=True)
class NewsSource:
    id: UUID
    name: str
    source_type: SourceType
    endpoint_url: str
    region: str
    language_code: str
    enabled: bool = True
    country_code: str | None = None
    quality_score: Decimal | None = None
    polling_interval_seconds: int = 3600
    last_polled_at: datetime | None = None
    next_poll_at: datetime | None = None
    etag: str | None = None
    last_modified: str | None = None
    credential_ref: str | None = None


@dataclass(frozen=True, slots=True)
class CollectionCycle:
    id: UUID
    status: CycleStatus
    started_at: datetime
    configuration_version: str
    completed_at: datetime | None = None
    new_article_count: int = 0
    source_success_count: int = 0
    source_failure_count: int = 0


@dataclass(frozen=True, slots=True)
class SourceRun:
    id: UUID
    cycle_id: UUID
    source_id: UUID
    status: SourceRunStatus
    started_at: datetime
    completed_at: datetime | None = None
    fetched_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    error_code: str | None = None
    error_context: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RawArticle:
    source_id: UUID
    original_url: str
    title: str | None
    summary: str | None = None
    content: str | None = None
    external_id: str | None = None
    published_at: datetime | None = None
    language_code: str | None = None
    payload: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class NormalizedArticleCandidate:
    source_id: UUID
    title: str
    summary: str | None
    canonical_url: str
    original_url: str
    published_at: datetime | None
    ingested_at: datetime
    language_code: str
    normalized_text: str
    geographic_relevance: tuple[str, ...] = ()
    topic_metadata: tuple[str, ...] = ()
    canonicalization_version: str = "1.0"
    payload_hash: str = ""
    external_id: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedArticle:
    id: UUID
    title: str
    summary: str | None
    canonical_url: str
    canonicalization_version: str
    primary_source_id: UUID
    published_at: datetime | None
    ingested_at: datetime
    language_code: str
    normalized_text: str
    created_in_cycle_id: UUID
    geographic_relevance: tuple[str, ...] = ()
    topic_metadata: tuple[str, ...] = ()
    event_group_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class SourceArticleRecord:
    id: UUID
    source_run_id: UUID
    source_id: UUID
    original_url: str
    payload_hash: str
    observed_at: datetime
    status: ProvenanceStatus
    external_id: str | None = None
    raw_payload: Mapping[str, Any] | None = None
    rejection_code: str | None = None
    article_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class DeduplicationDecision:
    id: UUID
    left_article_id: UUID
    right_article_id: UUID
    decision_type: DecisionType
    outcome: DecisionOutcome
    threshold_configuration: Mapping[str, Any]
    normalization_version: str
    evidence: Mapping[str, Any]
    decided_at: datetime
    title_similarity: Decimal | None = None
    content_similarity: Decimal | None = None


@dataclass(frozen=True, slots=True)
class EventGroup:
    id: UUID
    status: EventGroupStatus
    created_at: datetime
    updated_at: datetime
    label: str | None = None
    event_type: str | None = None
    representative_article_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ArticleAnalysis:
    id: UUID
    article_id: UUID
    status: AnalysisStatus
    schema_version: str
    analyzer_name: str
    analyzer_version: str
    created_at: datetime
    topics: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    cities: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()
    people: tuple[str, ...] = ()
    organizations: tuple[str, ...] = ()
    event_type: str | None = None
    importance_score: Decimal | None = None
    novelty_score: Decimal | None = None
    source_quality_score: Decimal | None = None
    semantic_metadata: Mapping[str, Any] | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, AnalysisStatus):
            raise TypeError("status must be an AnalysisStatus")
        for name in ("schema_version", "analyzer_name", "analyzer_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        bounds = {
            "topics": (20, 100),
            "countries": (20, 2),
            "cities": (30, 120),
            "locations": (30, 120),
            "people": (50, 160),
            "organizations": (50, 200),
        }
        for name, (maximum_items, maximum_length) in bounds.items():
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise TypeError(f"{name} must be a tuple")
            if len(values) > maximum_items or len(values) != len(set(values)):
                raise ValueError(f"{name} must be bounded and unique")
            if any(
                not isinstance(value, str) or not value or len(value) > maximum_length
                for value in values
            ):
                raise ValueError(f"{name} contains an invalid value")
        if any(
            len(country) != 2 or not country.isascii() or not country.isupper()
            for country in self.countries
        ):
            raise ValueError("countries must contain uppercase ISO alpha-2 values")
        if self.event_type is not None and (
            not isinstance(self.event_type, str)
            or not self.event_type
            or len(self.event_type) > 100
        ):
            raise ValueError("event_type is invalid")
        for name in (
            "importance_score",
            "novelty_score",
            "source_quality_score",
        ):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, Decimal) or not Decimal(0) <= value <= Decimal(1)
            ):
                raise ValueError(f"{name} must be a Decimal between zero and one")
        if self.semantic_metadata is not None:
            if not isinstance(self.semantic_metadata, Mapping):
                raise TypeError("semantic_metadata must be a mapping")
            if set(self.semantic_metadata) - {"representation_id", "model"}:
                raise ValueError("semantic_metadata contains unknown fields")
            for value in self.semantic_metadata.values():
                if not isinstance(value, str) or not value or len(value) > 200:
                    raise ValueError("semantic_metadata contains an invalid value")
        if self.error_code is not None and (
            not isinstance(self.error_code, str)
            or not self.error_code
            or len(self.error_code) > 100
        ):
            raise ValueError("error_code is invalid")


@dataclass(frozen=True, slots=True)
class ConditionalHeaders:
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class FetchResult:
    status: FetchStatus
    records: tuple[RawArticle, ...] = ()
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    candidate: NormalizedArticleCandidate | None = None
    rejection_code: str | None = None
    diagnostic_context: Mapping[str, Any] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return self.candidate is not None


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    outcome: DecisionOutcome
    matched_article_id: UUID | None = None
    title_similarity: Decimal | None = None
    content_similarity: Decimal | None = None
    thresholds: Mapping[str, Any] = field(default_factory=dict)
    algorithm_version: str = "1.0"
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EventGroupingResult:
    outcome: DecisionOutcome
    event_group_id: UUID | None = None
    score: Decimal | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EnrichmentResult:
    status: AnalysisStatus
    schema_version: str
    sections: Mapping[str, Any] = field(default_factory=dict)
    errors: tuple[Mapping[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class NewlyAvailableArticles:
    cycle_id: UUID
    article_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class AggregationResult:
    status: AggregationStatus
    cycle_id: UUID | None = None
    article_ids: tuple[UUID, ...] = ()
    source_success_count: int = 0
    source_failure_count: int = 0
