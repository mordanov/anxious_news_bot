from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID


class PreferenceOrigin(StrEnum):
    QUESTIONNAIRE = "questionnaire"
    EXPLICIT = "explicit"
    INFERENCE = "inference"
    SYSTEM = "system"


class SupportedLanguage(StrEnum):
    RUSSIAN = "ru"
    ENGLISH = "en"
    SPANISH = "es"


def normalize_language_code(value: str | None) -> SupportedLanguage:
    primary = (value or "").strip().lower().replace("_", "-").split("-", 1)[0]
    if primary == SupportedLanguage.RUSSIAN:
        return SupportedLanguage.RUSSIAN
    if primary == SupportedLanguage.SPANISH:
        return SupportedLanguage.SPANISH
    return SupportedLanguage.ENGLISH


class QuestionnaireStatus(StrEnum):
    GENERATING = "generating"
    ANSWERING = "answering"
    ANSWERS_COMPLETE = "answers_complete"
    INTERPRETING = "interpreting"
    APPLYING = "applying"
    APPLIED = "applied"
    FAILED = "failed"


class PreferenceAction(StrEnum):
    CREATE = "create"
    ADJUST = "adjust"
    REFINE = "refine"
    DEACTIVATE = "deactivate"
    REACTIVATE = "reactivate"


class ExplicitRequestStatus(StrEnum):
    RECEIVED = "received"
    INTERPRETING = "interpreting"
    VALIDATED = "validated"
    APPLYING = "applying"
    STALE = "stale"
    APPLIED = "applied"
    FAILED = "failed"


class UpdateBatchStatus(StrEnum):
    VALIDATED = "validated"
    APPLIED = "applied"
    STALE = "stale"
    REJECTED = "rejected"


class TuneStateKind(StrEnum):
    GENERATING = "generating"
    QUESTION = "question"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SpecifyStateKind(StrEnum):
    PROCESSING = "processing"
    APPLIED = "applied"
    NO_CHANGE = "no_change"
    INVALID = "invalid"
    STALE_RETRY = "stale_retry"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ApplicationUser:
    id: UUID
    telegram_user_id: int
    language_code: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PreferenceParameter:
    id: UUID
    user_id: UUID
    semantic_key: str
    name: str
    description: str
    evaluation_instructions: str
    weight: Decimal
    origin: PreferenceOrigin
    active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProfileSnapshot:
    user_id: UUID
    revision: int
    parameters: tuple[PreferenceParameter, ...]


@dataclass(frozen=True, slots=True)
class PriorAnswer:
    question: str
    selected_option: str
    dimension_key: str


@dataclass(frozen=True, slots=True)
class QuestionDimensionContext:
    dimension_key: str
    exposure_count: int
    last_exposed_at: datetime


@dataclass(frozen=True, slots=True)
class QuestionnaireContext:
    profile: ProfileSnapshot
    language_code: str | None
    prior_answers: tuple[PriorAnswer, ...] = ()
    dimension_context: tuple[QuestionDimensionContext, ...] = ()


@dataclass(frozen=True, slots=True)
class TuneOption:
    label: str
    callback_token: str


@dataclass(frozen=True, slots=True)
class TuneState:
    kind: TuneStateKind
    questionnaire_id: UUID | None = None
    ordinal: int | None = None
    question: str | None = None
    options: tuple[TuneOption, ...] = ()
    message: str | None = None


@dataclass(frozen=True, slots=True)
class SpecifyState:
    kind: SpecifyStateKind
    request_id: UUID | None = None
    action: PreferenceAction | None = None
    parameter_name: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class ExplicitRequestClaim:
    request_id: UUID
    replay_state: SpecifyState | None = None


@dataclass(frozen=True, slots=True)
class RetentionResult:
    questionnaire_details_removed: int = 0
    failed_questionnaires_removed: int = 0
    full_history_rows_removed: int = 0
    compact_audit_rows_preserved: int = 0
    already_running: bool = False
