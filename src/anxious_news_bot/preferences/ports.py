from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from anxious_news_bot.preferences.domain import (
    ExplicitRequestClaim,
    ProfileSnapshot,
    QuestionnaireContext,
    SpecifyState,
    TuneState,
)
from anxious_news_bot.preferences.schemas import (
    CreateChangeSchema,
    ExplicitPreferenceChangesSchema,
    PreferenceChangesSchema,
    QuestionnaireGenerationSchema,
)


@runtime_checkable
class QuestionnaireGenerator(Protocol):
    async def generate(self, context: QuestionnaireContext) -> Mapping[str, Any]: ...


@runtime_checkable
class PreferenceInterpreter(Protocol):
    async def propose(
        self,
        profile: ProfileSnapshot,
        questionnaire_id: UUID,
        answers: Sequence[tuple[str, str]],
    ) -> Mapping[str, Any]: ...


@runtime_checkable
class ExplicitPreferenceInterpreter(Protocol):
    async def interpret(
        self,
        request_id: UUID,
        statement: str,
        profile_snapshot: ProfileSnapshot,
        relevant_history: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]: ...


@runtime_checkable
class PreferenceEquivalenceClassifier(Protocol):
    async def classify(
        self,
        proposal: CreateChangeSchema,
        candidates: ProfileSnapshot,
    ) -> Mapping[str, Any]: ...


@runtime_checkable
class QuestionnaireQualityValidator(Protocol):
    def validate(
        self,
        candidate: QuestionnaireGenerationSchema,
        prior_questions: Sequence[str],
    ) -> None: ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class TokenFactory(Protocol):
    def create(self) -> tuple[str, str]: ...


@runtime_checkable
class PreferenceRepositoryPort(Protocol):
    async def start_or_resume(
        self, telegram_user_id: int, language_code: str | None
    ) -> tuple[QuestionnaireContext, TuneState]: ...

    async def store_generated(
        self,
        questionnaire_id: UUID,
        questionnaire: QuestionnaireGenerationSchema,
        token_hashes: Sequence[Sequence[str]],
    ) -> TuneState: ...

    async def record_answer(
        self,
        telegram_user_id: int,
        callback_token: str,
        answered_at: datetime,
    ) -> TuneState: ...

    async def load_interpretation_input(
        self, questionnaire_id: UUID
    ) -> tuple[ProfileSnapshot, Sequence[tuple[str, str]]]: ...

    async def apply_changes(
        self,
        questionnaire_id: UUID,
        proposal: PreferenceChangesSchema,
        applied_at: datetime,
    ) -> TuneState: ...

    async def fail(
        self, questionnaire_id: UUID, error_code: str, failed_at: datetime
    ) -> TuneState: ...

    async def claim_explicit_request(
        self,
        telegram_user_id: int,
        telegram_update_id: int,
        statement: str,
        language_code: str | None,
        claimed_at: datetime,
    ) -> ExplicitRequestClaim: ...

    async def load_explicit_context(
        self, request_id: UUID
    ) -> tuple[ProfileSnapshot, Sequence[Mapping[str, Any]]]: ...

    async def apply_explicit_changes(
        self,
        request_id: UUID,
        proposal: ExplicitPreferenceChangesSchema,
        applied_at: datetime,
    ) -> SpecifyState: ...

    async def complete_no_change(
        self,
        request_id: UUID,
        proposal_hash: str,
        completed_at: datetime,
    ) -> SpecifyState: ...

    async def fail_explicit_request(
        self,
        request_id: UUID,
        error_code: str,
        failed_at: datetime,
    ) -> SpecifyState: ...

    async def duplicate_candidates(
        self,
        user_id: UUID,
        semantic_key: str,
        name: str,
        *,
        limit: int = 20,
    ) -> ProfileSnapshot: ...
