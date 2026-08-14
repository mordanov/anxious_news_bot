"""Digest application protocols."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from anxious_news_bot.digest.domain import (
    AttemptClaim,
    CandidateFilterResult,
    DeliveryAcknowledgement,
    DeliveryPartClaim,
    DeliveryPartSnapshot,
    DigestConfigurationSnapshot,
    DigestExecutionSnapshot,
    DueOccurrence,
    RenderedPart,
    StructuredDigest,
    StructuredDigestItem,
)


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class DigestConfigurationRepository(Protocol):
    async def set_count(
        self,
        telegram_user_id: int,
        language_hint: str | None,
        count: int,
        changed_at: datetime,
    ) -> DigestConfigurationSnapshot: ...

    async def get(self, user_id: UUID) -> DigestConfigurationSnapshot | None: ...

    async def claim_due(
        self, now: datetime, batch_size: int
    ) -> tuple[DueOccurrence, ...]: ...

    async def record_success(
        self, execution_id: UUID, completed_at: datetime
    ) -> None: ...

    async def record_failure(
        self, execution_id: UUID, failure_code: str, completed_at: datetime
    ) -> None: ...


@runtime_checkable
class DigestExecutionRepository(Protocol):
    async def claim_attempt(
        self, execution_id: UUID, phase: str, now: datetime
    ) -> AttemptClaim: ...

    async def load_occurrence(self, execution_id: UUID) -> DueOccurrence | None: ...

    async def record_selection(
        self,
        execution_id: UUID,
        selected_count: int,
        ranking_run_id: UUID | None,
        profile_revision: int | None,
    ) -> None: ...

    async def record_items(
        self,
        execution_id: UUID,
        items: Sequence[StructuredDigestItem],
        now: datetime,
    ) -> StructuredDigest: ...

    async def load_digest(self, execution_id: UUID) -> StructuredDigest | None: ...

    async def prepare_delivery_parts(
        self, execution_id: UUID, parts: Sequence[RenderedPart]
    ) -> tuple[DeliveryPartSnapshot, ...]: ...

    async def claim_delivery_part(
        self, execution_id: UUID, ordinal: int, now: datetime
    ) -> DeliveryPartClaim | None: ...

    async def acknowledge_delivery_part(
        self,
        claim: DeliveryPartClaim,
        provider_message_id: str,
        sent_at: datetime,
    ) -> DeliveryPartSnapshot: ...

    async def record_delivery_unknown(
        self, claim: DeliveryPartClaim, reason_code: str, occurred_at: datetime
    ) -> DigestExecutionSnapshot: ...

    async def record_transient_failure(
        self,
        attempt: AttemptClaim,
        reason_code: str,
        failed_at: datetime,
        next_retry_at: datetime,
    ) -> DigestExecutionSnapshot: ...

    async def record_permanent_failure(
        self,
        attempt: AttemptClaim,
        reason_code: str,
        failed_at: datetime,
    ) -> DigestExecutionSnapshot: ...

    async def claim_retries(
        self, now: datetime, batch_size: int
    ) -> tuple[UUID, ...]: ...

    async def get_execution(
        self, execution_id: UUID
    ) -> DigestExecutionSnapshot | None: ...

    async def get_pending_parts(
        self, execution_id: UUID
    ) -> tuple[DeliveryPartSnapshot, ...]: ...

    async def record_history(
        self,
        execution_id: UUID,
        user_id: UUID,
        items: Sequence[StructuredDigestItem],
        outcome: str,
        delivered_at: datetime,
    ) -> None: ...

    async def complete_execution(
        self, execution_id: UUID, completed_at: datetime
    ) -> DigestExecutionSnapshot: ...


@runtime_checkable
class CandidateFilter(Protocol):
    async def filter(
        self, user_id: UUID, candidate_ids: Sequence[UUID], ranking_at: datetime
    ) -> CandidateFilterResult: ...


@runtime_checkable
class DigestContentComposer(Protocol):
    async def compose(
        self, execution_id: UUID, language: str, ranked_items: Sequence[dict]
    ) -> tuple[dict, ...]: ...


@runtime_checkable
class DigestDeliveryPort(Protocol):
    def render(
        self, digest: StructuredDigest, renderer_version: str
    ) -> tuple[RenderedPart, ...]: ...

    async def send(
        self, telegram_user_id: int, rendered_part: RenderedPart
    ) -> DeliveryAcknowledgement: ...
