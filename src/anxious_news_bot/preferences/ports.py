from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from anxious_news_bot.preferences.domain import (
    ProfileSnapshot,
    QuestionnaireContext,
    TuneState,
)
from anxious_news_bot.preferences.schemas import (
    CreateChangeSchema,
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

    async def duplicate_candidates(
        self,
        user_id: UUID,
        semantic_key: str,
        name: str,
        *,
        limit: int = 20,
    ) -> ProfileSnapshot: ...
