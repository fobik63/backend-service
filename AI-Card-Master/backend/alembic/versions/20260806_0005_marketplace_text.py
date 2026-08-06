"""Persist generated marketplace text and engine mode.

Revision ID: 20260806_0005
Revises: 20260806_0004
Create Date: 2026-08-06 03:35:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260806_0005"
down_revision: str | None = "20260806_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add structured WB/Ozon copy and explicit engine mode to generation jobs."""

    op.add_column(
        "generation_jobs",
        sa.Column(
            "engine_mode",
            sa.String(length=32),
            server_default="standard",
            nullable=False,
        ),
    )
    op.add_column(
        "generation_jobs",
        sa.Column(
            "marketplace_text",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove structured WB/Ozon copy and explicit engine mode from generation jobs."""

    op.drop_column("generation_jobs", "marketplace_text")
    op.drop_column("generation_jobs", "engine_mode")
