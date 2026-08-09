"""Add encrypted seller API fields on users and marketplace_publications.

Revision ID: 20260809_0046
Revises: 20260809_0045
Create Date: 2026-08-09 03:50:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260809_0046"
down_revision: str | None = "20260809_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table: str) -> bool:
    return table in _inspector().get_table_names()


def _has_column(table: str, column: str) -> bool:
    inspector = _inspector()
    if table not in inspector.get_table_names():
        return False
    return any(item["name"] == column for item in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("users", "wb_api_token_ciphertext"):
        op.add_column("users", sa.Column("wb_api_token_ciphertext", sa.Text(), nullable=True))
    if not _has_column("users", "ozon_client_id_ciphertext"):
        op.add_column(
            "users", sa.Column("ozon_client_id_ciphertext", sa.Text(), nullable=True)
        )
    if not _has_column("users", "ozon_api_key_ciphertext"):
        op.add_column(
            "users", sa.Column("ozon_api_key_ciphertext", sa.Text(), nullable=True)
        )
    if not _has_column("users", "marketplace_credentials_updated_at"):
        op.add_column(
            "users",
            sa.Column(
                "marketplace_credentials_updated_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )

    if not _has_table("marketplace_publications"):
        op.create_table(
            "marketplace_publications",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("platform", sa.String(length=16), nullable=False),
            sa.Column("product_id", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("message", sa.String(length=1000), nullable=False),
            sa.Column("external_task_id", sa.String(length=128), nullable=True),
            sa.Column(
                "error_logs",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "request_payload",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index(
            "ix_marketplace_publications_user_id",
            "marketplace_publications",
            ["user_id"],
        )
        op.create_index(
            "ix_marketplace_publications_platform",
            "marketplace_publications",
            ["platform"],
        )
        op.create_index(
            "ix_marketplace_publications_product_id",
            "marketplace_publications",
            ["product_id"],
        )
        op.create_index(
            "ix_marketplace_publications_status",
            "marketplace_publications",
            ["status"],
        )
        op.create_index(
            "ix_marketplace_publications_created_at",
            "marketplace_publications",
            ["created_at"],
        )


def downgrade() -> None:
    if _has_table("marketplace_publications"):
        op.drop_table("marketplace_publications")

    for column in (
        "marketplace_credentials_updated_at",
        "ozon_api_key_ciphertext",
        "ozon_client_id_ciphertext",
        "wb_api_token_ciphertext",
    ):
        if _has_column("users", column):
            op.drop_column("users", column)
