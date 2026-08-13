"""Add durable question dimension context.

Revision ID: 004_question_dimension_context
Revises: 003_create_personalized_ranking
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004_question_dimension_context"
down_revision: str | None = "003_create_personalized_ranking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "preference_question_contexts",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("application_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dimension_key", sa.String(length=100), nullable=False),
        sa.Column(
            "exposure_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "last_exposed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "exposure_count > 0",
            name="ck_preference_question_contexts_exposure_count",
        ),
        sa.PrimaryKeyConstraint(
            "user_id",
            "dimension_key",
            name="pk_preference_question_contexts",
        ),
    )
    op.create_index(
        "ix_preference_question_contexts_rotation",
        "preference_question_contexts",
        ["user_id", "exposure_count", "last_exposed_at"],
    )

    op.execute(
        """
        INSERT INTO preference_question_contexts (
            user_id,
            dimension_key,
            exposure_count,
            last_exposed_at
        )
        SELECT
            questionnaires.user_id,
            questions.dimension_key,
            COUNT(*)::integer,
            MAX(questionnaires.created_at)
        FROM preference_questions AS questions
        JOIN preference_questionnaires AS questionnaires
          ON questionnaires.id = questions.questionnaire_id
        GROUP BY questionnaires.user_id, questions.dimension_key
        ON CONFLICT (user_id, dimension_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_preference_question_contexts_rotation",
        table_name="preference_question_contexts",
    )
    op.drop_table("preference_question_contexts")
