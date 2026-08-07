"""Alembic: durable idempotency_records for coin debit / hold (Redis fallback).

Revision ID: 20260808_0040
Revises: 20260807_0039
Create Date: 2026-08-08 00:56:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260808_0040"
down_revision: str | None = "20260807_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> Inspector:
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _has_index(table: str, index_name: str) -> bool:
    if not _has_table(table):
        return False
    return index_name in {idx["name"] for idx in _inspector().get_indexes(table)}


def upgrade() -> None:
    if not _has_table("idempotency_records"):
        op.create_table(
            "idempotency_records",
            sa.Column("idempotency_key", sa.String(length=255), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("response_code", sa.Integer(), nullable=False),
            sa.Column(
                "response_body",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("idempotency_key"),
        )

    if _has_table("idempotency_records") and not _has_index(
        "idempotency_records", "ix_idempotency_records_user_id"
    ):
        op.create_index(
            "ix_idempotency_records_user_id",
            "idempotency_records",
            ["user_id"],
        )

    if _has_table("idempotency_records") and not _has_index(
        "idempotency_records", "ix_idempotency_records_created_at"
    ):
        op.create_index(
            "ix_idempotency_records_created_at",
            "idempotency_records",
            ["created_at"],
        )


def downgrade() -> None:
    if not _has_table("idempotency_records"):
        return
    if _has_index("idempotency_records", "ix_idempotency_records_created_at"):
        op.drop_index(
            "ix_idempotency_records_created_at",
            table_name="idempotency_records",
        )
    if _has_index("idempotency_records", "ix_idempotency_records_user_id"):
        op.drop_index(
            "ix_idempotency_records_user_id",
            table_name="idempotency_records",
        )
    op.drop_table("idempotency_records")
