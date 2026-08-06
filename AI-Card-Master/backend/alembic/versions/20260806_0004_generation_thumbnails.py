"""Persist lightweight generation thumbnails.

Revision ID: 20260806_0004
Revises: 20260806_0003
Create Date: 2026-08-06 03:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260806_0004"
down_revision: str | None = "20260806_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add durable preview metadata to completed generations."""

    op.add_column(
        "generation_jobs",
        sa.Column("thumbnail_object_key", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "generation_jobs",
        sa.Column("thumbnail_mime_type", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "generation_jobs",
        sa.Column("thumbnail_size_bytes", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Remove durable preview metadata."""

    op.drop_column("generation_jobs", "thumbnail_size_bytes")
    op.drop_column("generation_jobs", "thumbnail_mime_type")
    op.drop_column("generation_jobs", "thumbnail_object_key")
