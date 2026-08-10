"""Add subject mask key and preserve_subject on generation_jobs.

Revision ID: 20260810_0047
Revises: 20260809_0046
Create Date: 2026-08-10 08:15:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260810_0047"
down_revision: str | None = "20260809_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> Inspector:
    return sa.inspect(op.get_bind())


def _has_column(table: str, column: str) -> bool:
    inspector = _inspector()
    if table not in inspector.get_table_names():
        return False
    return any(item["name"] == column for item in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("generation_jobs", "mask_object_key"):
        op.add_column(
            "generation_jobs",
            sa.Column("mask_object_key", sa.String(length=1024), nullable=True),
        )
    if not _has_column("generation_jobs", "preserve_subject"):
        op.add_column(
            "generation_jobs",
            sa.Column(
                "preserve_subject",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )


def downgrade() -> None:
    if _has_column("generation_jobs", "preserve_subject"):
        op.drop_column("generation_jobs", "preserve_subject")
    if _has_column("generation_jobs", "mask_object_key"):
        op.drop_column("generation_jobs", "mask_object_key")
