"""Add utc_offset_hours column to application_users.

Revision ID: 008_add_user_timezone
Revises: 007_ranking_contribution_weight
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "008_add_user_timezone"
down_revision: str | None = "007_ranking_contribution_weight"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "application_users",
        sa.Column(
            "utc_offset_hours",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("application_users", "utc_offset_hours")
