"""BrandDNA table: learned seller style from successful generations.

Revision ID: 20260807_0032
Revises: 20260807_0031
Create Date: 2026-08-07 17:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260807_0032"
down_revision: str | None = "20260807_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create brand_dnas entity for plan §58."""

    op.create_table(
        "brand_dnas",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'empty'"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("midjourney_context", sa.Text(), nullable=True),
        sa.Column("claude_context", sa.Text(), nullable=True),
        sa.Column(
            "dominant_styles",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "palette_keywords",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "lighting_mood",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "composition_keywords",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "category_hints",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "source_job_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "sample_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("last_analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_brand_dnas_user_id"),
    )
    op.create_index("ix_brand_dnas_user_id", "brand_dnas", ["user_id"], unique=False)
    op.create_index("ix_brand_dnas_status", "brand_dnas", ["status"], unique=False)
    op.create_index("ix_brand_dnas_is_active", "brand_dnas", ["is_active"], unique=False)
    op.create_index(
        "ix_brand_dnas_user_status",
        "brand_dnas",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_brand_dnas_status_updated",
        "brand_dnas",
        ["status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "uq_brand_dnas_user_active",
        "brand_dnas",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
    )


def downgrade() -> None:
    """Drop brand_dnas."""

    op.drop_index("uq_brand_dnas_user_active", table_name="brand_dnas")
    op.drop_index("ix_brand_dnas_status_updated", table_name="brand_dnas")
    op.drop_index("ix_brand_dnas_user_status", table_name="brand_dnas")
    op.drop_index("ix_brand_dnas_is_active", table_name="brand_dnas")
    op.drop_index("ix_brand_dnas_status", table_name="brand_dnas")
    op.drop_index("ix_brand_dnas_user_id", table_name="brand_dnas")
    op.drop_table("brand_dnas")
