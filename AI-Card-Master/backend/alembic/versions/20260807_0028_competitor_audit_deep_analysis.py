"""Add Claude deep-analysis columns to competitor_audit_jobs (plan §78).

Revision ID: 20260807_0028
Revises: 20260807_0027
Create Date: 2026-08-07 06:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260807_0028"
down_revision: str | None = "20260807_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store Claude deep-analysis JSON + token usage on audit jobs."""

    op.add_column(
        "competitor_audit_jobs",
        sa.Column(
            "analysis_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "competitor_audit_jobs",
        sa.Column("model_name", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "competitor_audit_jobs",
        sa.Column(
            "input_tokens",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "competitor_audit_jobs",
        sa.Column(
            "output_tokens",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Remove deep-analysis columns."""

    op.drop_column("competitor_audit_jobs", "output_tokens")
    op.drop_column("competitor_audit_jobs", "input_tokens")
    op.drop_column("competitor_audit_jobs", "model_name")
    op.drop_column("competitor_audit_jobs", "analysis_payload")
