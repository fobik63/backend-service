"""Generation post-processing tiers and multi-credit debits.

Revision ID: 20260806_0008
Revises: 20260806_0007
Create Date: 2026-08-06 22:05:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0008"
down_revision: str | None = "20260806_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store user-selected post-processing tier and exact charged credits."""

    op.add_column(
        "generation_jobs",
        sa.Column(
            "post_processing_mode",
            sa.String(length=32),
            server_default=sa.text("'fast'"),
            nullable=False,
        ),
    )
    op.add_column(
        "generation_jobs",
        sa.Column(
            "coins_charged",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_generation_jobs_coins_charged_non_negative",
        "generation_jobs",
        "coins_charged >= 0",
    )


def downgrade() -> None:
    """Remove post-processing tier metadata."""

    op.drop_constraint(
        "ck_generation_jobs_coins_charged_non_negative",
        "generation_jobs",
        type_="check",
    )
    op.drop_column("generation_jobs", "coins_charged")
    op.drop_column("generation_jobs", "post_processing_mode")
