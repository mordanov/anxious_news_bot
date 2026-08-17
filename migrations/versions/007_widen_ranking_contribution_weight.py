"""Widen ranking_parameter_contributions weight/contribution bounds to ±5.

Revision ID: 007_ranking_contribution_weight
Revises: 006_preference_weight_range
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "007_ranking_contribution_weight"
down_revision: str | None = "006_preference_weight_range"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_ranking_parameter_contributions_weight",
        "ranking_parameter_contributions",
    )
    op.create_check_constraint(
        "ck_ranking_parameter_contributions_weight",
        "ranking_parameter_contributions",
        "weight >= -5.00 AND weight <= 5.00",
    )

    op.drop_constraint(
        "ck_ranking_parameter_contributions_contribution",
        "ranking_parameter_contributions",
    )
    op.create_check_constraint(
        "ck_ranking_parameter_contributions_contribution",
        "ranking_parameter_contributions",
        "contribution >= -5.00000000 AND contribution <= 5.00000000",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_ranking_parameter_contributions_weight",
        "ranking_parameter_contributions",
    )
    op.create_check_constraint(
        "ck_ranking_parameter_contributions_weight",
        "ranking_parameter_contributions",
        "weight >= -1.00 AND weight <= 1.00",
    )

    op.drop_constraint(
        "ck_ranking_parameter_contributions_contribution",
        "ranking_parameter_contributions",
    )
    op.create_check_constraint(
        "ck_ranking_parameter_contributions_contribution",
        "ranking_parameter_contributions",
        "contribution >= -1.00000000 AND contribution <= 1.00000000",
    )
