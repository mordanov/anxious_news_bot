"""Create digest scheduling and delivery tables.

Revision ID: 005_scheduler_digest
Revises: 004_question_dimension_context
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005_scheduler_digest"
down_revision: str | None = "004_question_dimension_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enum types
_execution_status = postgresql.ENUM(
    "scheduled",
    "processing",
    "composing",
    "ready",
    "delivering",
    "retrying",
    "completed",
    "failed",
    "delivery_unknown",
    name="digest_execution_status",
    create_type=False,
)
_attempt_phase = postgresql.ENUM(
    "prepare",
    "compose",
    "deliver",
    name="digest_attempt_phase",
    create_type=False,
)
_attempt_status = postgresql.ENUM(
    "running",
    "completed",
    "transient_failure",
    "permanent_failure",
    "ambiguous",
    name="digest_attempt_status",
    create_type=False,
)
_failure_class = postgresql.ENUM(
    "transient",
    "permanent",
    "ambiguous_delivery",
    name="digest_failure_class",
    create_type=False,
)
_delivery_part_status = postgresql.ENUM(
    "pending",
    "sending",
    "sent",
    "failed",
    "unknown",
    name="digest_delivery_part_status",
    create_type=False,
)
_history_outcome = postgresql.ENUM(
    "confirmed",
    "uncertain",
    name="digest_history_outcome",
    create_type=False,
)
_update_basis = postgresql.ENUM(
    "accepted_novelty",
    "content_delta",
    "insufficient_evidence",
    name="digest_material_update_basis",
    create_type=False,
)
_update_outcome = postgresql.ENUM(
    "material_update",
    "unchanged",
    name="digest_material_update_outcome",
    create_type=False,
)


def upgrade() -> None:
    # Create enum types
    for enum_type in [
        _execution_status,
        _attempt_phase,
        _attempt_status,
        _failure_class,
        _delivery_part_status,
        _history_outcome,
        _update_basis,
        _update_outcome,
    ]:
        enum_type.create(op.get_bind(), checkfirst=True)

    # DigestConfiguration
    op.create_table(
        "digest_configurations",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("application_users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "enabled", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "digest_count", sa.Integer, nullable=False, server_default=sa.text("10")
        ),
        sa.Column(
            "schedule_local_time",
            sa.Time,
            nullable=False,
            server_default=sa.text("'09:00'"),
        ),
        sa.Column(
            "timezone_name",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'UTC'"),
        ),
        sa.Column("next_due_at", sa.DateTime(timezone=True)),
        sa.Column(
            "schedule_revision", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
        sa.Column("last_success_execution_id", postgresql.UUID(as_uuid=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_execution_id", postgresql.UUID(as_uuid=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_code", sa.String(100)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "digest_count >= 5 AND digest_count <= 20",
            name="ck_digest_configurations_count",
        ),
        sa.CheckConstraint(
            "schedule_revision >= 0", name="ck_digest_configurations_revision"
        ),
        sa.CheckConstraint(
            "NOT enabled OR next_due_at IS NOT NULL",
            name="ck_digest_configurations_enabled_due",
        ),
        sa.CheckConstraint(
            "date_part('second', schedule_local_time) = 0",
            name="ck_digest_configurations_minute_precision",
        ),
    )
    op.create_index(
        "ix_digest_configurations_due",
        "digest_configurations",
        ["next_due_at", "user_id"],
        postgresql_where=sa.text("enabled = true"),
    )

    # DigestExecution
    op.create_table(
        "digest_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("application_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("occurrence_key", sa.String(160), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_date", sa.Date, nullable=False),
        sa.Column("local_time", sa.Time, nullable=False),
        sa.Column("timezone_name", sa.String(64), nullable=False),
        sa.Column("schedule_revision", sa.Integer, nullable=False),
        sa.Column("digest_count", sa.Integer, nullable=False),
        sa.Column(
            "language_code",
            sa.String(35),
            nullable=False,
            server_default=sa.text("'en'"),
        ),
        sa.Column("profile_revision", sa.Integer),
        sa.Column("ranking_request_id", sa.String(200), nullable=False),
        sa.Column("ranking_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "status",
            _execution_status,
            nullable=False,
            server_default=sa.text("'scheduled'"),
        ),
        sa.Column(
            "attempt_count", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
        sa.Column("selected_count", sa.Integer),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(100)),
        sa.Column("failure_class", _failure_class),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("content_ready_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_id", "occurrence_key", name="uq_digest_executions_occurrence"
        ),
        sa.CheckConstraint(
            "digest_count >= 5 AND digest_count <= 20",
            name="ck_digest_executions_count",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_digest_executions_attempt_count"
        ),
        sa.CheckConstraint(
            "selected_count IS NULL OR (selected_count >= 0 AND selected_count <= digest_count)",
            name="ck_digest_executions_selected_count",
        ),
        sa.CheckConstraint(
            "schedule_revision >= 0", name="ck_digest_executions_schedule_revision"
        ),
        sa.CheckConstraint(
            "(status NOT IN ('completed', 'failed', 'delivery_unknown') "
            "OR completed_at IS NOT NULL) "
            "AND (status <> 'retrying' OR "
            "(next_retry_at IS NOT NULL AND failure_class = 'transient')) "
            "AND (status <> 'delivery_unknown' OR "
            "failure_class = 'ambiguous_delivery')",
            name="ck_digest_executions_terminal",
        ),
    )
    op.create_index(
        "ix_digest_executions_status_retry",
        "digest_executions",
        ["status", "next_retry_at"],
    )
    op.create_index(
        "ix_digest_executions_user_scheduled",
        "digest_executions",
        ["user_id", "scheduled_for"],
    )

    # DigestExecutionAttempt
    op.create_table(
        "digest_execution_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("digest_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("phase", _attempt_phase, nullable=False),
        sa.Column("status", _attempt_status, nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "execution_id", "ordinal", name="uq_digest_execution_attempts_ordinal"
        ),
        sa.CheckConstraint("ordinal > 0", name="ck_digest_execution_attempts_ordinal"),
    )

    # DigestItem
    op.create_table(
        "digest_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("digest_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("normalized_articles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "article_analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("article_analyses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "event_group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_groups.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "ranking_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ranking_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("summary", sa.String(1200), nullable=False),
        sa.Column("source_name", sa.String(200), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canonical_url", sa.String(2048), nullable=False),
        sa.Column("score", sa.Numeric(16, 8), nullable=False),
        sa.Column(
            "content_schema_version",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'1.0'"),
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("delivery_part_ordinal", sa.Integer),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "execution_id", "position", name="uq_digest_items_position"
        ),
        sa.UniqueConstraint(
            "execution_id", "article_id", name="uq_digest_items_article"
        ),
        sa.CheckConstraint("position > 0", name="ck_digest_items_position"),
    )

    # DigestDeliveryPart
    op.create_table(
        "digest_delivery_parts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("digest_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("first_item_position", sa.Integer, nullable=False),
        sa.Column("last_item_position", sa.Integer, nullable=False),
        sa.Column(
            "status",
            _delivery_part_status,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("provider_message_id", sa.String(100)),
        sa.Column(
            "attempt_count", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(100)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "execution_id", "ordinal", name="uq_digest_delivery_parts_ordinal"
        ),
        sa.CheckConstraint("ordinal > 0", name="ck_digest_delivery_parts_ordinal"),
        sa.CheckConstraint(
            "last_item_position >= first_item_position",
            name="ck_digest_delivery_parts_range",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_digest_delivery_parts_attempt_count"
        ),
        sa.CheckConstraint(
            "(status <> 'sent' OR "
            "(provider_message_id IS NOT NULL AND sent_at IS NOT NULL)) "
            "AND (status <> 'unknown' OR failure_code IS NOT NULL)",
            name="ck_digest_delivery_parts_state",
        ),
        sa.UniqueConstraint(
            "execution_id",
            "provider_message_id",
            name="uq_digest_delivery_parts_provider_message",
        ),
    )

    # DigestDeliveryHistory
    op.create_table(
        "digest_delivery_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("application_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("digest_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "digest_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("digest_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("normalized_articles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "article_analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("article_analyses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "event_group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_groups.id", ondelete="RESTRICT"),
        ),
        sa.Column("publication_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", _history_outcome, nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "execution_id",
            "article_id",
            name="uq_digest_delivery_history_execution_article",
        ),
    )
    op.create_index(
        "ix_digest_delivery_history_user_article",
        "digest_delivery_history",
        ["user_id", "article_id", "delivered_at"],
    )
    op.create_index(
        "ix_digest_delivery_history_user_event",
        "digest_delivery_history",
        ["user_id", "event_group_id", "delivered_at"],
        postgresql_where=sa.text("event_group_id IS NOT NULL"),
    )

    # DigestMaterialUpdateEvidence
    op.create_table(
        "digest_material_update_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "delivery_history_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("digest_delivery_history.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("normalized_articles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "candidate_analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("article_analyses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "event_group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_groups.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("policy_version", sa.String(100), nullable=False),
        sa.Column("basis", _update_basis, nullable=False),
        sa.Column("outcome", _update_outcome, nullable=False),
        sa.Column("prior_text_hash", sa.String(64), nullable=False),
        sa.Column("candidate_text_hash", sa.String(64), nullable=False),
        sa.Column("content_similarity", sa.Numeric(6, 5)),
        sa.Column("novelty_score", sa.Numeric(5, 4)),
        sa.Column(
            "threshold_snapshot",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "delivery_history_id",
            "candidate_article_id",
            "policy_version",
            name="uq_digest_material_update_evidence_pair_policy",
        ),
        sa.CheckConstraint(
            "length(prior_text_hash) = 64 AND length(candidate_text_hash) = 64",
            name="ck_digest_material_update_evidence_hashes",
        ),
        sa.CheckConstraint(
            "(content_similarity IS NULL OR "
            "(content_similarity >= 0 AND content_similarity <= 1)) AND "
            "(novelty_score IS NULL OR "
            "(novelty_score >= 0 AND novelty_score <= 1))",
            name="ck_digest_material_update_evidence_scores",
        ),
        sa.CheckConstraint(
            "(basis = 'accepted_novelty' AND outcome = 'material_update' "
            "AND novelty_score IS NOT NULL) OR "
            "(basis = 'content_delta' AND outcome = 'material_update' "
            "AND content_similarity IS NOT NULL) OR "
            "(basis = 'insufficient_evidence' AND outcome = 'unchanged' "
            "AND content_similarity IS NULL AND novelty_score IS NULL)",
            name="ck_digest_material_update_evidence_consistency",
        ),
    )

    # Backfill existing users with disabled-safe digest configurations
    op.execute("""
        INSERT INTO digest_configurations (user_id, enabled, digest_count,
            schedule_local_time, timezone_name, schedule_revision,
            created_at, updated_at)
        SELECT id, false, 10, '09:00'::time, 'UTC', 0, now(), now()
        FROM application_users
        WHERE id NOT IN (SELECT user_id FROM digest_configurations)
    """)

    op.create_foreign_key(
        "fk_digest_configurations_last_success_execution",
        "digest_configurations",
        "digest_executions",
        ["last_success_execution_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_digest_configurations_last_failure_execution",
        "digest_configurations",
        "digest_executions",
        ["last_failure_execution_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_table("digest_material_update_evidence")
    op.drop_table("digest_delivery_history")
    op.drop_table("digest_delivery_parts")
    op.drop_table("digest_items")
    op.drop_table("digest_execution_attempts")
    op.drop_table("digest_configurations")
    op.drop_table("digest_executions")

    for name in [
        "digest_material_update_outcome",
        "digest_material_update_basis",
        "digest_history_outcome",
        "digest_delivery_part_status",
        "digest_failure_class",
        "digest_attempt_status",
        "digest_attempt_phase",
        "digest_execution_status",
    ]:
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
