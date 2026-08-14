"""Reusable digest test fixtures: clock, config, execution, article, composer, delivery fakes."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, time
from decimal import Decimal
from uuid import UUID, uuid4

from anxious_news_bot.digest.domain import (
    AttemptClaim,
    AttemptPhase,
    CandidateDecision,
    CandidateFilterDecision,
    CandidateFilterResult,
    DeliveryAcknowledgement,
    DeliveryPartClaim,
    DeliveryPartSnapshot,
    DeliveryPartStatus,
    DigestConfigurationSnapshot,
    DigestExecutionSnapshot,
    DueOccurrence,
    ExecutionStatus,
    RenderedPart,
    StructuredDigest,
    StructuredDigestItem,
)


class FixedClock:
    def __init__(self, value: datetime | None = None) -> None:
        self.value = value or datetime(2026, 1, 15, 9, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        from datetime import timedelta

        self.value += timedelta(seconds=seconds)


class FakeDigestConfigurationRepository:
    def __init__(self) -> None:
        self.configurations: dict[UUID, DigestConfigurationSnapshot] = {}
        self.configurations_by_telegram_user: dict[
            int, DigestConfigurationSnapshot
        ] = {}
        self.due_queue: list[DueOccurrence] = []
        self.success_calls: list[tuple[UUID, datetime]] = []
        self.failure_calls: list[tuple[UUID, str, datetime]] = []

    async def set_count(
        self,
        telegram_user_id: int,
        language_hint: str | None,
        count: int,
        changed_at: datetime,
    ) -> DigestConfigurationSnapshot:
        user_id = uuid4()
        snap = DigestConfigurationSnapshot(
            user_id=user_id,
            enabled=True,
            digest_count=count,
            schedule_local_time=time(9, 0),
            timezone_name="UTC",
            next_due_at=None,
            schedule_revision=0,
        )
        self.configurations[user_id] = snap
        self.configurations_by_telegram_user[telegram_user_id] = snap
        return snap

    async def get(self, user_id: UUID) -> DigestConfigurationSnapshot | None:
        return self.configurations.get(user_id)

    async def get_current(
        self,
        telegram_user_id: int,
        language_hint: str | None,
    ) -> DigestConfigurationSnapshot:
        del language_hint
        existing = self.configurations_by_telegram_user.get(telegram_user_id)
        if existing is not None:
            return existing
        return await self.set_count(
            telegram_user_id=telegram_user_id,
            language_hint=None,
            count=10,
            changed_at=datetime(2026, 1, 15, 9, 0, tzinfo=UTC),
        )

    async def claim_due(
        self, now: datetime, batch_size: int
    ) -> tuple[DueOccurrence, ...]:
        batch = self.due_queue[:batch_size]
        self.due_queue = self.due_queue[batch_size:]
        return tuple(batch)

    async def record_success(self, execution_id: UUID, completed_at: datetime) -> None:
        self.success_calls.append((execution_id, completed_at))

    async def record_failure(
        self, execution_id: UUID, failure_code: str, completed_at: datetime
    ) -> None:
        self.failure_calls.append((execution_id, failure_code, completed_at))


class FakeDigestExecutionRepository:
    def __init__(self) -> None:
        self.executions: dict[UUID, DigestExecutionSnapshot] = {}
        self.digests: dict[UUID, StructuredDigest] = {}
        self.parts: dict[UUID, list[DeliveryPartSnapshot]] = {}
        self.history_calls: list[tuple] = []
        self.attempt_count = 0
        self.last_attempt: AttemptClaim | None = None
        self.transient_failures: list[tuple] = []
        self.permanent_failures: list[tuple] = []
        self.occurrences: dict[UUID, DueOccurrence] = {}
        self.retry_ids: tuple[UUID, ...] = ()

    async def claim_attempt(
        self, execution_id: UUID, phase: str, now: datetime
    ) -> AttemptClaim:
        self.attempt_count += 1
        claim = AttemptClaim(
            attempt_id=uuid4(),
            execution_id=execution_id,
            ordinal=self.attempt_count,
            phase=AttemptPhase(phase),
        )
        self.last_attempt = claim
        return claim

    async def load_occurrence(self, execution_id: UUID) -> DueOccurrence | None:
        return self.occurrences.get(execution_id)

    async def record_selection(
        self,
        execution_id: UUID,
        selected_count: int,
        ranking_run_id: UUID | None,
        profile_revision: int | None,
    ) -> None:
        pass

    async def record_items(
        self,
        execution_id: UUID,
        items: Sequence[StructuredDigestItem],
        now: datetime,
    ) -> StructuredDigest:
        digest = StructuredDigest(
            execution_id=execution_id,
            user_id=uuid4(),
            language="en",
            items=tuple(items),
        )
        self.digests[execution_id] = digest
        return digest

    async def load_digest(self, execution_id: UUID) -> StructuredDigest | None:
        return self.digests.get(execution_id)

    async def prepare_delivery_parts(
        self, execution_id: UUID, parts: Sequence[RenderedPart]
    ) -> tuple[DeliveryPartSnapshot, ...]:
        result = []
        for p in parts:
            snap = DeliveryPartSnapshot(
                execution_id=execution_id,
                ordinal=p.ordinal,
                status=DeliveryPartStatus.PENDING,
                content_hash=p.content_hash,
                first_item_position=p.first_item_position,
                last_item_position=p.last_item_position,
            )
            result.append(snap)
        self.parts[execution_id] = result
        return tuple(result)

    async def claim_delivery_part(
        self, execution_id: UUID, ordinal: int, now: datetime
    ) -> DeliveryPartClaim | None:
        return DeliveryPartClaim(
            execution_id=execution_id,
            ordinal=ordinal,
            content_hash="a" * 64,
            first_item_position=1,
            last_item_position=1,
        )

    async def acknowledge_delivery_part(
        self,
        claim: DeliveryPartClaim,
        provider_message_id: str,
        sent_at: datetime,
    ) -> DeliveryPartSnapshot:
        return DeliveryPartSnapshot(
            execution_id=claim.execution_id,
            ordinal=claim.ordinal,
            status=DeliveryPartStatus.SENT,
            content_hash=claim.content_hash,
            first_item_position=claim.first_item_position,
            last_item_position=claim.last_item_position,
            provider_message_id=provider_message_id,
        )

    async def record_delivery_unknown(
        self, claim: DeliveryPartClaim, reason_code: str, occurred_at: datetime
    ) -> None:
        pass

    async def record_transient_failure(
        self,
        attempt: AttemptClaim,
        reason_code: str,
        failed_at: datetime,
        next_retry_at: datetime,
    ) -> DigestExecutionSnapshot:
        self.transient_failures.append((attempt, reason_code, failed_at, next_retry_at))
        return DigestExecutionSnapshot(
            id=attempt.execution_id,
            user_id=uuid4(),
            occurrence_key="test",
            status=ExecutionStatus.RETRYING,
            attempt_count=1,
        )

    async def record_permanent_failure(
        self,
        attempt: AttemptClaim,
        reason_code: str,
        failed_at: datetime,
    ) -> DigestExecutionSnapshot:
        self.permanent_failures.append((attempt, reason_code, failed_at))
        return DigestExecutionSnapshot(
            id=attempt.execution_id,
            user_id=uuid4(),
            occurrence_key="test",
            status=ExecutionStatus.FAILED,
            attempt_count=1,
        )

    async def claim_retries(self, now: datetime, batch_size: int) -> tuple[UUID, ...]:
        result = self.retry_ids[:batch_size]
        self.retry_ids = self.retry_ids[batch_size:]
        return result

    async def get_execution(self, execution_id: UUID) -> DigestExecutionSnapshot | None:
        return self.executions.get(execution_id)

    async def get_pending_parts(
        self, execution_id: UUID
    ) -> tuple[DeliveryPartSnapshot, ...]:
        return tuple(self.parts.get(execution_id, []))

    async def record_history(
        self,
        execution_id: UUID,
        user_id: UUID,
        items: Sequence[StructuredDigestItem],
        outcome: str,
        delivered_at: datetime,
    ) -> None:
        self.history_calls.append((execution_id, user_id, items, outcome, delivered_at))

    async def complete_execution(
        self, execution_id: UUID, completed_at: datetime
    ) -> DigestExecutionSnapshot:
        return DigestExecutionSnapshot(
            id=execution_id,
            user_id=uuid4(),
            occurrence_key="test",
            status=ExecutionStatus.COMPLETED,
            attempt_count=1,
            completed_at=completed_at,
        )

    async def get_user_history_article_ids(self, user_id: UUID) -> set[UUID]:
        return set()


class FakeComposer:
    def __init__(
        self,
        items: list[dict] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._items = items
        self._error = error
        self.calls: list[tuple] = []

    async def compose(
        self, execution_id: UUID, language: str, ranked_items: Sequence[dict]
    ) -> tuple[dict, ...]:
        self.calls.append((execution_id, language, ranked_items))
        if self._error is not None:
            raise self._error
        if self._items is not None:
            return tuple(self._items)
        return tuple(
            {
                "index": item["index"],
                "title": f"Title {item['index']}",
                "summary": f"Summary {item['index']}",
            }
            for item in ranked_items
        )


class FakeDelivery:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.sent_parts: list[RenderedPart] = []

    def render(
        self, digest: StructuredDigest, renderer_version: str
    ) -> tuple[RenderedPart, ...]:
        from anxious_news_bot.telegram.digest import render_digest

        return render_digest(digest, renderer_version)

    async def send(
        self, telegram_user_id: int, rendered_part: RenderedPart
    ) -> DeliveryAcknowledgement:
        if self._error is not None:
            raise self._error
        self.sent_parts.append(rendered_part)
        return DeliveryAcknowledgement(
            provider_message_id=f"msg_{rendered_part.ordinal}",
            accepted_at=datetime.now(UTC),
        )


class FakeCandidateFilter:
    async def filter(
        self, user_id: UUID, candidate_ids: Sequence[UUID], ranking_at: datetime
    ) -> CandidateFilterResult:
        return CandidateFilterResult(
            eligible_article_ids=tuple(candidate_ids),
            decisions=tuple(
                CandidateFilterDecision(
                    article_id=aid, outcome=CandidateDecision.ELIGIBLE
                )
                for aid in candidate_ids
            ),
        )


class FakeNewsSelector:
    def __init__(self, items: list[dict] | None = None) -> None:
        self._items = items or []
        self.calls: list[tuple] = []

    async def select_for_user(
        self, user_id, request_id, count, candidate_limit, candidate_filter
    ) -> dict:
        self.calls.append(
            (user_id, request_id, count, candidate_limit, candidate_filter)
        )
        return {
            "items": self._items[:count],
            "ranking_run_id": uuid4(),
            "profile_revision": 1,
        }


def make_test_occurrence(
    *,
    user_id: UUID | None = None,
    execution_id: UUID | None = None,
    digest_count: int = 10,
    language_code: str = "en",
) -> DueOccurrence:
    return DueOccurrence(
        execution_id=execution_id or uuid4(),
        user_id=user_id or uuid4(),
        telegram_user_id=123456,
        occurrence_key="2026-01-15/09:00/UTC",
        scheduled_for=datetime(2026, 1, 15, 9, 0, tzinfo=UTC),
        local_date=datetime(2026, 1, 15).date(),
        local_time=time(9, 0),
        timezone_name="UTC",
        schedule_revision=0,
        digest_count=digest_count,
        language_code=language_code,
    )


def make_ranked_items(count: int = 3) -> list[dict]:
    items = []
    for i in range(1, count + 1):
        items.append(
            {
                "position": i,
                "article_id": uuid4(),
                "article_analysis_id": uuid4(),
                "event_group_id": None,
                "ranking_run_id": uuid4(),
                "title": f"Article {i}",
                "summary": f"Summary of article {i}",
                "normalized_text": f"Normalized text of article {i} " * 20,
                "source_name": f"Source {i}",
                "published_at": datetime(2026, 1, 14, 12, 0, tzinfo=UTC),
                "canonical_url": f"https://example.com/article-{i}",
                "score": Decimal("0.85000000"),
            }
        )
    return items
