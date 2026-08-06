"""Direct Export tables: encrypted credentials and export history.

Revision ID: 20260806_0012
Revises: 20260806_0011
Create Date: 2026-08-06 22:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0012"
down_revision: str | None = "20260806_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create marketplace_credentials and marketplace_exports tables."""

    op.create_table(
        "marketplace_credentials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "platform",
            name="uq_marketplace_credentials_user_platform",
        ),
    )
    op.create_index(
        "ix_marketplace_credentials_user_id",
        "marketplace_credentials",
        ["user_id"],
    )
    op.create_index(
        "ix_marketplace_credentials_platform",
        "marketplace_credentials",
        ["platform"],
    )
    op.create_index(
        "ix_marketplace_credentials_created_at",
        "marketplace_credentials",
        ["created_at"],
    )
    op.create_index(
        "ix_marketplace_credentials_updated_at",
        "marketplace_credentials",
        ["updated_at"],
    )

    op.create_table(
        "marketplace_exports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generation_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("vendor_code", sa.String(length=64), nullable=False),
        sa.Column("external_task_id", sa.String(length=128), nullable=True),
        sa.Column("external_offer_id", sa.String(length=128), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column(
            "validation_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "request_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["generation_job_id"],
            ["generation_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_marketplace_exports_user_id", "marketplace_exports", ["user_id"])
    op.create_index(
        "ix_marketplace_exports_generation_job_id",
        "marketplace_exports",
        ["generation_job_id"],
    )
    op.create_index(
        "ix_marketplace_exports_platform",
        "marketplace_exports",
        ["platform"],
    )
    op.create_index(
        "ix_marketplace_exports_status",
        "marketplace_exports",
        ["status"],
    )
    op.create_index(
        "ix_marketplace_exports_created_at",
        "marketplace_exports",
        ["created_at"],
    )


def downgrade() -> None:
    """Drop Direct Export tables."""

    op.drop_index("ix_marketplace_exports_created_at", table_name="marketplace_exports")
    op.drop_index("ix_marketplace_exports_status", table_name="marketplace_exports")
    op.drop_index("ix_marketplace_exports_platform", table_name="marketplace_exports")
    op.drop_index(
        "ix_marketplace_exports_generation_job_id",
        table_name="marketplace_exports",
    )
    op.drop_index("ix_marketplace_exports_user_id", table_name="marketplace_exports")
    op.drop_table("marketplace_exports")

    op.drop_index(
        "ix_marketplace_credentials_updated_at",
        table_name="marketplace_credentials",
    )
    op.drop_index(
        "ix_marketplace_credentials_created_at",
        table_name="marketplace_credentials",
    )
    op.drop_index(
        "ix_marketplace_credentials_platform",
        table_name="marketplace_credentials",
    )
    op.drop_index(
        "ix_marketplace_credentials_user_id",
        table_name="marketplace_credentials",
    )
    op.drop_table("marketplace_credentials")
