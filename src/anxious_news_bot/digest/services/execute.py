"""Digest execution orchestration with bounded retries and user isolation."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from uuid import UUID

from anxious_news_bot.digest.domain import (
    AttemptClaim,
    AttemptPhase,
    DigestExecutionSnapshot,
    DueCycleResult,
    DueOccurrence,
    ExecutionStatus,
    RetryCycleResult,
    RetrySchedule,
    StructuredDigest,
)
from anxious_news_bot.digest.errors import (
    AmbiguousDeliveryError,
    ExecutionBusyError,
    ExecutionTerminalError,
    PermanentDigestError,
    TransientDigestError,
)
from anxious_news_bot.digest.observability import log_digest_event
from anxious_news_bot.digest.ports import (
    CandidateFilter,
    Clock,
    DigestConfigurationRepository,
    DigestContentComposer,
    DigestDeliveryPort,
    DigestExecutionRepository,
)
from anxious_news_bot.digest.services.content import (
    merge_composed_content,
    prepare_composer_inputs,
)
from anxious_news_bot.digest.services.schedule import DigestScheduleService

LOGGER = logging.getLogger(__name__)


class DigestExecutionService:
    def __init__(
        self,
        config_repository: DigestConfigurationRepository,
        execution_repository: DigestExecutionRepository,
        personal_news_selector: object,
        composer: DigestContentComposer,
        delivery: DigestDeliveryPort,
        candidate_filter: CandidateFilter | None,
        clock: Clock,
        *,
        retry_schedule: RetrySchedule | None = None,
        user_concurrency: int = 5,
        candidate_limit: int = 100,
        renderer_version: str = "1.0",
        claim_batch_size: int = 100,
        max_claims_per_tick: int = 1000,
        claim_time_budget_seconds: int = 30,
        content_max_input_chars: int = 2000,
    ) -> None:
        if user_concurrency < 1:
            raise ValueError("user_concurrency must be positive")
        if candidate_limit < 20:
            raise ValueError("candidate_limit must be at least 20")
        if not renderer_version:
            raise ValueError("renderer_version must not be empty")
        if content_max_input_chars < 100:
            raise ValueError("content_max_input_chars must be at least 100")
        self._config_repo = config_repository
        self._exec_repo = execution_repository
        self._news_selector = personal_news_selector
        self._composer = composer
        self._delivery = delivery
        self._candidate_filter = candidate_filter
        self._clock = clock
        self._retry_schedule = retry_schedule or RetrySchedule(
            base_seconds=60,
            max_seconds=900,
            max_attempts=3,
        )
        self._user_concurrency = user_concurrency
        self._candidate_limit = candidate_limit
        self._renderer_version = renderer_version
        self._content_max_input_chars = content_max_input_chars
        self._schedule_service = DigestScheduleService(
            config_repository,
            clock,
            claim_batch_size=claim_batch_size,
            max_claims_per_tick=max_claims_per_tick,
            claim_time_budget_seconds=claim_time_budget_seconds,
        )

    async def execute(
        self,
        occurrence_or_id: DueOccurrence | UUID,
    ) -> DigestExecutionSnapshot:
        occurrence = await self._resolve_occurrence(occurrence_or_id)
        execution_id = occurrence.execution_id
        existing_digest = await self._exec_repo.load_digest(execution_id)
        phase = (
            AttemptPhase.DELIVER
            if existing_digest is not None and existing_digest.items
            else AttemptPhase.PREPARE
        )
        claim = await self._exec_repo.claim_attempt(
            execution_id,
            phase.value,
            self._clock.now(),
        )

        try:
            return await self._execute_claimed(
                occurrence,
                claim,
                existing_digest,
            )
        except (ExecutionTerminalError, ExecutionBusyError):
            raise
        except PermanentDigestError as exc:
            return await self._record_permanent(occurrence, claim, exc.code)
        except TransientDigestError as exc:
            return await self._record_transient(occurrence, claim, exc.code)
        except Exception:
            LOGGER.exception(
                "digest_execution_unexpected",
                extra={"digest": {"execution_id": str(execution_id)}},
            )
            return await self._record_transient(
                occurrence,
                claim,
                "unexpected_error",
            )

    async def _resolve_occurrence(
        self,
        occurrence_or_id: DueOccurrence | UUID,
    ) -> DueOccurrence:
        if isinstance(occurrence_or_id, DueOccurrence):
            return occurrence_or_id
        occurrence = await self._exec_repo.load_occurrence(occurrence_or_id)
        if occurrence is None:
            raise ExecutionTerminalError(
                "execution occurrence was not found",
                code="not_found",
            )
        return occurrence

    async def _execute_claimed(
        self,
        occurrence: DueOccurrence,
        claim: AttemptClaim,
        existing_digest: StructuredDigest | None,
    ) -> DigestExecutionSnapshot:
        execution_id = occurrence.execution_id
        digest = existing_digest
        if digest is None or not digest.items:
            selection = await self._select_news(occurrence)
            selected_items = selection["items"]
            await self._exec_repo.record_selection(
                execution_id,
                len(selected_items),
                selection["ranking_run_id"],
                selection["profile_revision"],
            )
            if not selected_items:
                snapshot = await self._exec_repo.complete_execution(
                    execution_id,
                    self._clock.now(),
                )
                await self._config_repo.record_success(
                    execution_id,
                    snapshot.completed_at or self._clock.now(),
                )
                log_digest_event(
                    "execution_completed_zero_items",
                    execution_id=execution_id,
                    user_id=occurrence.user_id,
                    status="completed",
                    fields={"selected_count": 0},
                )
                return snapshot

            composer_inputs = prepare_composer_inputs(
                selected_items,
                max_input_chars=self._content_max_input_chars,
            )
            composed = await self._composer.compose(
                execution_id,
                occurrence.language_code,
                composer_inputs,
            )
            validated = merge_composed_content(composed, selected_items)
            digest = await self._exec_repo.record_items(
                execution_id,
                validated,
                self._clock.now(),
            )

        unknown_snapshot = await self._deliver(occurrence, digest)
        if unknown_snapshot is not None:
            return unknown_snapshot

        completed_at = self._clock.now()
        snapshot = await self._exec_repo.complete_execution(
            execution_id,
            completed_at,
        )
        await self._config_repo.record_success(execution_id, completed_at)
        log_digest_event(
            "execution_completed",
            execution_id=execution_id,
            user_id=occurrence.user_id,
            status="completed",
            fields={"selected_count": len(digest.items)},
        )
        return snapshot

    async def _select_news(self, occurrence: DueOccurrence) -> dict:
        request_id = f"digest-execution:{occurrence.execution_id}"
        result = await self._news_selector.select_for_user(
            occurrence.user_id,
            request_id,
            occurrence.digest_count,
            self._candidate_limit,
            self._candidate_filter,
        )
        if isinstance(result, dict):
            items = list(result.get("items", ()))[: occurrence.digest_count]
            ranking_run_id = result.get("ranking_run_id")
            profile_revision = result.get("profile_revision")
            if items and ranking_run_id is None:
                # Test fakes may put the run ID on every item.
                ranking_run_id = items[0].get("ranking_run_id")
            return {
                "items": items,
                "ranking_run_id": ranking_run_id,
                "profile_revision": profile_revision,
            }

        ranking_run_id = result.ranking_run_id
        if result.items and ranking_run_id is None:
            raise PermanentDigestError(
                "ranking metadata is incomplete",
                code="missing_ranking_run",
            )
        ranked_items: list[dict] = []
        for item in result.items[: occurrence.digest_count]:
            article = item.article
            if article.article_analysis_id is None:
                raise PermanentDigestError(
                    "accepted article analysis is missing",
                    code="missing_article_analysis",
                )
            ranked_items.append(
                {
                    "position": item.position,
                    "article_id": article.article_id,
                    "article_analysis_id": article.article_analysis_id,
                    "event_group_id": article.event_group_id,
                    "ranking_run_id": ranking_run_id,
                    "title": article.title,
                    "summary": article.grounded_summary,
                    "normalized_text": article.normalized_text or "",
                    "source_name": article.source_name,
                    "published_at": article.published_at,
                    "canonical_url": article.canonical_url,
                    "score": item.score,
                }
            )
        return {
            "items": ranked_items,
            "ranking_run_id": ranking_run_id,
            "profile_revision": result.profile_revision,
        }

    async def _deliver(
        self,
        occurrence: DueOccurrence,
        digest: StructuredDigest,
    ) -> DigestExecutionSnapshot | None:
        parts = self._delivery.render(digest, self._renderer_version)
        if not parts:
            return None
        await self._exec_repo.prepare_delivery_parts(
            occurrence.execution_id,
            parts,
        )
        for part in parts:
            claim = await self._exec_repo.claim_delivery_part(
                occurrence.execution_id,
                part.ordinal,
                self._clock.now(),
            )
            if claim is None:
                snapshot = await self._exec_repo.get_execution(occurrence.execution_id)
                if (
                    snapshot is not None
                    and snapshot.status is ExecutionStatus.DELIVERY_UNKNOWN
                ):
                    return snapshot
                continue
            try:
                acknowledgement = await self._delivery.send(
                    occurrence.telegram_user_id,
                    part,
                )
            except AmbiguousDeliveryError as exc:
                snapshot = await self._exec_repo.record_delivery_unknown(
                    claim,
                    exc.code,
                    self._clock.now(),
                )
                log_digest_event(
                    "execution_ambiguous",
                    execution_id=occurrence.execution_id,
                    user_id=occurrence.user_id,
                    status="delivery_unknown",
                    reason_code=exc.code,
                )
                return snapshot
            await self._exec_repo.acknowledge_delivery_part(
                claim,
                acknowledgement.provider_message_id,
                acknowledgement.accepted_at,
            )
        return None

    async def _record_transient(
        self,
        occurrence: DueOccurrence,
        claim: AttemptClaim,
        reason_code: str,
    ) -> DigestExecutionSnapshot:
        now = self._clock.now()
        if claim.ordinal >= self._retry_schedule.max_attempts:
            return await self._record_permanent(
                occurrence,
                claim,
                f"exhausted_{reason_code}"[:100],
            )
        next_retry_at = self._retry_schedule.next_retry_at(claim.ordinal, now)
        snapshot = await self._exec_repo.record_transient_failure(
            claim,
            reason_code,
            now,
            next_retry_at,
        )
        log_digest_event(
            "execution_transient_failure",
            execution_id=occurrence.execution_id,
            user_id=occurrence.user_id,
            status="retrying",
            reason_code=reason_code,
            fields={"attempt": claim.ordinal},
        )
        return snapshot

    async def _record_permanent(
        self,
        occurrence: DueOccurrence,
        claim: AttemptClaim,
        reason_code: str,
    ) -> DigestExecutionSnapshot:
        failed_at = self._clock.now()
        snapshot = await self._exec_repo.record_permanent_failure(
            claim,
            reason_code,
            failed_at,
        )
        await self._config_repo.record_failure(
            occurrence.execution_id,
            reason_code,
            failed_at,
        )
        log_digest_event(
            "execution_permanent_failure",
            execution_id=occurrence.execution_id,
            user_id=occurrence.user_id,
            status="failed",
            reason_code=reason_code,
            fields={"attempt": claim.ordinal},
        )
        return snapshot

    async def run_due_cycle(self, now: datetime) -> DueCycleResult:
        occurrences = await self._schedule_service.claim_due_batch(now)
        if not occurrences:
            return DueCycleResult()
        completed, failed = await self._process_occurrences(occurrences)
        return DueCycleResult(
            claimed_count=len(occurrences),
            processed_count=len(occurrences),
            completed_count=completed,
            failed_count=failed,
        )

    async def retry_due(self, now: datetime) -> RetryCycleResult:
        execution_ids = await self._exec_repo.claim_retries(
            now,
            batch_size=min(100, self._candidate_limit),
        )
        if not execution_ids:
            return RetryCycleResult()
        occurrences: list[DueOccurrence] = []
        missing = 0
        for execution_id in execution_ids:
            occurrence = await self._exec_repo.load_occurrence(execution_id)
            if occurrence is None:
                missing += 1
            else:
                occurrences.append(occurrence)
        completed, failed = await self._process_occurrences(tuple(occurrences))
        return RetryCycleResult(
            retried_count=len(execution_ids),
            completed_count=completed,
            failed_count=failed + missing,
        )

    async def _process_occurrences(
        self,
        occurrences: tuple[DueOccurrence, ...],
    ) -> tuple[int, int]:
        semaphore = asyncio.Semaphore(self._user_concurrency)

        async def process_one(occurrence: DueOccurrence) -> bool:
            async with semaphore:
                try:
                    snapshot = await self.execute(occurrence)
                    return snapshot.status is ExecutionStatus.COMPLETED
                except Exception:
                    LOGGER.exception(
                        "execution_failed_user_isolated",
                        extra={
                            "digest": {"execution_id": str(occurrence.execution_id)}
                        },
                    )
                    return False

        outcomes = await asyncio.gather(
            *(process_one(occurrence) for occurrence in occurrences)
        )
        completed = sum(outcomes)
        return completed, len(outcomes) - completed
