"""Immutable digest domain values, enums, and validation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DIGEST_COUNT_MIN = 5
DIGEST_COUNT_MAX = 20
_REASON_CODE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_DIGEST_HEX = re.compile(r"^[a-f0-9]{64}$")
_LOCAL_TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class ExecutionStatus(StrEnum):
    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    COMPOSING = "composing"
    READY = "ready"
    DELIVERING = "delivering"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    DELIVERY_UNKNOWN = "delivery_unknown"


TERMINAL_STATUSES = frozenset(
    {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.DELIVERY_UNKNOWN,
    }
)


class AttemptPhase(StrEnum):
    PREPARE = "prepare"
    COMPOSE = "compose"
    DELIVER = "deliver"


class AttemptStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    TRANSIENT_FAILURE = "transient_failure"
    PERMANENT_FAILURE = "permanent_failure"
    AMBIGUOUS = "ambiguous"


class DeliveryPartStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    UNKNOWN = "unknown"


class FailureClass(StrEnum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    AMBIGUOUS_DELIVERY = "ambiguous_delivery"


class HistoryOutcome(StrEnum):
    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"


class MaterialUpdateBasis(StrEnum):
    ACCEPTED_NOVELTY = "accepted_novelty"
    CONTENT_DELTA = "content_delta"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class MaterialUpdateOutcome(StrEnum):
    MATERIAL_UPDATE = "material_update"
    UNCHANGED = "unchanged"


class CandidateDecision(StrEnum):
    ELIGIBLE = "eligible"
    SAME_ARTICLE = "same_article"
    UNCHANGED_STORY = "unchanged_story"


def validate_digest_count(value: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < DIGEST_COUNT_MIN
        or value > DIGEST_COUNT_MAX
    ):
        raise ValueError(
            f"digest_count must be an integer from {DIGEST_COUNT_MIN} "
            f"to {DIGEST_COUNT_MAX}"
        )
    return value


def validate_iana_timezone(name: str) -> ZoneInfo:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("timezone_name must be a non-empty IANA identifier")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, KeyError) as exc:
        raise ValueError(f"invalid IANA timezone: {name}") from exc


def validate_local_time(value: str) -> time:
    if not isinstance(value, str) or _LOCAL_TIME.fullmatch(value) is None:
        raise ValueError("local_time must be an HH:MM string")
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def validate_reason_code(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _REASON_CODE.fullmatch(value):
        raise ValueError("reason_code must be a canonical identifier")
    if len(value) > 100:
        raise ValueError("reason_code must be at most 100 characters")
    return value


def validate_hex_digest(value: str, field_name: str = "hash") -> str:
    if not isinstance(value, str) or not _DIGEST_HEX.fullmatch(value):
        raise ValueError(f"{field_name} must be a 64-character lowercase hex digest")
    return value


def canonical_occurrence_key(
    local_date: date, local_time: time, timezone_name: str
) -> str:
    validate_iana_timezone(timezone_name)
    if local_time.second or local_time.microsecond:
        raise ValueError("local_time must use minute precision")
    return f"{local_date.isoformat()}/{local_time.strftime('%H:%M')}/{timezone_name}"


def compute_next_due(
    local_time: time,
    tz: ZoneInfo,
    after: datetime,
) -> datetime:
    """Compute the next UTC instant for a daily local-time schedule after `after`."""
    if after.tzinfo is None or after.utcoffset() is None:
        raise ValueError("after must be timezone-aware")
    if local_time.second or local_time.microsecond:
        raise ValueError("local_time must use minute precision")
    local_now = after.astimezone(tz)
    candidate_date = local_now.date()
    for offset in range(3):
        candidate = resolve_occurrence(
            candidate_date + timedelta(days=offset),
            local_time,
            tz,
        )
        if candidate > after.astimezone(timezone.utc):
            return candidate
    raise ValueError("unable to resolve the next daily occurrence")


def resolve_occurrence(
    local_date: date,
    local_time: time,
    tz: ZoneInfo,
) -> datetime:
    """Resolve a local wall time using earlier-fold/first-valid-after-gap rules."""
    if local_time.second or local_time.microsecond:
        raise ValueError("local_time must use minute precision")
    requested = datetime.combine(local_date, local_time)
    # A gap is bounded by normal timezone transitions, but one day keeps this
    # deterministic for unusual historical IANA transitions as well.
    for minute_offset in range(24 * 60 + 1):
        local_naive = requested + timedelta(minutes=minute_offset)
        valid_instants: set[datetime] = set()
        for fold in (0, 1):
            aware = local_naive.replace(tzinfo=tz, fold=fold)
            instant = aware.astimezone(timezone.utc)
            round_trip = instant.astimezone(tz)
            if round_trip.replace(tzinfo=None) == local_naive:
                valid_instants.add(instant)
        if valid_instants:
            # Ambiguous local times have two instants. The smaller UTC instant
            # is the earlier fold.
            return min(valid_instants)
    raise ValueError("unable to resolve local occurrence")


def content_hash(data: dict[str, Any]) -> str:
    canonical = json.dumps(
        data, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DigestCount:
    value: int

    def __post_init__(self) -> None:
        validate_digest_count(self.value)


@dataclass(frozen=True, slots=True)
class DueOccurrence:
    execution_id: UUID
    user_id: UUID
    telegram_user_id: int
    occurrence_key: str
    scheduled_for: datetime
    local_date: date
    local_time: time
    timezone_name: str
    schedule_revision: int
    digest_count: int
    language_code: str = "en"

    def __post_init__(self) -> None:
        validate_digest_count(self.digest_count)
        if self.telegram_user_id <= 0:
            raise ValueError("telegram_user_id must be positive")
        if self.schedule_revision < 0:
            raise ValueError("schedule_revision must be non-negative")
        if self.scheduled_for.tzinfo is None or self.scheduled_for.utcoffset() is None:
            raise ValueError("scheduled_for must be timezone-aware")
        validate_iana_timezone(self.timezone_name)
        expected_key = canonical_occurrence_key(
            self.local_date,
            self.local_time,
            self.timezone_name,
        )
        if self.occurrence_key != expected_key:
            raise ValueError("occurrence_key does not match the captured schedule")
        if not self.language_code:
            raise ValueError("language_code must not be empty")


@dataclass(frozen=True, slots=True)
class StructuredDigestItem:
    position: int
    article_id: UUID
    article_analysis_id: UUID
    event_group_id: UUID | None
    ranking_run_id: UUID
    title: str
    summary: str
    source_name: str
    published_at: datetime
    canonical_url: str
    score: Decimal
    content_schema_version: str = "1.0"
    content_hash: str = ""

    def __post_init__(self) -> None:
        if self.position < 1 or self.position > DIGEST_COUNT_MAX:
            raise ValueError(f"position must be 1..{DIGEST_COUNT_MAX}")
        if not self.title.strip() or len(self.title) > 500:
            raise ValueError("title must be 1..500 characters")
        if not self.summary.strip() or len(self.summary) > 1200:
            raise ValueError("summary must be 1..1200 characters")
        if not self.source_name.strip() or len(self.source_name) > 200:
            raise ValueError("source_name must be 1..200 characters")
        if not self.canonical_url or not self.canonical_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError("canonical_url must be a valid HTTP(S) URL")
        if len(self.canonical_url) > 2048:
            raise ValueError("canonical_url must be at most 2048 characters")
        if self.published_at.tzinfo is None or self.published_at.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        if not self.score.is_finite():
            raise ValueError("score must be finite")
        if self.content_hash:
            validate_hex_digest(self.content_hash, "content_hash")


@dataclass(frozen=True, slots=True)
class StructuredDigest:
    execution_id: UUID
    user_id: UUID
    language: str
    items: tuple[StructuredDigestItem, ...]

    def __post_init__(self) -> None:
        if len(self.items) > DIGEST_COUNT_MAX:
            raise ValueError(f"digest may contain at most {DIGEST_COUNT_MAX} items")
        if self.items:
            positions = [item.position for item in self.items]
            expected = list(range(1, len(self.items) + 1))
            if positions != expected:
                raise ValueError("items must have contiguous positions from 1")
            article_ids = [item.article_id for item in self.items]
            if len(set(article_ids)) != len(article_ids):
                raise ValueError("items must contain unique articles")


@dataclass(frozen=True, slots=True)
class DigestConfigurationSnapshot:
    user_id: UUID
    enabled: bool
    digest_count: int
    schedule_local_time: time
    timezone_name: str
    next_due_at: datetime | None
    schedule_revision: int
    last_success_execution_id: UUID | None = None
    last_success_at: datetime | None = None
    last_failure_execution_id: UUID | None = None
    last_failure_at: datetime | None = None
    last_failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class DigestExecutionSnapshot:
    id: UUID
    user_id: UUID
    occurrence_key: str
    status: ExecutionStatus
    attempt_count: int
    selected_count: int | None = None
    digest_count: int = 10
    language_code: str = "en"
    failure_code: str | None = None
    failure_class: FailureClass | None = None
    completed_at: datetime | None = None
    next_retry_at: datetime | None = None
    ranking_run_id: UUID | None = None
    profile_revision: int | None = None


@dataclass(frozen=True, slots=True)
class CandidateFilterResult:
    eligible_article_ids: tuple[UUID, ...]
    decisions: tuple[CandidateFilterDecision, ...]


@dataclass(frozen=True, slots=True)
class CandidateFilterDecision:
    article_id: UUID
    outcome: CandidateDecision
    evidence_history_id: UUID | None = None
    analysis_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class MaterialUpdateEvidence:
    delivery_history_id: UUID
    candidate_article_id: UUID
    candidate_analysis_id: UUID
    event_group_id: UUID
    policy_version: str
    basis: MaterialUpdateBasis
    outcome: MaterialUpdateOutcome
    prior_text_hash: str
    candidate_text_hash: str
    content_similarity: Decimal | None = None
    novelty_score: Decimal | None = None
    threshold_snapshot: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.policy_version.strip() or len(self.policy_version) > 100:
            raise ValueError("policy_version must be 1..100 characters")
        validate_hex_digest(self.prior_text_hash, "prior_text_hash")
        validate_hex_digest(self.candidate_text_hash, "candidate_text_hash")
        for name, value in (
            ("content_similarity", self.content_similarity),
            ("novelty_score", self.novelty_score),
        ):
            if value is not None and (not value.is_finite() or value < 0 or value > 1):
                raise ValueError(f"{name} must be between zero and one")
        if self.basis is MaterialUpdateBasis.INSUFFICIENT_EVIDENCE:
            if self.outcome is not MaterialUpdateOutcome.UNCHANGED:
                raise ValueError("insufficient_evidence must have unchanged outcome")
            if self.content_similarity is not None or self.novelty_score is not None:
                raise ValueError(
                    "insufficient_evidence cannot retain qualifying scores"
                )
        elif self.basis is MaterialUpdateBasis.CONTENT_DELTA:
            if self.outcome is not MaterialUpdateOutcome.MATERIAL_UPDATE:
                raise ValueError("content_delta must have material_update outcome")
            if self.content_similarity is None:
                raise ValueError("content_delta requires content_similarity")
        elif self.basis is MaterialUpdateBasis.ACCEPTED_NOVELTY:
            if self.outcome is not MaterialUpdateOutcome.MATERIAL_UPDATE:
                raise ValueError("accepted_novelty must have material_update outcome")
            if self.novelty_score is None:
                raise ValueError("accepted_novelty requires novelty_score")


@dataclass(frozen=True, slots=True)
class DeliveredArticleEvidence:
    history_id: UUID
    article_id: UUID
    article_analysis_id: UUID
    event_group_id: UUID
    publication_time: datetime
    normalized_text: str


@dataclass(frozen=True, slots=True)
class CandidateArticleEvidence:
    article_id: UUID
    article_analysis_id: UUID
    event_group_id: UUID
    publication_time: datetime
    normalized_text: str
    novelty_score: Decimal | None


@dataclass(frozen=True, slots=True)
class MaterialUpdateInput:
    delivered: DeliveredArticleEvidence
    candidate: CandidateArticleEvidence
    has_duplicate_or_review_veto: bool


@dataclass(frozen=True, slots=True)
class PersonalNewsSelection:
    ranking_run_id: UUID | None
    profile_revision: int
    ranking_at: datetime
    items: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class RenderedPart:
    ordinal: int
    first_item_position: int
    last_item_position: int
    content: str
    content_hash: str

    def __post_init__(self) -> None:
        if self.ordinal < 1:
            raise ValueError("ordinal must be positive")
        if self.first_item_position < 1:
            raise ValueError("first_item_position must be positive")
        if self.last_item_position < self.first_item_position:
            raise ValueError("last_item_position must not be below first")
        validate_hex_digest(self.content_hash, "content_hash")


@dataclass(frozen=True, slots=True)
class DeliveryAcknowledgement:
    provider_message_id: str
    accepted_at: datetime


@dataclass(frozen=True, slots=True)
class DeliveryPartSnapshot:
    execution_id: UUID
    ordinal: int
    status: DeliveryPartStatus
    content_hash: str
    first_item_position: int
    last_item_position: int
    provider_message_id: str | None = None
    attempt_count: int = 0


@dataclass(frozen=True, slots=True)
class AttemptClaim:
    attempt_id: UUID
    execution_id: UUID
    ordinal: int
    phase: AttemptPhase


@dataclass(frozen=True, slots=True)
class DeliveryPartClaim:
    execution_id: UUID
    ordinal: int
    content_hash: str
    first_item_position: int
    last_item_position: int


@dataclass(frozen=True, slots=True)
class DueCycleResult:
    claimed_count: int = 0
    processed_count: int = 0
    completed_count: int = 0
    failed_count: int = 0


@dataclass(frozen=True, slots=True)
class RetryCycleResult:
    retried_count: int = 0
    completed_count: int = 0
    failed_count: int = 0


@dataclass(frozen=True, slots=True)
class RetrySchedule:
    base_seconds: int
    max_seconds: int
    max_attempts: int

    def __post_init__(self) -> None:
        if self.base_seconds < 1:
            raise ValueError("base_seconds must be positive")
        if self.max_seconds < self.base_seconds:
            raise ValueError("max_seconds must not be below base_seconds")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")

    def next_retry_at(self, attempt_count: int, now: datetime) -> datetime:
        if attempt_count < 1:
            raise ValueError("attempt_count must be positive")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        delay = min(
            self.base_seconds * (2 ** (attempt_count - 1)),
            self.max_seconds,
        )
        return now + timedelta(seconds=delay)
