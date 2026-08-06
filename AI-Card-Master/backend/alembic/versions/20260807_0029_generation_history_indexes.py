"""Composite indexes for instant generation-history lookups (plan §16).

Revision ID: 20260807_0029
Revises: 20260807_0028
Create Date: 2026-08-07 14:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260807_0029"
down_revision: str | None = "20260807_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Speed up cabinet history: WHERE user_id ORDER BY created_at DESC."""

    op.create_index(
        "ix_generation_jobs_user_id_created_at",
        "generation_jobs",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_generation_jobs_user_id_status_created_at",
        "generation_jobs",
        ["user_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_generations_user_id_created_at",
        "generations",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop highload history indexes."""

    op.drop_index("ix_generations_user_id_created_at", table_name="generations")
    op.drop_index(
        "ix_generation_jobs_user_id_status_created_at",
        table_name="generation_jobs",
    )
    op.drop_index(
        "ix_generation_jobs_user_id_created_at",
        table_name="generation_jobs",
    )
