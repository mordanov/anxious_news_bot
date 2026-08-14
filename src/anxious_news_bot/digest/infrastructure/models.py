"""Digest ORM entities."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from anxious_news_bot.digest.domain import (
    AttemptPhase,
    AttemptStatus,
    DeliveryPartStatus,
    ExecutionStatus,
    FailureClass,
    HistoryOutcome,
    MaterialUpdateBasis,
    MaterialUpdateOutcome,
)
from anxious_news_bot.infrastructure.database import Base, TimestampMixin


def _enum(enum_class: type, name: str) -> Enum:
    return Enum(
        enum_class,
        name=name,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


class DigestConfiguration(TimestampMixin, Base):
    __tablename__ = "digest_configurations"
    __table_args__ = (
        CheckConstraint(
            "digest_count >= 5 AND digest_count <= 20",
            name="ck_digest_configurations_count",
        ),
        CheckConstraint(
            "schedule_revision >= 0",
            name="ck_digest_configurations_revision",
        ),
        CheckConstraint(
            "NOT enabled OR next_due_at IS NOT NULL",
            name="ck_digest_configurations_enabled_due",
        ),
        CheckConstraint(
            "date_part('second', schedule_local_time) = 0",
            name="ck_digest_configurations_minute_precision",
        ),
        Index(
            "ix_digest_configurations_due",
            "next_due_at",
            "user_id",
            postgresql_where=sql_text("enabled = true"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("application_users.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sql_text("false")
    )
    digest_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default=sql_text("10")
    )
    schedule_local_time: Mapped[time] = mapped_column(
        Time, nullable=False, default=time(9, 0), server_default=sql_text("'09:00'")
    )
    timezone_name: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default=sql_text("'UTC'")
    )
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    schedule_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sql_text("0")
    )
    last_success_execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "digest_executions.id",
            name="fk_digest_configurations_last_success_execution",
            ondelete="SET NULL",
            use_alter=True,
        )
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "digest_executions.id",
            name="fk_digest_configurations_last_failure_execution",
            ondelete="SET NULL",
            use_alter=True,
        )
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_code: Mapped[str | None] = mapped_column(String(100))


class DigestExecution(TimestampMixin, Base):
    __tablename__ = "digest_executions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "occurrence_key", name="uq_digest_executions_occurrence"
        ),
        CheckConstraint(
            "digest_count >= 5 AND digest_count <= 20",
            name="ck_digest_executions_count",
        ),
        CheckConstraint(
            "attempt_count >= 0", name="ck_digest_executions_attempt_count"
        ),
        CheckConstraint(
            "selected_count IS NULL OR (selected_count >= 0 AND selected_count <= digest_count)",
            name="ck_digest_executions_selected_count",
        ),
        CheckConstraint(
            "schedule_revision >= 0",
            name="ck_digest_executions_schedule_revision",
        ),
        CheckConstraint(
            "(status NOT IN ('completed', 'failed', 'delivery_unknown') "
            "OR completed_at IS NOT NULL) "
            "AND (status <> 'retrying' OR "
            "(next_retry_at IS NOT NULL AND failure_class = 'transient')) "
            "AND (status <> 'delivery_unknown' OR "
            "failure_class = 'ambiguous_delivery')",
            name="ck_digest_executions_terminal",
        ),
        Index("ix_digest_executions_status_retry", "status", "next_retry_at"),
        Index(
            "ix_digest_executions_user_scheduled",
            "user_id",
            "scheduled_for",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("application_users.id", ondelete="CASCADE"), nullable=False
    )
    occurrence_key: Mapped[str] = mapped_column(String(160), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    local_time: Mapped[time] = mapped_column(Time, nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(64), nullable=False)
    schedule_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    digest_count: Mapped[int] = mapped_column(Integer, nullable=False)
    language_code: Mapped[str] = mapped_column(String(35), nullable=False, default="en")
    profile_revision: Mapped[int | None] = mapped_column(Integer)
    ranking_request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    ranking_run_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    status: Mapped[ExecutionStatus] = mapped_column(
        _enum(ExecutionStatus, "digest_execution_status"),
        nullable=False,
        default=ExecutionStatus.SCHEDULED,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sql_text("0")
    )
    selected_count: Mapped[int | None] = mapped_column(Integer)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    failure_class: Mapped[FailureClass | None] = mapped_column(
        _enum(FailureClass, "digest_failure_class")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    attempts: Mapped[list[DigestExecutionAttempt]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )
    items: Mapped[list[DigestItem]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )
    delivery_parts: Mapped[list[DigestDeliveryPart]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )
    history_entries: Mapped[list[DigestDeliveryHistory]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )


class DigestExecutionAttempt(Base):
    __tablename__ = "digest_execution_attempts"
    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "ordinal",
            name="uq_digest_execution_attempts_ordinal",
        ),
        CheckConstraint("ordinal > 0", name="ck_digest_execution_attempts_ordinal"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("digest_executions.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[AttemptPhase] = mapped_column(
        _enum(AttemptPhase, "digest_attempt_phase"), nullable=False
    )
    status: Mapped[AttemptStatus] = mapped_column(
        _enum(AttemptStatus, "digest_attempt_status"), nullable=False
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    execution: Mapped[DigestExecution] = relationship(back_populates="attempts")


class DigestItem(Base):
    __tablename__ = "digest_items"
    __table_args__ = (
        UniqueConstraint("execution_id", "position", name="uq_digest_items_position"),
        UniqueConstraint("execution_id", "article_id", name="uq_digest_items_article"),
        CheckConstraint("position > 0", name="ck_digest_items_position"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("digest_executions.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    article_id: Mapped[UUID] = mapped_column(
        ForeignKey("normalized_articles.id", ondelete="RESTRICT"), nullable=False
    )
    article_analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("article_analyses.id", ondelete="RESTRICT"), nullable=False
    )
    event_group_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("event_groups.id", ondelete="RESTRICT")
    )
    ranking_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ranking_runs.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(String(1200), nullable=False)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(16, 8), nullable=False)
    content_schema_version: Mapped[str] = mapped_column(
        String(20), nullable=False, default="1.0"
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    delivery_part_ordinal: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    execution: Mapped[DigestExecution] = relationship(back_populates="items")


class DigestDeliveryPart(TimestampMixin, Base):
    __tablename__ = "digest_delivery_parts"
    __table_args__ = (
        UniqueConstraint(
            "execution_id", "ordinal", name="uq_digest_delivery_parts_ordinal"
        ),
        CheckConstraint("ordinal > 0", name="ck_digest_delivery_parts_ordinal"),
        CheckConstraint(
            "last_item_position >= first_item_position",
            name="ck_digest_delivery_parts_range",
        ),
        CheckConstraint(
            "attempt_count >= 0", name="ck_digest_delivery_parts_attempt_count"
        ),
        CheckConstraint(
            "(status <> 'sent' OR "
            "(provider_message_id IS NOT NULL AND sent_at IS NOT NULL)) "
            "AND (status <> 'unknown' OR failure_code IS NOT NULL)",
            name="ck_digest_delivery_parts_state",
        ),
        UniqueConstraint(
            "execution_id",
            "provider_message_id",
            name="uq_digest_delivery_parts_provider_message",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("digest_executions.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    first_item_position: Mapped[int] = mapped_column(Integer, nullable=False)
    last_item_position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DeliveryPartStatus] = mapped_column(
        _enum(DeliveryPartStatus, "digest_delivery_part_status"),
        nullable=False,
        default=DeliveryPartStatus.PENDING,
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(100))
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sql_text("0")
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(100))

    execution: Mapped[DigestExecution] = relationship(back_populates="delivery_parts")


class DigestDeliveryHistory(Base):
    __tablename__ = "digest_delivery_history"
    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "article_id",
            name="uq_digest_delivery_history_execution_article",
        ),
        Index(
            "ix_digest_delivery_history_user_article",
            "user_id",
            "article_id",
            "delivered_at",
        ),
        Index(
            "ix_digest_delivery_history_user_event",
            "user_id",
            "event_group_id",
            "delivered_at",
            postgresql_where=sql_text("event_group_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("application_users.id", ondelete="CASCADE"), nullable=False
    )
    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("digest_executions.id", ondelete="CASCADE"), nullable=False
    )
    digest_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("digest_items.id", ondelete="CASCADE"), nullable=False
    )
    article_id: Mapped[UUID] = mapped_column(
        ForeignKey("normalized_articles.id", ondelete="RESTRICT"), nullable=False
    )
    article_analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("article_analyses.id", ondelete="RESTRICT"), nullable=False
    )
    event_group_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("event_groups.id", ondelete="RESTRICT")
    )
    publication_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    outcome: Mapped[HistoryOutcome] = mapped_column(
        _enum(HistoryOutcome, "digest_history_outcome"), nullable=False
    )
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    execution: Mapped[DigestExecution] = relationship(back_populates="history_entries")


class DigestMaterialUpdateEvidence(Base):
    __tablename__ = "digest_material_update_evidence"
    __table_args__ = (
        UniqueConstraint(
            "delivery_history_id",
            "candidate_article_id",
            "policy_version",
            name="uq_digest_material_update_evidence_pair_policy",
        ),
        CheckConstraint(
            "length(prior_text_hash) = 64 AND length(candidate_text_hash) = 64",
            name="ck_digest_material_update_evidence_hashes",
        ),
        CheckConstraint(
            "(content_similarity IS NULL OR "
            "(content_similarity >= 0 AND content_similarity <= 1)) AND "
            "(novelty_score IS NULL OR "
            "(novelty_score >= 0 AND novelty_score <= 1))",
            name="ck_digest_material_update_evidence_scores",
        ),
        CheckConstraint(
            "(basis = 'accepted_novelty' AND outcome = 'material_update' "
            "AND novelty_score IS NOT NULL) OR "
            "(basis = 'content_delta' AND outcome = 'material_update' "
            "AND content_similarity IS NOT NULL) OR "
            "(basis = 'insufficient_evidence' AND outcome = 'unchanged' "
            "AND content_similarity IS NULL AND novelty_score IS NULL)",
            name="ck_digest_material_update_evidence_consistency",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    delivery_history_id: Mapped[UUID] = mapped_column(
        ForeignKey("digest_delivery_history.id", ondelete="CASCADE"), nullable=False
    )
    candidate_article_id: Mapped[UUID] = mapped_column(
        ForeignKey("normalized_articles.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("article_analyses.id", ondelete="RESTRICT"), nullable=False
    )
    event_group_id: Mapped[UUID] = mapped_column(
        ForeignKey("event_groups.id", ondelete="RESTRICT"), nullable=False
    )
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    basis: Mapped[MaterialUpdateBasis] = mapped_column(
        _enum(MaterialUpdateBasis, "digest_material_update_basis"), nullable=False
    )
    outcome: Mapped[MaterialUpdateOutcome] = mapped_column(
        _enum(MaterialUpdateOutcome, "digest_material_update_outcome"), nullable=False
    )
    prior_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_similarity: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    novelty_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    threshold_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
