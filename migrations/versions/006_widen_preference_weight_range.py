"""Widen preference weight range from ±1 to ±5.

Revision ID: 006_preference_weight_range
Revises: 005_scheduler_digest
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "006_preference_weight_range"
down_revision: str | None = "005_scheduler_digest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_preference_parameters_weight", "preference_parameters"
    )
    op.create_check_constraint(
        "ck_preference_parameters_weight",
        "preference_parameters",
        "weight >= -5.00 AND weight <= 5.00",
    )

    op.drop_constraint(
        "ck_preference_evidence_requested_weight", "preference_evidence"
    )
    op.create_check_constraint(
        "ck_preference_evidence_requested_weight",
        "preference_evidence",
        "requested_weight IS NULL OR (requested_weight >= -5.00 AND requested_weight <= 5.00)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_preference_parameters_weight", "preference_parameters"
    )
    op.create_check_constraint(
        "ck_preference_parameters_weight",
        "preference_parameters",
        "weight >= -1.00 AND weight <= 1.00",
    )

    op.drop_constraint(
        "ck_preference_evidence_requested_weight", "preference_evidence"
    )
    op.create_check_constraint(
        "ck_preference_evidence_requested_weight",
        "preference_evidence",
        "requested_weight IS NULL OR (requested_weight >= -1.00 AND requested_weight <= 1.00)",
    )
