"""Create personalized ranking schema.

Revision ID: 003_create_personalized_ranking
Revises: 002_create_user_preferences
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_create_personalized_ranking"
down_revision: str | None = "002_create_user_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

preference_origin = postgresql.ENUM(
    "questionnaire",
    "explicit",
    "inference",
    "system",
    name="preference_origin",
    create_type=False,
)
preference_action = postgresql.ENUM(
    "create",
    "adjust",
    "refine",
    "deactivate",
    "reactivate",
    name="preference_action",
    create_type=False,
)
explicit_request_status = postgresql.ENUM(
    "received",
    "interpreting",
    "validated",
    "applying",
    "stale",
    "applied",
    "failed",
    name="explicit_preference_request_status",
    create_type=False,
)
evaluation_status = postgresql.ENUM(
    "pending",
    "evaluating",
    "complete",
    "incomplete",
    "failed",
    "stale",
    name="article_preference_evaluation_status",
    create_type=False,
)
evaluation_attempt_status = postgresql.ENUM(
    "received",
    "invalid",
    "transient_failure",
    "accepted",
    "failed",
    name="article_preference_evaluation_attempt_status",
    create_type=False,
)
ranking_status = postgresql.ENUM(
    "pending",
    "scoring",
    "diversifying",
    "complete",
    "failed",
    "stale",
    name="ranking_run_status",
    create_type=False,
)
personal_state = postgresql.ENUM(
    "complete",
    "no_active_parameters",
    "all_weights_zero",
    name="ranking_personal_state",
    create_type=False,
)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in (
        explicit_request_status,
        evaluation_status,
        evaluation_attempt_status,
        ranking_status,
        personal_state,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "explicit_preference_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_update_id", sa.BigInteger(), nullable=False),
        sa.Column("normalized_text_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("language_code", sa.String(length=35), nullable=True),
        sa.Column("status", explicit_request_status, nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("base_profile_revision", sa.Integer(), nullable=False),
        sa.Column("interpretation_version", sa.String(length=100), nullable=True),
        sa.Column("proposal_hash", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "base_profile_revision >= 0",
            name="ck_explicit_requests_base_revision",
        ),
        sa.CheckConstraint(
            "length(normalized_text_hash) = 64",
            name="ck_explicit_requests_text_hash",
        ),
        sa.CheckConstraint(
            "proposal_hash IS NULL OR length(proposal_hash) = 64",
            name="ck_explicit_requests_proposal_hash",
        ),
        sa.CheckConstraint(
            "raw_text IS NULL OR length(btrim(raw_text)) > 0",
            name="ck_explicit_requests_raw_text",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["application_users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "telegram_update_id",
            name="uq_explicit_requests_user_update",
        ),
    )
    op.create_index(
        "ix_explicit_requests_status_updated",
        "explicit_preference_requests",
        ["status", "updated_at"],
    )

    op.add_column(
        "preference_update_batches",
        sa.Column("explicit_request_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.alter_column(
        "preference_update_batches",
        "questionnaire_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_preference_update_batches_explicit_request",
        "preference_update_batches",
        "explicit_preference_requests",
        ["explicit_request_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_preference_update_batches_explicit_request",
        "preference_update_batches",
        ["explicit_request_id"],
    )
    op.create_check_constraint(
        "ck_update_batches_single_source",
        "preference_update_batches",
        "((questionnaire_id IS NOT NULL)::integer + (explicit_request_id IS NOT NULL)::integer) = 1",
    )

    op.add_column(
        "preference_change_history",
        sa.Column("explicit_request_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_preference_change_history_explicit_request",
        "preference_change_history",
        "explicit_preference_requests",
        ["explicit_request_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_preference_change_history_source_reference",
        "preference_change_history",
        "(source = 'questionnaire' AND questionnaire_id IS NOT NULL AND explicit_request_id IS NULL) OR "
        "(source = 'explicit' AND questionnaire_id IS NULL AND explicit_request_id IS NOT NULL) OR "
        "(source IN ('inference', 'system') AND questionnaire_id IS NULL AND explicit_request_id IS NULL)",
    )

    op.add_column(
        "preference_change_audit",
        sa.Column("explicit_request_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_preference_change_audit_explicit_request",
        "preference_change_audit",
        "explicit_preference_requests",
        ["explicit_request_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_preference_change_audit_source_reference",
        "preference_change_audit",
        "(source = 'questionnaire' AND questionnaire_id IS NOT NULL AND explicit_request_id IS NULL) OR "
        "(source = 'explicit' AND questionnaire_id IS NULL AND explicit_request_id IS NOT NULL) OR "
        "(source IN ('inference', 'system') AND questionnaire_id IS NULL AND explicit_request_id IS NULL)",
    )

    op.create_table(
        "preference_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parameter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", preference_origin, nullable=False),
        sa.Column("explicit_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("questionnaire_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", preference_action, nullable=False),
        sa.Column("requested_weight", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("reason_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(source = 'questionnaire' AND questionnaire_id IS NOT NULL AND explicit_request_id IS NULL) OR "
            "(source = 'explicit' AND questionnaire_id IS NULL AND explicit_request_id IS NOT NULL) OR "
            "(source IN ('inference', 'system') AND questionnaire_id IS NULL AND explicit_request_id IS NULL)",
            name="ck_preference_evidence_source_reference",
        ),
        sa.CheckConstraint(
            "length(reason_hash) = 64",
            name="ck_preference_evidence_reason_hash",
        ),
        sa.CheckConstraint(
            "requested_weight IS NULL OR (requested_weight >= -1.00 AND requested_weight <= 1.00)",
            name="ck_preference_evidence_requested_weight",
        ),
        sa.ForeignKeyConstraint(
            ["parameter_id"], ["preference_parameters.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["preference_profiles.user_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["explicit_request_id"],
            ["explicit_preference_requests.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["questionnaire_id"],
            ["preference_questionnaires.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_preference_evidence_parameter_created",
        "preference_evidence",
        ["parameter_id", "created_at"],
    )

    op.execute(
        """
        INSERT INTO preference_evidence (
            id,
            parameter_id,
            user_id,
            source,
            explicit_request_id,
            questionnaire_id,
            action,
            requested_weight,
            active,
            reason_hash,
            created_at
        )
        SELECT
            history.id,
            history.parameter_id,
            batch.user_id,
            history.source::text::preference_origin,
            history.explicit_request_id,
            history.questionnaire_id,
            history.action,
            CASE
                WHEN history.action IN ('create', 'adjust') THEN
                    NULLIF(history.new_state ->> 'weight', '')::numeric(3, 2)
                ELSE NULL
            END,
            COALESCE((history.new_state ->> 'active')::boolean, true),
            audit.reason_hash,
            history.changed_at
        FROM preference_change_history AS history
        JOIN preference_update_batches AS batch ON batch.id = history.batch_id
        JOIN preference_change_audit AS audit ON audit.id = history.id
        WHERE history.questionnaire_id IS NOT NULL
        """
    )

    op.create_table(
        "article_preference_evaluation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_revision", sa.Integer(), nullable=False),
        sa.Column("parameter_set_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("evaluator_name", sa.String(length=100), nullable=False),
        sa.Column("evaluator_version", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("status", evaluation_status, nullable=False),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("accepted_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "profile_revision >= 0",
            name="ck_article_preference_evaluation_runs_profile_revision",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_article_preference_evaluation_runs_attempt_count",
        ),
        sa.CheckConstraint(
            "length(parameter_set_hash) = 64",
            name="ck_article_preference_evaluation_runs_parameter_set_hash",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["preference_profiles.user_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["article_id"], ["normalized_articles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["article_analysis_id"], ["article_analyses.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "article_id",
            "article_analysis_id",
            "profile_revision",
            "parameter_set_hash",
            "schema_version",
            "evaluator_name",
            "evaluator_version",
            "prompt_version",
            name="uq_article_preference_evaluation_runs_version",
        ),
        sa.UniqueConstraint(
            "accepted_attempt_id",
            name="uq_article_preference_evaluation_runs_accepted_attempt",
        ),
    )
    op.create_index(
        "ix_article_preference_evaluation_runs_user_article_status",
        "article_preference_evaluation_runs",
        ["user_id", "article_id", "status"],
    )
    op.create_index(
        "ix_article_preference_evaluation_runs_status_updated",
        "article_preference_evaluation_runs",
        ["status", "updated_at"],
    )

    op.create_table(
        "article_preference_evaluation_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("response_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "raw_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("status", evaluation_attempt_status, nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "ordinal > 0",
            name="ck_article_preference_evaluation_attempts_ordinal",
        ),
        sa.CheckConstraint(
            "response_hash IS NULL OR length(response_hash) = 64",
            name="ck_article_preference_evaluation_attempts_response_hash",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["article_preference_evaluation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "ordinal",
            name="uq_article_preference_evaluation_attempts_run_ordinal",
        ),
    )
    op.create_index(
        "ix_article_preference_evaluation_attempts_status_completed",
        "article_preference_evaluation_attempts",
        ["status", "completed_at"],
    )
    op.create_foreign_key(
        "fk_article_preference_evaluation_runs_accepted_attempt",
        "article_preference_evaluation_runs",
        "article_preference_evaluation_attempts",
        ["accepted_attempt_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "article_parameter_relevances",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evaluation_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parameter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parameter_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("relevance", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(parameter_snapshot_hash) = 64",
            name="ck_article_parameter_relevances_snapshot_hash",
        ),
        sa.CheckConstraint(
            "relevance >= -1.0000 AND relevance <= 1.0000",
            name="ck_article_parameter_relevances_relevance",
        ),
        sa.CheckConstraint(
            "length(btrim(reason_code)) > 0",
            name="ck_article_parameter_relevances_reason_code",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"],
            ["article_preference_evaluation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parameter_id"],
            ["preference_parameters.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_run_id",
            "parameter_id",
            name="uq_article_parameter_relevances_run_parameter",
        ),
    )
    op.create_index(
        "ix_article_parameter_relevances_run",
        "article_parameter_relevances",
        ["evaluation_run_id"],
    )

    op.create_table(
        "ranking_configuration_snapshots",
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "personal_coefficient", sa.Numeric(precision=6, scale=5), nullable=False
        ),
        sa.Column(
            "importance_coefficient", sa.Numeric(precision=6, scale=5), nullable=False
        ),
        sa.Column(
            "freshness_coefficient", sa.Numeric(precision=6, scale=5), nullable=False
        ),
        sa.Column(
            "quality_coefficient", sa.Numeric(precision=6, scale=5), nullable=False
        ),
        sa.Column(
            "novelty_coefficient", sa.Numeric(precision=6, scale=5), nullable=False
        ),
        sa.Column("freshness_horizon_seconds", sa.Integer(), nullable=False),
        sa.Column("future_tolerance_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "minimum_source_quality", sa.Numeric(precision=6, scale=5), nullable=False
        ),
        sa.Column("maximum_candidate_count", sa.Integer(), nullable=False),
        sa.Column("event_cap", sa.Integer(), nullable=False),
        sa.Column("topic_cap", sa.Integer(), nullable=False),
        sa.Column("source_cap", sa.Integer(), nullable=False),
        sa.Column(
            "explicit_weight_threshold",
            sa.Numeric(precision=3, scale=2),
            nullable=False,
        ),
        sa.Column(
            "explicit_relevance_threshold",
            sa.Numeric(precision=5, scale=4),
            nullable=False,
        ),
        sa.Column("explanation_contribution_limit", sa.Integer(), nullable=False),
        sa.Column("tie_policy_version", sa.String(length=100), nullable=False),
        sa.Column("retention_policy_version", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(configuration_hash) = 64",
            name="ck_ranking_configuration_snapshots_hash",
        ),
        sa.CheckConstraint(
            "personal_coefficient >= 0 AND personal_coefficient <= 1 AND "
            "importance_coefficient >= 0 AND importance_coefficient <= 1 AND "
            "freshness_coefficient >= 0 AND freshness_coefficient <= 1 AND "
            "quality_coefficient >= 0 AND quality_coefficient <= 1 AND "
            "novelty_coefficient >= 0 AND novelty_coefficient <= 1",
            name="ck_ranking_configuration_snapshots_coefficients",
        ),
        sa.CheckConstraint(
            "personal_coefficient + importance_coefficient + freshness_coefficient + quality_coefficient + novelty_coefficient = 1.00000",
            name="ck_ranking_configuration_snapshots_coefficient_sum",
        ),
        sa.CheckConstraint(
            "personal_coefficient >= 0.40000",
            name="ck_ranking_configuration_snapshots_personal_floor",
        ),
        sa.CheckConstraint(
            "freshness_horizon_seconds > 0",
            name="ck_ranking_configuration_snapshots_freshness_horizon",
        ),
        sa.CheckConstraint(
            "future_tolerance_seconds >= 0",
            name="ck_ranking_configuration_snapshots_future_tolerance",
        ),
        sa.CheckConstraint(
            "minimum_source_quality >= 0 AND minimum_source_quality <= 1",
            name="ck_ranking_configuration_snapshots_minimum_source_quality",
        ),
        sa.CheckConstraint(
            "maximum_candidate_count > 0 AND maximum_candidate_count <= 500",
            name="ck_ranking_configuration_snapshots_candidate_count",
        ),
        sa.CheckConstraint(
            "event_cap > 0 AND topic_cap > 0 AND source_cap > 0",
            name="ck_ranking_configuration_snapshots_caps",
        ),
        sa.CheckConstraint(
            "explicit_weight_threshold >= 0 AND explicit_weight_threshold <= 1",
            name="ck_ranking_configuration_snapshots_weight_threshold",
        ),
        sa.CheckConstraint(
            "explicit_relevance_threshold >= 0 AND explicit_relevance_threshold <= 1",
            name="ck_ranking_configuration_snapshots_relevance_threshold",
        ),
        sa.CheckConstraint(
            "explanation_contribution_limit > 0 AND explanation_contribution_limit <= 10",
            name="ck_ranking_configuration_snapshots_explanation_limit",
        ),
        sa.PrimaryKeyConstraint("version"),
        sa.UniqueConstraint(
            "configuration_hash",
            name="uq_ranking_configuration_snapshots_hash",
        ),
    )

    op.create_table(
        "ranking_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", sa.String(length=200), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_revision", sa.Integer(), nullable=False),
        sa.Column("candidate_set_hash", sa.String(length=64), nullable=False),
        sa.Column("configuration_version", sa.String(length=100), nullable=False),
        sa.Column("ranking_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("status", ranking_status, nullable=False),
        sa.Column(
            "selected_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "excluded_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "selected_cap_vector",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "unsatisfied_limits",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "profile_revision >= 0",
            name="ck_ranking_runs_profile_revision",
        ),
        sa.CheckConstraint(
            "length(candidate_set_hash) = 64",
            name="ck_ranking_runs_candidate_set_hash",
        ),
        sa.CheckConstraint(
            "requested_count > 0",
            name="ck_ranking_runs_requested_count",
        ),
        sa.CheckConstraint(
            "selected_count >= 0 AND excluded_count >= 0",
            name="ck_ranking_runs_counts",
        ),
        sa.CheckConstraint(
            "selected_count <= requested_count",
            name="ck_ranking_runs_selected_count",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["preference_profiles.user_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["configuration_version"],
            ["ranking_configuration_snapshots.version"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "request_id",
            name="uq_ranking_runs_user_request",
        ),
        sa.UniqueConstraint(
            "user_id",
            "profile_revision",
            "candidate_set_hash",
            "configuration_version",
            "ranking_at",
            "requested_count",
            name="uq_ranking_runs_snapshot",
        ),
    )
    op.create_index(
        "ix_ranking_runs_user_status_created",
        "ranking_runs",
        ["user_id", "status", "created_at"],
    )

    op.create_table(
        "article_ranking_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ranking_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_analysis_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evaluation_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic_key", sa.String(length=160), nullable=True),
        sa.Column(
            "personal_numerator", sa.Numeric(precision=28, scale=8), nullable=False
        ),
        sa.Column(
            "personal_denominator", sa.Numeric(precision=28, scale=8), nullable=False
        ),
        sa.Column("personal_state", personal_state, nullable=False),
        sa.Column("personal_signed", sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column("personal_factor", sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column("importance", sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column("freshness", sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column("quality", sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column("novelty", sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column(
            "unrounded_score", sa.Numeric(precision=28, scale=16), nullable=False
        ),
        sa.Column("final_score", sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("eligibility_reason", sa.String(length=100), nullable=False),
        sa.Column("explicit_protected", sa.Boolean(), nullable=False),
        sa.Column("explicit_veto", sa.Boolean(), nullable=False),
        sa.Column("initial_position", sa.Integer(), nullable=True),
        sa.Column("final_position", sa.Integer(), nullable=True),
        sa.Column("selection_reason", sa.String(length=100), nullable=False),
        sa.Column("diversity_pass", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "personal_denominator >= 0",
            name="ck_article_ranking_records_personal_denominator",
        ),
        sa.CheckConstraint(
            "personal_signed >= -1.00000000 AND personal_signed <= 1.00000000",
            name="ck_article_ranking_records_personal_signed",
        ),
        sa.CheckConstraint(
            "personal_factor >= 0 AND personal_factor <= 1",
            name="ck_article_ranking_records_personal_factor",
        ),
        sa.CheckConstraint(
            "importance >= 0 AND importance <= 1 AND freshness >= 0 AND freshness <= 1 AND quality >= 0 AND quality <= 1 AND novelty >= 0 AND novelty <= 1",
            name="ck_article_ranking_records_factors",
        ),
        sa.CheckConstraint(
            "unrounded_score >= 0 AND unrounded_score <= 1 AND final_score >= 0 AND final_score <= 1",
            name="ck_article_ranking_records_scores",
        ),
        sa.CheckConstraint(
            "initial_position IS NULL OR initial_position > 0",
            name="ck_article_ranking_records_initial_position",
        ),
        sa.CheckConstraint(
            "final_position IS NULL OR final_position > 0",
            name="ck_article_ranking_records_final_position",
        ),
        sa.CheckConstraint(
            "final_position IS NULL OR eligible",
            name="ck_article_ranking_records_final_position_requires_eligibility",
        ),
        sa.CheckConstraint(
            "(personal_state = 'complete' AND "
            "(evaluation_run_id IS NOT NULL OR NOT eligible)) OR "
            "personal_state IN ('no_active_parameters', 'all_weights_zero')",
            name="ck_article_ranking_records_personal_state_evaluation",
        ),
        sa.ForeignKeyConstraint(
            ["ranking_run_id"], ["ranking_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["article_id"], ["normalized_articles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["article_analysis_id"], ["article_analyses.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"],
            ["article_preference_evaluation_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_group_id"], ["event_groups.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["news_sources.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ranking_run_id",
            "article_id",
            name="uq_article_ranking_records_run_article",
        ),
    )
    op.create_index(
        "ix_article_ranking_records_run_score",
        "article_ranking_records",
        ["ranking_run_id", "eligible", "final_score"],
    )

    op.create_table(
        "ranking_parameter_contributions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_ranking_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parameter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parameter_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("parameter_name", sa.String(length=160), nullable=False),
        sa.Column("parameter_origin", preference_origin, nullable=False),
        sa.Column("effective_authority", preference_origin, nullable=False),
        sa.Column("weight", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("relevance", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("contribution", sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column("explanation_ordinal", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "length(parameter_snapshot_hash) = 64",
            name="ck_ranking_parameter_contributions_snapshot_hash",
        ),
        sa.CheckConstraint(
            "length(btrim(parameter_name)) > 0",
            name="ck_ranking_parameter_contributions_parameter_name",
        ),
        sa.CheckConstraint(
            "weight >= -1.00 AND weight <= 1.00",
            name="ck_ranking_parameter_contributions_weight",
        ),
        sa.CheckConstraint(
            "relevance >= -1.0000 AND relevance <= 1.0000",
            name="ck_ranking_parameter_contributions_relevance",
        ),
        sa.CheckConstraint(
            "contribution >= -1.00000000 AND contribution <= 1.00000000",
            name="ck_ranking_parameter_contributions_contribution",
        ),
        sa.CheckConstraint(
            "explanation_ordinal IS NULL OR explanation_ordinal > 0",
            name="ck_ranking_parameter_contributions_explanation_ordinal",
        ),
        sa.ForeignKeyConstraint(
            ["article_ranking_id"], ["article_ranking_records.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parameter_id"], ["preference_parameters.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "article_ranking_id",
            "parameter_id",
            name="uq_ranking_parameter_contributions_article_parameter",
        ),
    )
    op.create_index(
        "ix_ranking_parameter_contributions_explanation",
        "ranking_parameter_contributions",
        ["article_ranking_id", "explanation_ordinal"],
        unique=True,
        postgresql_where=sa.text("explanation_ordinal IS NOT NULL"),
    )

    op.create_table(
        "ranking_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ranking_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_revision", sa.Integer(), nullable=False),
        sa.Column("configuration_version", sa.String(length=100), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("factor_hash", sa.String(length=64), nullable=False),
        sa.Column("contribution_hash", sa.String(length=64), nullable=False),
        sa.Column("score_hash", sa.String(length=64), nullable=False),
        sa.Column("selection_hash", sa.String(length=64), nullable=False),
        sa.Column("final_score", sa.Numeric(precision=10, scale=8), nullable=False),
        sa.Column("final_position", sa.Integer(), nullable=True),
        sa.Column("ranked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "profile_revision >= 0",
            name="ck_ranking_audit_profile_revision",
        ),
        sa.CheckConstraint(
            "length(input_hash) = 64",
            name="ck_ranking_audit_input_hash",
        ),
        sa.CheckConstraint(
            "length(factor_hash) = 64",
            name="ck_ranking_audit_factor_hash",
        ),
        sa.CheckConstraint(
            "length(contribution_hash) = 64",
            name="ck_ranking_audit_contribution_hash",
        ),
        sa.CheckConstraint(
            "length(score_hash) = 64",
            name="ck_ranking_audit_score_hash",
        ),
        sa.CheckConstraint(
            "length(selection_hash) = 64",
            name="ck_ranking_audit_selection_hash",
        ),
        sa.CheckConstraint(
            "final_score >= 0 AND final_score <= 1",
            name="ck_ranking_audit_final_score",
        ),
        sa.CheckConstraint(
            "final_position IS NULL OR final_position > 0",
            name="ck_ranking_audit_final_position",
        ),
        sa.ForeignKeyConstraint(
            ["ranking_run_id"], ["ranking_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["preference_profiles.user_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["article_id"], ["normalized_articles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["configuration_version"],
            ["ranking_configuration_snapshots.version"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ranking_audit_user_ranked",
        "ranking_audit",
        ["user_id", "ranked_at"],
    )

    op.execute(
        """
        CREATE FUNCTION reject_immutable_row_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME;
        END;
        $$
        """
    )
    for table_name, trigger_name in (
        ("preference_evidence", "preference_evidence_immutable"),
        (
            "article_preference_evaluation_attempts",
            "article_preference_evaluation_attempts_immutable",
        ),
        ("article_parameter_relevances", "article_parameter_relevances_immutable"),
        (
            "ranking_parameter_contributions",
            "ranking_parameter_contributions_immutable",
        ),
        ("ranking_audit", "ranking_audit_immutable"),
    ):
        op.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_immutable_row_mutation()
            """
        )


def downgrade() -> None:
    for table_name, trigger_name in (
        ("ranking_audit", "ranking_audit_immutable"),
        (
            "ranking_parameter_contributions",
            "ranking_parameter_contributions_immutable",
        ),
        ("article_parameter_relevances", "article_parameter_relevances_immutable"),
        (
            "article_preference_evaluation_attempts",
            "article_preference_evaluation_attempts_immutable",
        ),
        ("preference_evidence", "preference_evidence_immutable"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}")
    op.execute("DROP FUNCTION IF EXISTS reject_immutable_row_mutation()")

    op.drop_index("ix_ranking_audit_user_ranked", table_name="ranking_audit")
    op.drop_table("ranking_audit")
    op.drop_index(
        "ix_ranking_parameter_contributions_explanation",
        table_name="ranking_parameter_contributions",
    )
    op.drop_table("ranking_parameter_contributions")
    op.drop_index(
        "ix_article_ranking_records_run_score",
        table_name="article_ranking_records",
    )
    op.drop_table("article_ranking_records")
    op.drop_index("ix_ranking_runs_user_status_created", table_name="ranking_runs")
    op.drop_table("ranking_runs")
    op.drop_table("ranking_configuration_snapshots")
    op.drop_index(
        "ix_article_parameter_relevances_run",
        table_name="article_parameter_relevances",
    )
    op.drop_table("article_parameter_relevances")
    op.drop_constraint(
        "fk_article_preference_evaluation_runs_accepted_attempt",
        "article_preference_evaluation_runs",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_article_preference_evaluation_attempts_status_completed",
        table_name="article_preference_evaluation_attempts",
    )
    op.drop_table("article_preference_evaluation_attempts")
    op.drop_index(
        "ix_article_preference_evaluation_runs_status_updated",
        table_name="article_preference_evaluation_runs",
    )
    op.drop_index(
        "ix_article_preference_evaluation_runs_user_article_status",
        table_name="article_preference_evaluation_runs",
    )
    op.drop_table("article_preference_evaluation_runs")

    op.drop_index(
        "ix_preference_evidence_parameter_created",
        table_name="preference_evidence",
    )
    op.drop_table("preference_evidence")

    op.execute(
        "DELETE FROM preference_change_audit WHERE source = 'explicit' OR explicit_request_id IS NOT NULL"
    )
    op.execute(
        "DELETE FROM preference_change_history WHERE source = 'explicit' OR explicit_request_id IS NOT NULL"
    )
    op.execute(
        "DELETE FROM preference_update_batches WHERE explicit_request_id IS NOT NULL"
    )
    op.execute("DELETE FROM explicit_preference_requests")

    op.drop_constraint(
        "ck_preference_change_audit_source_reference",
        "preference_change_audit",
        type_="check",
    )
    op.drop_constraint(
        "fk_preference_change_audit_explicit_request",
        "preference_change_audit",
        type_="foreignkey",
    )
    op.drop_column("preference_change_audit", "explicit_request_id")

    op.drop_constraint(
        "ck_preference_change_history_source_reference",
        "preference_change_history",
        type_="check",
    )
    op.drop_constraint(
        "fk_preference_change_history_explicit_request",
        "preference_change_history",
        type_="foreignkey",
    )
    op.drop_column("preference_change_history", "explicit_request_id")

    op.drop_constraint(
        "ck_update_batches_single_source",
        "preference_update_batches",
        type_="check",
    )
    op.drop_constraint(
        "uq_preference_update_batches_explicit_request",
        "preference_update_batches",
        type_="unique",
    )
    op.drop_constraint(
        "fk_preference_update_batches_explicit_request",
        "preference_update_batches",
        type_="foreignkey",
    )
    op.drop_column("preference_update_batches", "explicit_request_id")
    op.alter_column(
        "preference_update_batches",
        "questionnaire_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )

    op.drop_index(
        "ix_explicit_requests_status_updated",
        table_name="explicit_preference_requests",
    )
    op.drop_table("explicit_preference_requests")

    bind = op.get_bind()
    for enum_type in (
        personal_state,
        ranking_status,
        evaluation_attempt_status,
        evaluation_status,
        explicit_request_status,
    ):
        enum_type.drop(bind, checkfirst=True)
