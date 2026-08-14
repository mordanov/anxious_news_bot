"""Digest configuration and execution repositories."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from anxious_news_bot.digest.domain import (
    TERMINAL_STATUSES,
    AttemptClaim,
    AttemptPhase,
    AttemptStatus,
    CandidateArticleEvidence,
    DeliveredArticleEvidence,
    DeliveryPartClaim,
    DeliveryPartSnapshot,
    DeliveryPartStatus,
    DigestConfigurationSnapshot,
    DigestExecutionSnapshot,
    DueOccurrence,
    ExecutionStatus,
    FailureClass,
    HistoryOutcome,
    MaterialUpdateBasis,
    MaterialUpdateEvidence,
    MaterialUpdateInput,
    MaterialUpdateOutcome,
    RenderedPart,
    StructuredDigest,
    StructuredDigestItem,
    canonical_occurrence_key,
    compute_next_due,
    content_hash,
    validate_digest_count,
    validate_iana_timezone,
    validate_reason_code,
)
from anxious_news_bot.digest.errors import (
    ExecutionBusyError,
    ExecutionTerminalError,
    StaleAttemptError,
)
from anxious_news_bot.digest.infrastructure.models import (
    DigestConfiguration,
    DigestDeliveryHistory,
    DigestDeliveryPart,
    DigestExecution,
    DigestExecutionAttempt,
    DigestItem,
    DigestMaterialUpdateEvidence,
)
from anxious_news_bot.infrastructure.database import Database
from anxious_news_bot.infrastructure.users import ApplicationUserProvisioner
from anxious_news_bot.news.domain import AnalysisStatus, DecisionOutcome
from anxious_news_bot.news.infrastructure.models import (
    ArticleAnalysis,
    DeduplicationDecision,
    NormalizedArticle,
)
from anxious_news_bot.preferences.infrastructure.models import ApplicationUser


class SQLAlchemyDigestRepository:
    def __init__(
        self,
        database: Database,
        *,
        user_provisioner: ApplicationUserProvisioner | None = None,
        retry_claim_lease_seconds: int = 300,
        sending_stale_seconds: int = 300,
    ) -> None:
        if retry_claim_lease_seconds < 1 or sending_stale_seconds < 1:
            raise ValueError("digest claim lease values must be positive")
        self._database = database
        self._user_provisioner = user_provisioner or ApplicationUserProvisioner()
        self._retry_claim_lease_seconds = retry_claim_lease_seconds
        self._sending_stale_seconds = sending_stale_seconds

    # -- Configuration operations --

    async def set_count(
        self,
        telegram_user_id: int,
        language_hint: str | None,
        count: int,
        changed_at: datetime,
    ) -> DigestConfigurationSnapshot:
        validate_digest_count(count)
        async with self._database.session() as session:
            provisioned = await self._user_provisioner.ensure(
                session,
                telegram_user_id=telegram_user_id,
                language_hint=language_hint,
            )
            config = provisioned.digest_configuration
            config.digest_count = count
            config.updated_at = changed_at
            await session.flush()
            return self._config_snapshot(config)

    async def get(self, user_id: UUID) -> DigestConfigurationSnapshot | None:
        async with self._database.session() as session:
            config = await session.get(DigestConfiguration, user_id)
            if config is None:
                return None
            return self._config_snapshot(config)

    async def claim_due(
        self, now: datetime, batch_size: int
    ) -> tuple[DueOccurrence, ...]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        results: list[DueOccurrence] = []
        async with self._database.session() as session:
            rows = (
                await session.execute(
                    select(DigestConfiguration, ApplicationUser)
                    .join(
                        ApplicationUser,
                        ApplicationUser.id == DigestConfiguration.user_id,
                    )
                    .where(
                        DigestConfiguration.enabled.is_(True),
                        DigestConfiguration.next_due_at.is_not(None),
                        DigestConfiguration.next_due_at <= now,
                    )
                    .order_by(DigestConfiguration.next_due_at)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()

            for config, user in rows:
                if config.next_due_at is None:
                    continue
                tz = validate_iana_timezone(config.timezone_name)
                due_at = config.next_due_at
                local_date = due_at.astimezone(tz).date()
                local_time_val = config.schedule_local_time
                occ_key = canonical_occurrence_key(
                    local_date, local_time_val, config.timezone_name
                )

                from anxious_news_bot.digest.domain import resolve_occurrence

                scheduled_for = resolve_occurrence(local_date, local_time_val, tz)

                execution_id = uuid4()
                ranking_request_id = f"digest-execution:{execution_id}"

                # Try insert execution - skip on conflict (already claimed)
                result = await session.execute(
                    insert(DigestExecution)
                    .values(
                        id=execution_id,
                        user_id=config.user_id,
                        occurrence_key=occ_key,
                        scheduled_for=scheduled_for,
                        local_date=local_date,
                        local_time=local_time_val,
                        timezone_name=config.timezone_name,
                        schedule_revision=config.schedule_revision,
                        digest_count=config.digest_count,
                        language_code=user.language_code or "en",
                        ranking_request_id=ranking_request_id,
                        status=ExecutionStatus.SCHEDULED,
                        attempt_count=0,
                    )
                    .on_conflict_do_nothing(
                        constraint="uq_digest_executions_occurrence"
                    )
                    .returning(DigestExecution.id)
                )
                inserted_id = result.scalar_one_or_none()
                if inserted_id is None:
                    # Already claimed, still advance next_due_at
                    pass

                # Advance next_due_at
                config.next_due_at = compute_next_due(
                    local_time_val,
                    tz,
                    max(now, scheduled_for),
                )
                config.updated_at = now
                await session.flush()

                if inserted_id is not None:
                    results.append(
                        DueOccurrence(
                            execution_id=execution_id,
                            user_id=config.user_id,
                            telegram_user_id=user.telegram_user_id,
                            occurrence_key=occ_key,
                            scheduled_for=scheduled_for,
                            local_date=local_date,
                            local_time=local_time_val,
                            timezone_name=config.timezone_name,
                            schedule_revision=config.schedule_revision,
                            digest_count=config.digest_count,
                            language_code=user.language_code or "en",
                        )
                    )

        return tuple(results)

    async def load_occurrence(self, execution_id: UUID) -> DueOccurrence | None:
        async with self._database.session() as session:
            row = (
                await session.execute(
                    select(DigestExecution, ApplicationUser.telegram_user_id)
                    .join(
                        ApplicationUser,
                        ApplicationUser.id == DigestExecution.user_id,
                    )
                    .where(DigestExecution.id == execution_id)
                )
            ).one_or_none()
            if row is None:
                return None
            execution, telegram_user_id = row
            return DueOccurrence(
                execution_id=execution.id,
                user_id=execution.user_id,
                telegram_user_id=telegram_user_id,
                occurrence_key=execution.occurrence_key,
                scheduled_for=execution.scheduled_for,
                local_date=execution.local_date,
                local_time=execution.local_time,
                timezone_name=execution.timezone_name,
                schedule_revision=execution.schedule_revision,
                digest_count=execution.digest_count,
                language_code=execution.language_code,
            )

    async def record_success(self, execution_id: UUID, completed_at: datetime) -> None:
        async with self._database.session() as session:
            execution = await session.get(DigestExecution, execution_id)
            if execution is None:
                return
            await self._update_success_summary(session, execution, completed_at)
            await session.flush()

    async def record_failure(
        self, execution_id: UUID, failure_code: str, completed_at: datetime
    ) -> None:
        validate_reason_code(failure_code)
        async with self._database.session() as session:
            execution = await session.get(DigestExecution, execution_id)
            if execution is None:
                return
            await self._update_failure_summary(
                session,
                execution,
                failure_code,
                completed_at,
            )
            await session.flush()

    # -- Execution operations --

    async def claim_attempt(
        self, execution_id: UUID, phase: str, now: datetime
    ) -> AttemptClaim:
        async with self._database.session() as session:
            execution = await session.get(
                DigestExecution, execution_id, with_for_update=True
            )
            if execution is None:
                raise ExecutionTerminalError("execution not found", code="not_found")
            if execution.status in TERMINAL_STATUSES:
                raise ExecutionTerminalError(
                    f"execution is {execution.status}", code="terminal"
                )
            # Check for running attempts
            running = await session.scalar(
                select(DigestExecutionAttempt.id).where(
                    DigestExecutionAttempt.execution_id == execution_id,
                    DigestExecutionAttempt.status == AttemptStatus.RUNNING,
                )
            )
            if running is not None:
                raise ExecutionBusyError("concurrent attempt running", code="busy")

            ordinal = execution.attempt_count + 1
            execution.attempt_count = ordinal
            if execution.started_at is None:
                execution.started_at = now

            attempt_phase = AttemptPhase(phase)
            # Transition status based on phase
            if attempt_phase == AttemptPhase.PREPARE:
                execution.status = ExecutionStatus.PROCESSING
            elif attempt_phase == AttemptPhase.COMPOSE:
                execution.status = ExecutionStatus.COMPOSING
            elif attempt_phase == AttemptPhase.DELIVER:
                if execution.delivery_started_at is None:
                    execution.delivery_started_at = now
                execution.status = ExecutionStatus.DELIVERING

            execution.next_retry_at = None
            execution.failure_code = None
            execution.failure_class = None
            execution.updated_at = now

            attempt_id = uuid4()
            attempt = DigestExecutionAttempt(
                id=attempt_id,
                execution_id=execution_id,
                ordinal=ordinal,
                phase=attempt_phase,
                status=AttemptStatus.RUNNING,
                started_at=now,
            )
            session.add(attempt)
            await session.flush()

            return AttemptClaim(
                attempt_id=attempt_id,
                execution_id=execution_id,
                ordinal=ordinal,
                phase=attempt_phase,
            )

    async def record_selection(
        self,
        execution_id: UUID,
        selected_count: int,
        ranking_run_id: UUID | None,
        profile_revision: int | None,
    ) -> None:
        if selected_count < 0:
            raise ValueError("selected_count must be non-negative")
        if profile_revision is not None and profile_revision < 0:
            raise ValueError("profile_revision must be non-negative")
        async with self._database.session() as session:
            execution = await session.get(
                DigestExecution,
                execution_id,
                with_for_update=True,
            )
            if execution is None:
                raise ExecutionTerminalError(
                    "execution not found",
                    code="not_found",
                )
            if execution.status in TERMINAL_STATUSES:
                raise ExecutionTerminalError(
                    "execution is terminal",
                    code="terminal",
                )
            if selected_count > execution.digest_count:
                raise ValueError("selected_count exceeds captured digest_count")
            if execution.selected_count is not None:
                if (
                    execution.selected_count != selected_count
                    or execution.ranking_run_id != ranking_run_id
                    or execution.profile_revision != profile_revision
                ):
                    raise StaleAttemptError(
                        "selection does not match persisted execution",
                        code="selection_mismatch",
                    )
                return
            execution.selected_count = selected_count
            execution.ranking_run_id = ranking_run_id
            execution.profile_revision = profile_revision
            await session.flush()

    async def record_items(
        self,
        execution_id: UUID,
        items: Sequence[StructuredDigestItem],
        now: datetime,
    ) -> StructuredDigest:
        item_tuple = tuple(items)
        positions = tuple(item.position for item in item_tuple)
        if positions != tuple(range(1, len(item_tuple) + 1)):
            raise ValueError("digest item positions must be contiguous from 1")
        article_ids = tuple(item.article_id for item in item_tuple)
        if len(set(article_ids)) != len(article_ids):
            raise ValueError("digest items must contain unique articles")
        async with self._database.session() as session:
            execution = await session.get(
                DigestExecution,
                execution_id,
                with_for_update=True,
            )
            if execution is None:
                raise ExecutionTerminalError(
                    "execution not found",
                    code="not_found",
                )
            if execution.status in TERMINAL_STATUSES:
                raise ExecutionTerminalError(
                    "execution is terminal",
                    code="terminal",
                )
            if execution.selected_count is None:
                raise ValueError("selection must be persisted before items")
            if len(item_tuple) != execution.selected_count:
                raise ValueError(
                    "item count must exactly equal execution selected_count"
                )
            if not item_tuple:
                raise ValueError("zero-item executions do not persist digest items")
            if execution.ranking_run_id is None:
                raise ValueError("non-empty selection requires ranking_run_id")
            if any(
                item.ranking_run_id != execution.ranking_run_id for item in item_tuple
            ):
                raise ValueError("item ranking_run_id must match execution")

            existing_rows = (
                (
                    await session.execute(
                        select(DigestItem)
                        .where(DigestItem.execution_id == execution_id)
                        .order_by(DigestItem.position)
                    )
                )
                .scalars()
                .all()
            )
            if existing_rows:
                if len(existing_rows) != len(item_tuple):
                    raise StaleAttemptError(
                        "persisted digest item count mismatch",
                        code="item_set_mismatch",
                    )
                for row, item in zip(existing_rows, item_tuple, strict=True):
                    expected_hash = self._content_hash(item)
                    if (
                        row.position != item.position
                        or row.article_id != item.article_id
                        or row.content_hash != expected_hash
                    ):
                        raise StaleAttemptError(
                            "persisted digest items differ",
                            code="item_set_mismatch",
                        )
                return self._structured_digest(execution, existing_rows)

            for item in item_tuple:
                item_hash = self._content_hash(item)
                if item.content_hash and item.content_hash != item_hash:
                    raise ValueError("item content_hash does not match canonical item")
                db_item = DigestItem(
                    execution_id=execution_id,
                    position=item.position,
                    article_id=item.article_id,
                    article_analysis_id=item.article_analysis_id,
                    event_group_id=item.event_group_id,
                    ranking_run_id=item.ranking_run_id,
                    title=item.title,
                    summary=item.summary,
                    source_name=item.source_name,
                    published_at=item.published_at,
                    canonical_url=item.canonical_url,
                    score=item.score,
                    content_schema_version=item.content_schema_version,
                    content_hash=item_hash,
                    created_at=now,
                )
                session.add(db_item)

            execution.content_ready_at = now
            execution.status = ExecutionStatus.READY
            execution.updated_at = now
            await session.flush()

            return StructuredDigest(
                execution_id=execution_id,
                user_id=execution.user_id,
                language=execution.language_code,
                items=item_tuple,
            )

    async def load_digest(self, execution_id: UUID) -> StructuredDigest | None:
        async with self._database.session() as session:
            execution = await session.get(DigestExecution, execution_id)
            if execution is None:
                return None
            rows = (
                (
                    await session.execute(
                        select(DigestItem)
                        .where(DigestItem.execution_id == execution_id)
                        .order_by(DigestItem.position)
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                return None
            return self._structured_digest(execution, rows)

    async def prepare_delivery_parts(
        self, execution_id: UUID, parts: Sequence[RenderedPart]
    ) -> tuple[DeliveryPartSnapshot, ...]:
        descriptors = tuple(parts)
        if not descriptors:
            raise ValueError("non-empty digest requires delivery parts")
        if tuple(part.ordinal for part in descriptors) != tuple(
            range(1, len(descriptors) + 1)
        ):
            raise ValueError("delivery part ordinals must be contiguous from 1")
        expected_first = 1
        for part in descriptors:
            if part.first_item_position != expected_first:
                raise ValueError("delivery part item ranges must be contiguous")
            expected_first = part.last_item_position + 1
        async with self._database.session() as session:
            execution = await session.get(
                DigestExecution,
                execution_id,
                with_for_update=True,
            )
            if execution is None:
                raise ExecutionTerminalError("execution not found", code="not_found")
            if execution.status in TERMINAL_STATUSES:
                raise ExecutionTerminalError("execution is terminal", code="terminal")
            if execution.selected_count is None or execution.selected_count < 1:
                raise ValueError("delivery parts require a non-empty selection")
            if expected_first - 1 != execution.selected_count:
                raise ValueError("delivery part ranges must cover every digest item")

            existing = (
                (
                    await session.execute(
                        select(DigestDeliveryPart)
                        .where(DigestDeliveryPart.execution_id == execution_id)
                        .order_by(DigestDeliveryPart.ordinal)
                    )
                )
                .scalars()
                .all()
            )
            if existing:
                if len(existing) != len(descriptors):
                    raise StaleAttemptError(
                        "delivery part descriptor count changed",
                        code="part_descriptor_mismatch",
                    )
                for row, part in zip(existing, descriptors, strict=True):
                    if (
                        row.ordinal != part.ordinal
                        or row.content_hash != part.content_hash
                        or row.first_item_position != part.first_item_position
                        or row.last_item_position != part.last_item_position
                    ):
                        raise StaleAttemptError(
                            "delivery part descriptor changed",
                            code="part_descriptor_mismatch",
                        )
                return tuple(self._part_snapshot(row) for row in existing)

            result: list[DeliveryPartSnapshot] = []
            for part in descriptors:
                db_part = DigestDeliveryPart(
                    execution_id=execution_id,
                    ordinal=part.ordinal,
                    content_hash=part.content_hash,
                    first_item_position=part.first_item_position,
                    last_item_position=part.last_item_position,
                    status=DeliveryPartStatus.PENDING,
                    attempt_count=0,
                )
                session.add(db_part)
                await session.execute(
                    update(DigestItem)
                    .where(
                        DigestItem.execution_id == execution_id,
                        DigestItem.position >= part.first_item_position,
                        DigestItem.position <= part.last_item_position,
                    )
                    .values(delivery_part_ordinal=part.ordinal)
                )
                result.append(self._part_snapshot(db_part))
            await session.flush()
            return tuple(result)

    async def claim_delivery_part(
        self, execution_id: UUID, ordinal: int, now: datetime
    ) -> DeliveryPartClaim | None:
        async with self._database.session() as session:
            part = (
                await session.execute(
                    select(DigestDeliveryPart)
                    .where(
                        DigestDeliveryPart.execution_id == execution_id,
                        DigestDeliveryPart.ordinal == ordinal,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if part is None:
                return None
            if part.status is DeliveryPartStatus.SENDING:
                stale_before = now - timedelta(seconds=self._sending_stale_seconds)
                if part.claimed_at is not None and part.claimed_at <= stale_before:
                    await self._mark_delivery_unknown(
                        session,
                        part,
                        reason_code="stale_sending",
                        occurred_at=now,
                    )
                return None
            if part.status not in (
                DeliveryPartStatus.PENDING,
                DeliveryPartStatus.FAILED,
            ):
                return None
            part.status = DeliveryPartStatus.SENDING
            part.claimed_at = now
            part.attempt_count += 1
            part.updated_at = now
            execution = await session.get(
                DigestExecution,
                execution_id,
                with_for_update=True,
            )
            if execution is None or execution.status in TERMINAL_STATUSES:
                raise ExecutionTerminalError("execution is terminal", code="terminal")
            execution.status = ExecutionStatus.DELIVERING
            if execution.delivery_started_at is None:
                execution.delivery_started_at = now
            execution.updated_at = now
            await session.flush()
            return DeliveryPartClaim(
                execution_id=execution_id,
                ordinal=part.ordinal,
                content_hash=part.content_hash,
                first_item_position=part.first_item_position,
                last_item_position=part.last_item_position,
            )

    async def acknowledge_delivery_part(
        self,
        claim: DeliveryPartClaim,
        provider_message_id: str,
        sent_at: datetime,
    ) -> DeliveryPartSnapshot:
        if not provider_message_id or len(provider_message_id) > 100:
            raise ValueError("provider_message_id must be 1..100 characters")
        async with self._database.session() as session:
            part = (
                await session.execute(
                    select(DigestDeliveryPart)
                    .where(
                        DigestDeliveryPart.execution_id == claim.execution_id,
                        DigestDeliveryPart.ordinal == claim.ordinal,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            self._validate_part_claim(part, claim)
            if part.status is DeliveryPartStatus.SENT:
                if part.provider_message_id != provider_message_id:
                    raise StaleAttemptError(
                        "delivery acknowledgement changed",
                        code="acknowledgement_mismatch",
                    )
                return self._part_snapshot(part)
            if part.status is not DeliveryPartStatus.SENDING:
                raise StaleAttemptError(
                    "delivery part is not claimed for sending",
                    code="stale_delivery_claim",
                )
            part.status = DeliveryPartStatus.SENT
            part.provider_message_id = provider_message_id
            part.sent_at = sent_at
            part.updated_at = sent_at
            await self._insert_history_for_part(
                session,
                part,
                HistoryOutcome.CONFIRMED,
                sent_at,
            )
            await session.flush()
            return self._part_snapshot(part)

    async def record_delivery_unknown(
        self, claim: DeliveryPartClaim, reason_code: str, occurred_at: datetime
    ) -> DigestExecutionSnapshot:
        async with self._database.session() as session:
            part = (
                await session.execute(
                    select(DigestDeliveryPart)
                    .where(
                        DigestDeliveryPart.execution_id == claim.execution_id,
                        DigestDeliveryPart.ordinal == claim.ordinal,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            self._validate_part_claim(part, claim)
            return await self._mark_delivery_unknown(
                session,
                part,
                reason_code=reason_code,
                occurred_at=occurred_at,
            )

    async def record_transient_failure(
        self,
        attempt_claim: AttemptClaim,
        reason_code: str,
        failed_at: datetime,
        next_retry_at: datetime,
    ) -> DigestExecutionSnapshot:
        validate_reason_code(reason_code)
        if next_retry_at <= failed_at:
            raise ValueError("next_retry_at must be after failed_at")
        async with self._database.session() as session:
            attempt, execution = await self._lock_attempt(
                session,
                attempt_claim,
            )
            attempt.status = AttemptStatus.TRANSIENT_FAILURE
            attempt.error_code = reason_code
            attempt.completed_at = failed_at
            await session.execute(
                update(DigestDeliveryPart)
                .where(
                    DigestDeliveryPart.execution_id == execution.id,
                    DigestDeliveryPart.status == DeliveryPartStatus.SENDING,
                )
                .values(
                    status=DeliveryPartStatus.FAILED,
                    failure_code=reason_code,
                    updated_at=failed_at,
                )
            )
            execution.status = ExecutionStatus.RETRYING
            execution.failure_code = reason_code
            execution.failure_class = FailureClass.TRANSIENT
            execution.next_retry_at = next_retry_at
            execution.updated_at = failed_at
            await session.flush()
            return self._execution_snapshot(execution)

    async def record_permanent_failure(
        self,
        attempt_claim: AttemptClaim,
        reason_code: str,
        failed_at: datetime,
    ) -> DigestExecutionSnapshot:
        validate_reason_code(reason_code)
        async with self._database.session() as session:
            attempt, execution = await self._lock_attempt(
                session,
                attempt_claim,
            )
            attempt.status = AttemptStatus.PERMANENT_FAILURE
            attempt.error_code = reason_code
            attempt.completed_at = failed_at
            await session.execute(
                update(DigestDeliveryPart)
                .where(
                    DigestDeliveryPart.execution_id == execution.id,
                    DigestDeliveryPart.status == DeliveryPartStatus.SENDING,
                )
                .values(
                    status=DeliveryPartStatus.FAILED,
                    failure_code=reason_code,
                    updated_at=failed_at,
                )
            )
            execution.status = ExecutionStatus.FAILED
            execution.failure_code = reason_code
            execution.failure_class = FailureClass.PERMANENT
            execution.completed_at = failed_at
            execution.next_retry_at = None
            execution.updated_at = failed_at
            await self._update_failure_summary(
                session,
                execution,
                reason_code,
                failed_at,
            )
            await session.flush()
            return self._execution_snapshot(execution)

    async def claim_retries(self, now: datetime, batch_size: int) -> tuple[UUID, ...]:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        async with self._database.session() as session:
            rows = (
                (
                    await session.execute(
                        select(DigestExecution)
                        .where(
                            DigestExecution.status == ExecutionStatus.RETRYING,
                            DigestExecution.next_retry_at.is_not(None),
                            DigestExecution.next_retry_at <= now,
                        )
                        .order_by(DigestExecution.next_retry_at, DigestExecution.id)
                        .limit(batch_size)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )
            lease_until = now + timedelta(seconds=self._retry_claim_lease_seconds)
            for execution in rows:
                execution.next_retry_at = lease_until
                execution.updated_at = now
            await session.flush()
            return tuple(execution.id for execution in rows)

    async def get_execution(self, execution_id: UUID) -> DigestExecutionSnapshot | None:
        async with self._database.session() as session:
            execution = await session.get(DigestExecution, execution_id)
            if execution is None:
                return None
            return self._execution_snapshot(execution)

    async def get_pending_parts(
        self, execution_id: UUID
    ) -> tuple[DeliveryPartSnapshot, ...]:
        async with self._database.session() as session:
            rows = (
                (
                    await session.execute(
                        select(DigestDeliveryPart)
                        .where(
                            DigestDeliveryPart.execution_id == execution_id,
                            DigestDeliveryPart.status.in_(
                                [
                                    DeliveryPartStatus.PENDING,
                                    DeliveryPartStatus.FAILED,
                                ]
                            ),
                        )
                        .order_by(DigestDeliveryPart.ordinal)
                    )
                )
                .scalars()
                .all()
            )
            return tuple(self._part_snapshot(part) for part in rows)

    async def record_history(
        self,
        execution_id: UUID,
        user_id: UUID,
        items: Sequence[StructuredDigestItem],
        outcome: str,
        delivered_at: datetime,
    ) -> None:
        async with self._database.session() as session:
            # Load digest items to get their IDs
            db_items = (
                (
                    await session.execute(
                        select(DigestItem)
                        .where(DigestItem.execution_id == execution_id)
                        .order_by(DigestItem.position)
                    )
                )
                .scalars()
                .all()
            )
            items_by_position = {item.position: item for item in db_items}
            history_outcome = HistoryOutcome(outcome)
            for item in items:
                db_item = items_by_position.get(item.position)
                if db_item is None:
                    continue
                await session.execute(
                    insert(DigestDeliveryHistory)
                    .values(
                        user_id=user_id,
                        execution_id=execution_id,
                        digest_item_id=db_item.id,
                        article_id=item.article_id,
                        article_analysis_id=item.article_analysis_id,
                        event_group_id=item.event_group_id,
                        publication_time=item.published_at,
                        outcome=history_outcome,
                        delivered_at=delivered_at,
                    )
                    .on_conflict_do_nothing(
                        constraint="uq_digest_delivery_history_execution_article"
                    )
                )
            await session.flush()

    async def complete_execution(
        self, execution_id: UUID, completed_at: datetime
    ) -> DigestExecutionSnapshot:
        async with self._database.session() as session:
            execution = await session.get(
                DigestExecution,
                execution_id,
                with_for_update=True,
            )
            if execution is None:
                raise ExecutionTerminalError("execution not found", code="not_found")
            if execution.status is ExecutionStatus.COMPLETED:
                return self._execution_snapshot(execution)
            if execution.status in {
                ExecutionStatus.FAILED,
                ExecutionStatus.DELIVERY_UNKNOWN,
            }:
                raise ExecutionTerminalError("execution is terminal", code="terminal")
            if execution.selected_count is None:
                raise ValueError("execution selection is not complete")
            if execution.selected_count > 0:
                unsent_count = await session.scalar(
                    select(func.count())
                    .select_from(DigestDeliveryPart)
                    .where(
                        DigestDeliveryPart.execution_id == execution_id,
                        DigestDeliveryPart.status != DeliveryPartStatus.SENT,
                    )
                )
                part_count = await session.scalar(
                    select(func.count())
                    .select_from(DigestDeliveryPart)
                    .where(DigestDeliveryPart.execution_id == execution_id)
                )
                if not part_count or unsent_count:
                    raise ValueError(
                        "execution cannot complete before all delivery parts are sent"
                    )
            execution.status = ExecutionStatus.COMPLETED
            execution.completed_at = completed_at
            execution.failure_code = None
            execution.failure_class = None
            execution.next_retry_at = None
            execution.updated_at = completed_at
            # Complete running attempt
            running = (
                await session.execute(
                    select(DigestExecutionAttempt).where(
                        DigestExecutionAttempt.execution_id == execution_id,
                        DigestExecutionAttempt.status == AttemptStatus.RUNNING,
                    )
                )
            ).scalar_one_or_none()
            if running is not None:
                running.status = AttemptStatus.COMPLETED
                running.completed_at = completed_at
            await self._update_success_summary(session, execution, completed_at)
            await session.flush()
            return self._execution_snapshot(execution)

    async def get_user_history_article_ids(
        self,
        user_id: UUID,
        candidate_ids: Sequence[UUID] | None = None,
    ) -> set[UUID]:
        async with self._database.session() as session:
            statement = select(DigestDeliveryHistory.article_id).where(
                DigestDeliveryHistory.user_id == user_id
            )
            if candidate_ids is not None:
                ids = tuple(candidate_ids)
                if not ids:
                    return set()
                statement = statement.where(DigestDeliveryHistory.article_id.in_(ids))
            rows = (await session.execute(statement)).scalars().all()
            return set(rows)

    async def load_material_update_inputs(
        self,
        user_id: UUID,
        candidate_ids: Sequence[UUID],
    ) -> tuple[MaterialUpdateInput, ...]:
        ids = tuple(dict.fromkeys(candidate_ids))
        if not ids:
            return ()
        async with self._database.session() as session:
            candidates = (
                (
                    await session.execute(
                        select(NormalizedArticle).where(
                            NormalizedArticle.id.in_(ids),
                            NormalizedArticle.event_group_id.is_not(None),
                            NormalizedArticle.published_at.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not candidates:
                return ()
            candidate_by_id = {row.id: row for row in candidates}
            analysis_rows = (
                (
                    await session.execute(
                        select(ArticleAnalysis)
                        .where(
                            ArticleAnalysis.article_id.in_(candidate_by_id),
                            ArticleAnalysis.status == AnalysisStatus.COMPLETE,
                        )
                        .order_by(
                            ArticleAnalysis.article_id,
                            ArticleAnalysis.created_at.desc(),
                            ArticleAnalysis.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            analysis_by_article: dict[UUID, ArticleAnalysis] = {}
            for analysis in analysis_rows:
                analysis_by_article.setdefault(analysis.article_id, analysis)

            event_ids = {
                article.event_group_id
                for article in candidates
                if article.event_group_id is not None
            }
            history_rows = (
                await session.execute(
                    select(
                        DigestDeliveryHistory,
                        NormalizedArticle.normalized_text,
                    )
                    .join(
                        NormalizedArticle,
                        NormalizedArticle.id == DigestDeliveryHistory.article_id,
                    )
                    .where(
                        DigestDeliveryHistory.user_id == user_id,
                        DigestDeliveryHistory.event_group_id.in_(event_ids),
                    )
                    .order_by(DigestDeliveryHistory.delivered_at.desc())
                    .limit(max(20, len(ids) * 20))
                )
            ).all()

            candidate_and_prior_ids = set(candidate_by_id)
            candidate_and_prior_ids.update(
                history.article_id for history, _ in history_rows
            )
            veto_rows = (
                (
                    await session.execute(
                        select(DeduplicationDecision).where(
                            DeduplicationDecision.left_article_id.in_(
                                candidate_and_prior_ids
                            ),
                            DeduplicationDecision.right_article_id.in_(
                                candidate_and_prior_ids
                            ),
                            DeduplicationDecision.outcome.in_(
                                [
                                    DecisionOutcome.DUPLICATE,
                                    DecisionOutcome.REVIEW,
                                ]
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            veto_pairs = {
                frozenset((row.left_article_id, row.right_article_id))
                for row in veto_rows
            }

            result: list[MaterialUpdateInput] = []
            for candidate_id in ids:
                candidate = candidate_by_id.get(candidate_id)
                analysis = analysis_by_article.get(candidate_id)
                if (
                    candidate is None
                    or analysis is None
                    or candidate.event_group_id is None
                    or candidate.published_at is None
                ):
                    continue
                candidate_snapshot = CandidateArticleEvidence(
                    article_id=candidate.id,
                    article_analysis_id=analysis.id,
                    event_group_id=candidate.event_group_id,
                    publication_time=candidate.published_at,
                    normalized_text=candidate.normalized_text,
                    novelty_score=analysis.novelty_score,
                )
                for history, prior_text in history_rows:
                    if (
                        history.event_group_id != candidate.event_group_id
                        or history.article_id == candidate.id
                    ):
                        continue
                    result.append(
                        MaterialUpdateInput(
                            delivered=DeliveredArticleEvidence(
                                history_id=history.id,
                                article_id=history.article_id,
                                article_analysis_id=history.article_analysis_id,
                                event_group_id=history.event_group_id,
                                publication_time=history.publication_time,
                                normalized_text=prior_text,
                            ),
                            candidate=candidate_snapshot,
                            has_duplicate_or_review_veto=(
                                frozenset((history.article_id, candidate.id))
                                in veto_pairs
                            ),
                        )
                    )
            return tuple(result)

    async def get_user_history_event_groups(
        self, user_id: UUID
    ) -> dict[UUID, list[DigestDeliveryHistory]]:
        """Return history entries grouped by event_group_id for a user."""
        async with self._database.session() as session:
            rows = (
                (
                    await session.execute(
                        select(DigestDeliveryHistory).where(
                            DigestDeliveryHistory.user_id == user_id,
                            DigestDeliveryHistory.event_group_id.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            groups: dict[UUID, list[DigestDeliveryHistory]] = {}
            for row in rows:
                groups.setdefault(row.event_group_id, []).append(row)
            return groups

    async def load_material_update_evidence(
        self,
        delivery_history_id: UUID,
        candidate_article_id: UUID,
        policy_version: str,
    ) -> MaterialUpdateEvidence | None:
        async with self._database.session() as session:
            row = (
                await session.execute(
                    select(DigestMaterialUpdateEvidence).where(
                        DigestMaterialUpdateEvidence.delivery_history_id
                        == delivery_history_id,
                        DigestMaterialUpdateEvidence.candidate_article_id
                        == candidate_article_id,
                        DigestMaterialUpdateEvidence.policy_version == policy_version,
                    )
                )
            ).scalar_one_or_none()
            return None if row is None else self._material_evidence_snapshot(row)

    async def save_material_update_evidence(
        self,
        evidence: MaterialUpdateEvidence,
    ) -> MaterialUpdateEvidence:
        async with self._database.session() as session:
            await session.execute(
                insert(DigestMaterialUpdateEvidence)
                .values(
                    id=uuid4(),
                    delivery_history_id=evidence.delivery_history_id,
                    candidate_article_id=evidence.candidate_article_id,
                    candidate_analysis_id=evidence.candidate_analysis_id,
                    event_group_id=evidence.event_group_id,
                    policy_version=evidence.policy_version,
                    basis=evidence.basis,
                    outcome=evidence.outcome,
                    prior_text_hash=evidence.prior_text_hash,
                    candidate_text_hash=evidence.candidate_text_hash,
                    content_similarity=evidence.content_similarity,
                    novelty_score=evidence.novelty_score,
                    threshold_snapshot=evidence.threshold_snapshot or {},
                )
                .on_conflict_do_nothing(
                    constraint="uq_digest_material_update_evidence_pair_policy"
                )
            )
            row = (
                await session.execute(
                    select(DigestMaterialUpdateEvidence).where(
                        DigestMaterialUpdateEvidence.delivery_history_id
                        == evidence.delivery_history_id,
                        DigestMaterialUpdateEvidence.candidate_article_id
                        == evidence.candidate_article_id,
                        DigestMaterialUpdateEvidence.policy_version
                        == evidence.policy_version,
                    )
                )
            ).scalar_one()
            return self._material_evidence_snapshot(row)

    async def delete_expired_history(self, before: datetime, batch_size: int) -> int:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        async with self._database.session() as session:
            ids = (
                (
                    await session.execute(
                        select(DigestDeliveryHistory.id)
                        .join(
                            DigestExecution,
                            DigestExecution.id == DigestDeliveryHistory.execution_id,
                        )
                        .where(
                            DigestDeliveryHistory.delivered_at < before,
                            DigestDeliveryHistory.outcome == HistoryOutcome.CONFIRMED,
                            DigestExecution.status.in_(
                                [
                                    ExecutionStatus.COMPLETED,
                                    ExecutionStatus.FAILED,
                                ]
                            ),
                        )
                        .order_by(DigestDeliveryHistory.delivered_at)
                        .limit(batch_size)
                    )
                )
                .scalars()
                .all()
            )
            if not ids:
                return 0
            await session.execute(
                delete(DigestDeliveryHistory).where(DigestDeliveryHistory.id.in_(ids))
            )
            return len(ids)

    async def delete_expired_details(
        self,
        before: datetime,
        batch_size: int,
    ) -> int:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        async with self._database.session() as session:
            execution_ids = (
                (
                    await session.execute(
                        select(DigestExecution.id)
                        .where(
                            DigestExecution.status.in_(
                                [
                                    ExecutionStatus.COMPLETED,
                                    ExecutionStatus.FAILED,
                                ]
                            ),
                            DigestExecution.completed_at.is_not(None),
                            DigestExecution.completed_at < before,
                        )
                        .order_by(DigestExecution.completed_at)
                        .limit(batch_size)
                    )
                )
                .scalars()
                .all()
            )
            if not execution_ids:
                return 0
            attempts = await session.execute(
                delete(DigestExecutionAttempt).where(
                    DigestExecutionAttempt.execution_id.in_(execution_ids)
                )
            )
            parts = await session.execute(
                delete(DigestDeliveryPart).where(
                    DigestDeliveryPart.execution_id.in_(execution_ids)
                )
            )
            unreferenced_item_ids = (
                select(DigestItem.id)
                .where(DigestItem.execution_id.in_(execution_ids))
                .where(
                    ~select(DigestDeliveryHistory.id)
                    .where(DigestDeliveryHistory.digest_item_id == DigestItem.id)
                    .exists()
                )
                .limit(batch_size)
            )
            items = await session.execute(
                delete(DigestItem).where(DigestItem.id.in_(unreferenced_item_ids))
            )
            return (
                max(attempts.rowcount or 0, 0)
                + max(parts.rowcount or 0, 0)
                + max(items.rowcount or 0, 0)
            )

    # -- Helpers --

    async def _lock_attempt(
        self,
        session: AsyncSession,
        claim: AttemptClaim,
    ) -> tuple[DigestExecutionAttempt, DigestExecution]:
        attempt = await session.get(
            DigestExecutionAttempt,
            claim.attempt_id,
            with_for_update=True,
        )
        execution = await session.get(
            DigestExecution,
            claim.execution_id,
            with_for_update=True,
        )
        if (
            attempt is None
            or execution is None
            or attempt.execution_id != claim.execution_id
            or attempt.ordinal != claim.ordinal
            or attempt.phase is not claim.phase
            or attempt.status is not AttemptStatus.RUNNING
        ):
            raise StaleAttemptError(
                "attempt claim is stale",
                code="stale_attempt",
            )
        if execution.status in TERMINAL_STATUSES:
            raise ExecutionTerminalError("execution is terminal", code="terminal")
        return attempt, execution

    @staticmethod
    async def _update_success_summary(
        session: AsyncSession,
        execution: DigestExecution,
        completed_at: datetime,
    ) -> None:
        config = await session.get(
            DigestConfiguration,
            execution.user_id,
            with_for_update=True,
        )
        if config is None:
            return
        if config.last_success_at is None or completed_at > config.last_success_at:
            config.last_success_execution_id = execution.id
            config.last_success_at = completed_at
            config.updated_at = completed_at

    @staticmethod
    async def _update_failure_summary(
        session: AsyncSession,
        execution: DigestExecution,
        reason_code: str,
        failed_at: datetime,
    ) -> None:
        config = await session.get(
            DigestConfiguration,
            execution.user_id,
            with_for_update=True,
        )
        if config is None:
            return
        if config.last_failure_at is None or failed_at > config.last_failure_at:
            config.last_failure_execution_id = execution.id
            config.last_failure_at = failed_at
            config.last_failure_code = reason_code
            config.updated_at = failed_at

    @staticmethod
    def _content_hash(item: StructuredDigestItem) -> str:
        return content_hash(
            {
                "position": item.position,
                "article_id": str(item.article_id),
                "title": item.title,
                "summary": item.summary,
                "source_name": item.source_name,
                "published_at": item.published_at.isoformat(),
                "canonical_url": item.canonical_url,
            }
        )

    @staticmethod
    def _structured_digest(
        execution: DigestExecution,
        rows: Sequence[DigestItem],
    ) -> StructuredDigest:
        items = tuple(
            StructuredDigestItem(
                position=row.position,
                article_id=row.article_id,
                article_analysis_id=row.article_analysis_id,
                event_group_id=row.event_group_id,
                ranking_run_id=row.ranking_run_id,
                title=row.title,
                summary=row.summary,
                source_name=row.source_name,
                published_at=row.published_at,
                canonical_url=row.canonical_url,
                score=row.score,
                content_schema_version=row.content_schema_version,
                content_hash=row.content_hash,
            )
            for row in rows
        )
        return StructuredDigest(
            execution_id=execution.id,
            user_id=execution.user_id,
            language=execution.language_code,
            items=items,
        )

    @staticmethod
    def _part_snapshot(part: DigestDeliveryPart) -> DeliveryPartSnapshot:
        return DeliveryPartSnapshot(
            execution_id=part.execution_id,
            ordinal=part.ordinal,
            status=part.status,
            content_hash=part.content_hash,
            first_item_position=part.first_item_position,
            last_item_position=part.last_item_position,
            provider_message_id=part.provider_message_id,
            attempt_count=part.attempt_count,
        )

    @staticmethod
    def _material_evidence_snapshot(
        row: DigestMaterialUpdateEvidence,
    ) -> MaterialUpdateEvidence:
        return MaterialUpdateEvidence(
            delivery_history_id=row.delivery_history_id,
            candidate_article_id=row.candidate_article_id,
            candidate_analysis_id=row.candidate_analysis_id,
            event_group_id=row.event_group_id,
            policy_version=row.policy_version,
            basis=MaterialUpdateBasis(row.basis),
            outcome=MaterialUpdateOutcome(row.outcome),
            prior_text_hash=row.prior_text_hash,
            candidate_text_hash=row.candidate_text_hash,
            content_similarity=(
                Decimal(row.content_similarity)
                if row.content_similarity is not None
                else None
            ),
            novelty_score=(
                Decimal(row.novelty_score) if row.novelty_score is not None else None
            ),
            threshold_snapshot=dict(row.threshold_snapshot),
        )

    @staticmethod
    def _validate_part_claim(
        part: DigestDeliveryPart,
        claim: DeliveryPartClaim,
    ) -> None:
        if (
            part.execution_id != claim.execution_id
            or part.ordinal != claim.ordinal
            or part.content_hash != claim.content_hash
            or part.first_item_position != claim.first_item_position
            or part.last_item_position != claim.last_item_position
        ):
            raise StaleAttemptError(
                "delivery part claim does not match persisted descriptor",
                code="delivery_hash_mismatch",
            )

    @staticmethod
    async def _insert_history_for_part(
        session: AsyncSession,
        part: DigestDeliveryPart,
        outcome: HistoryOutcome,
        delivered_at: datetime,
    ) -> None:
        execution = await session.get(DigestExecution, part.execution_id)
        if execution is None:
            raise ExecutionTerminalError("execution not found", code="not_found")
        rows = (
            (
                await session.execute(
                    select(DigestItem).where(
                        DigestItem.execution_id == part.execution_id,
                        DigestItem.position >= part.first_item_position,
                        DigestItem.position <= part.last_item_position,
                    )
                )
            )
            .scalars()
            .all()
        )
        expected_count = part.last_item_position - part.first_item_position + 1
        if len(rows) != expected_count:
            raise StaleAttemptError(
                "delivery part item range is incomplete",
                code="delivery_item_range_mismatch",
            )
        for item in rows:
            await session.execute(
                insert(DigestDeliveryHistory)
                .values(
                    user_id=execution.user_id,
                    execution_id=execution.id,
                    digest_item_id=item.id,
                    article_id=item.article_id,
                    article_analysis_id=item.article_analysis_id,
                    event_group_id=item.event_group_id,
                    publication_time=item.published_at,
                    outcome=outcome,
                    delivered_at=delivered_at,
                )
                .on_conflict_do_nothing(
                    constraint="uq_digest_delivery_history_execution_article"
                )
            )

    async def _mark_delivery_unknown(
        self,
        session: AsyncSession,
        part: DigestDeliveryPart,
        *,
        reason_code: str,
        occurred_at: datetime,
    ) -> DigestExecutionSnapshot:
        validate_reason_code(reason_code)
        execution = await session.get(
            DigestExecution,
            part.execution_id,
            with_for_update=True,
        )
        if execution is None:
            raise ExecutionTerminalError("execution not found", code="not_found")
        if (
            part.status is DeliveryPartStatus.UNKNOWN
            and execution.status is ExecutionStatus.DELIVERY_UNKNOWN
        ):
            return self._execution_snapshot(execution)
        if part.status is not DeliveryPartStatus.SENDING:
            raise StaleAttemptError(
                "only a sending part may become unknown",
                code="stale_delivery_claim",
            )
        part.status = DeliveryPartStatus.UNKNOWN
        part.failure_code = reason_code
        part.updated_at = occurred_at
        await self._insert_history_for_part(
            session,
            part,
            HistoryOutcome.UNCERTAIN,
            occurred_at,
        )
        running = (
            await session.execute(
                select(DigestExecutionAttempt)
                .where(
                    DigestExecutionAttempt.execution_id == execution.id,
                    DigestExecutionAttempt.status == AttemptStatus.RUNNING,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if running is not None:
            running.status = AttemptStatus.AMBIGUOUS
            running.error_code = reason_code
            running.completed_at = occurred_at
        execution.status = ExecutionStatus.DELIVERY_UNKNOWN
        execution.failure_code = reason_code
        execution.failure_class = FailureClass.AMBIGUOUS_DELIVERY
        execution.completed_at = occurred_at
        execution.next_retry_at = None
        execution.updated_at = occurred_at
        await self._update_failure_summary(
            session,
            execution,
            reason_code,
            occurred_at,
        )
        await session.flush()
        return self._execution_snapshot(execution)

    @staticmethod
    def _config_snapshot(config: DigestConfiguration) -> DigestConfigurationSnapshot:
        return DigestConfigurationSnapshot(
            user_id=config.user_id,
            enabled=config.enabled,
            digest_count=config.digest_count,
            schedule_local_time=config.schedule_local_time,
            timezone_name=config.timezone_name,
            next_due_at=config.next_due_at,
            schedule_revision=config.schedule_revision,
            last_success_execution_id=config.last_success_execution_id,
            last_success_at=config.last_success_at,
            last_failure_execution_id=config.last_failure_execution_id,
            last_failure_at=config.last_failure_at,
            last_failure_code=config.last_failure_code,
        )

    @staticmethod
    def _execution_snapshot(execution: DigestExecution) -> DigestExecutionSnapshot:
        return DigestExecutionSnapshot(
            id=execution.id,
            user_id=execution.user_id,
            occurrence_key=execution.occurrence_key,
            status=execution.status,
            attempt_count=execution.attempt_count,
            selected_count=execution.selected_count,
            digest_count=execution.digest_count,
            language_code=execution.language_code,
            failure_code=execution.failure_code,
            failure_class=execution.failure_class,
            completed_at=execution.completed_at,
            next_retry_at=execution.next_retry_at,
            ranking_run_id=execution.ranking_run_id,
            profile_revision=execution.profile_revision,
        )
