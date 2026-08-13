"""Create user preference tuning schema.

Revision ID: 002_create_user_preferences
Revises: 001_create_news_aggregation
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002_create_user_preferences"
down_revision: str | None = "001_create_news_aggregation"
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
questionnaire_status = postgresql.ENUM(
    "generating",
    "answering",
    "answers_complete",
    "interpreting",
    "applying",
    "applied",
    "failed",
    name="questionnaire_status",
    create_type=False,
)
batch_status = postgresql.ENUM(
    "validated",
    "applied",
    "stale",
    "rejected",
    name="preference_update_batch_status",
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
history_source = postgresql.ENUM(
    "questionnaire",
    "explicit",
    "inference",
    "system",
    name="preference_history_source",
    create_type=False,
)
audit_action = postgresql.ENUM(
    "create",
    "adjust",
    "refine",
    "deactivate",
    "reactivate",
    name="preference_audit_action",
    create_type=False,
)
audit_source = postgresql.ENUM(
    "questionnaire",
    "explicit",
    "inference",
    "system",
    name="preference_audit_source",
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
        preference_origin,
        questionnaire_status,
        batch_status,
        preference_action,
        history_source,
        audit_action,
        audit_source,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "application_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("language_code", sa.String(length=35), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_user_id"),
    )
    op.create_table(
        "preference_profiles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "revision", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        *_timestamps(),
        sa.CheckConstraint("revision >= 0", name="ck_preference_profiles_revision"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["application_users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "preference_parameters",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("semantic_key", sa.String(length=160), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evaluation_instructions", sa.Text(), nullable=False),
        sa.Column("weight", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("origin", preference_origin, nullable=False),
        sa.Column(
            "active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "length(btrim(name)) > 0 AND length(btrim(description)) > 0 "
            "AND length(btrim(evaluation_instructions)) > 0",
            name="ck_preference_parameters_text",
        ),
        sa.CheckConstraint(
            "weight >= -1.00 AND weight <= 1.00",
            name="ck_preference_parameters_weight",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["preference_profiles.user_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "semantic_key", name="uq_preference_parameters_user_semantic"
        ),
    )
    op.create_index(
        "ix_preference_parameters_user_active",
        "preference_parameters",
        ["user_id", "active"],
    )
    op.create_index(
        "ix_preference_parameters_name_trgm",
        "preference_parameters",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_table(
        "preference_questionnaires",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", questionnaire_status, nullable=False),
        sa.Column(
            "schema_version",
            sa.String(length=20),
            server_default=sa.text("'1.0'"),
            nullable=False,
        ),
        sa.Column("profile_revision", sa.Integer(), nullable=False),
        sa.Column("generation_context_hash", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "profile_revision >= 0", name="ck_questionnaires_profile_revision"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["application_users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_questionnaires_user_active",
        "preference_questionnaires",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('generating', 'answering', 'answers_complete', "
            "'interpreting', 'applying')"
        ),
    )
    op.create_index(
        "ix_questionnaires_status_updated",
        "preference_questionnaires",
        ["status", "updated_at"],
    )
    op.create_table(
        "preference_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("questionnaire_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("dimension_key", sa.String(length=100), nullable=False),
        sa.Column("text", sa.String(length=160), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 10", name="ck_questions_ordinal"),
        sa.CheckConstraint("length(btrim(text)) > 0", name="ck_questions_text"),
        sa.ForeignKeyConstraint(
            ["questionnaire_id"], ["preference_questionnaires.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "questionnaire_id", "ordinal", name="uq_questions_questionnaire_ordinal"
        ),
    )
    op.create_table(
        "preference_question_options",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("normalized_label", sa.String(length=80), nullable=False),
        sa.Column("callback_token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 4", name="ck_options_ordinal"),
        sa.CheckConstraint("length(btrim(label)) > 0", name="ck_options_label"),
        sa.ForeignKeyConstraint(
            ["question_id"], ["preference_questions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "question_id", name="uq_options_id_question"),
        sa.UniqueConstraint(
            "question_id", "ordinal", name="uq_options_question_ordinal"
        ),
        sa.UniqueConstraint(
            "question_id", "normalized_label", name="uq_options_question_label"
        ),
    )
    op.create_index(
        "ix_options_callback_token_hash",
        "preference_question_options",
        ["callback_token_hash"],
        unique=True,
    )
    op.create_table(
        "preference_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("option_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["question_id"], ["preference_questions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["option_id", "question_id"],
            [
                "preference_question_options.id",
                "preference_question_options.question_id",
            ],
            ondelete="CASCADE",
            name="fk_answers_option_question",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_id"),
    )
    op.create_table(
        "preference_update_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("questionnaire_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("base_profile_revision", sa.Integer(), nullable=False),
        sa.Column("resulting_profile_revision", sa.Integer(), nullable=True),
        sa.Column("proposal_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "change_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("history_digest", sa.String(length=64), nullable=True),
        sa.Column("status", batch_status, nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "base_profile_revision >= 0", name="ck_update_batches_base_revision"
        ),
        sa.CheckConstraint(
            "resulting_profile_revision IS NULL OR "
            "resulting_profile_revision = base_profile_revision + 1",
            name="ck_update_batches_result_revision",
        ),
        sa.CheckConstraint("change_count >= 0", name="ck_update_batches_change_count"),
        sa.ForeignKeyConstraint(
            ["questionnaire_id"], ["preference_questionnaires.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["preference_profiles.user_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("questionnaire_id"),
    )
    op.create_table(
        "preference_change_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parameter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", preference_action, nullable=False),
        sa.Column("source", history_source, nullable=False),
        sa.Column("questionnaire_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "previous_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("new_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_history_reason"),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["preference_update_batches.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parameter_id"], ["preference_parameters.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["questionnaire_id"], ["preference_questionnaires.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_id",
            "parameter_id",
            "action",
            name="uq_preference_history_batch_parameter_action",
        ),
    )
    op.create_table(
        "preference_change_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parameter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", audit_action, nullable=False),
        sa.Column("source", audit_source, nullable=False),
        sa.Column("questionnaire_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("previous_state_hash", sa.String(length=64), nullable=True),
        sa.Column("new_state_hash", sa.String(length=64), nullable=False),
        sa.Column("reason_hash", sa.String(length=64), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["preference_update_batches.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["parameter_id"], ["preference_parameters.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["questionnaire_id"], ["preference_questionnaires.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_id",
            "parameter_id",
            "action",
            name="uq_preference_audit_batch_parameter_action",
        ),
    )
    op.execute(
        """
        CREATE FUNCTION reject_preference_audit_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'preference change audit rows are immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER preference_change_audit_immutable
        BEFORE UPDATE OR DELETE ON preference_change_audit
        FOR EACH ROW EXECUTE FUNCTION reject_preference_audit_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_preference_origin_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.origin IS DISTINCT FROM OLD.origin THEN
                RAISE EXCEPTION 'preference parameter origin is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER preference_parameter_origin_immutable
        BEFORE UPDATE ON preference_parameters
        FOR EACH ROW EXECUTE FUNCTION reject_preference_origin_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS preference_parameter_origin_immutable "
        "ON preference_parameters"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_preference_origin_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS preference_change_audit_immutable "
        "ON preference_change_audit"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_preference_audit_mutation()")
    op.drop_table("preference_change_audit")
    op.drop_table("preference_change_history")
    op.drop_table("preference_update_batches")
    op.drop_table("preference_answers")
    op.drop_index(
        "ix_options_callback_token_hash", table_name="preference_question_options"
    )
    op.drop_table("preference_question_options")
    op.drop_table("preference_questions")
    op.drop_index(
        "ix_questionnaires_status_updated", table_name="preference_questionnaires"
    )
    op.drop_index(
        "uq_questionnaires_user_active", table_name="preference_questionnaires"
    )
    op.drop_table("preference_questionnaires")
    op.drop_index(
        "ix_preference_parameters_name_trgm", table_name="preference_parameters"
    )
    op.drop_index(
        "ix_preference_parameters_user_active", table_name="preference_parameters"
    )
    op.drop_table("preference_parameters")
    op.drop_table("preference_profiles")
    op.drop_table("application_users")
    bind = op.get_bind()
    for enum_type in (
        audit_source,
        audit_action,
        history_source,
        preference_action,
        batch_status,
        questionnaire_status,
        preference_origin,
    ):
        enum_type.drop(bind, checkfirst=True)
