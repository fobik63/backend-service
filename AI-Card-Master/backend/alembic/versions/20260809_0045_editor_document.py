"""Persist complete versioned multi-page editor documents.

Revision ID: 20260809_0045
Revises: 20260808_0044
Create Date: 2026-08-09 02:55:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260809_0045"
down_revision: str | None = "20260808_0044"
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
    if not _has_column("user_saved_designs", "editor_document_data"):
        op.add_column(
            "user_saved_designs",
            sa.Column(
                "editor_document_data",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
        )


def downgrade() -> None:
    if _has_column("user_saved_designs", "editor_document_data"):
        op.drop_column("user_saved_designs", "editor_document_data")
