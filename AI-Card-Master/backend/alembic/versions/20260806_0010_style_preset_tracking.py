"""Internal style preset selection tracking for analytics.

Revision ID: 20260806_0010
Revises: 20260806_0009
Create Date: 2026-08-06 21:40:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0010"
down_revision: str | None = "20260806_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable style-preset selection log."""

    op.create_table(
        "style_preset_selections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("generation_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("niche_key", sa.String(length=64), nullable=False),
        sa.Column("slide_key", sa.String(length=64), nullable=False),
        sa.Column("selected_style", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["generation_job_id"],
            ["generation_jobs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_style_preset_selections_user_id",
        "style_preset_selections",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_style_preset_selections_generation_job_id",
        "style_preset_selections",
        ["generation_job_id"],
        unique=False,
    )
    op.create_index(
        "ix_style_preset_selections_niche_key",
        "style_preset_selections",
        ["niche_key"],
        unique=False,
    )
    op.create_index(
        "ix_style_preset_selections_slide_key",
        "style_preset_selections",
        ["slide_key"],
        unique=False,
    )
    op.create_index(
        "ix_style_preset_selections_selected_style",
        "style_preset_selections",
        ["selected_style"],
        unique=False,
    )
    op.create_index(
        "ix_style_preset_selections_created_at",
        "style_preset_selections",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_style_preset_selections_niche_style",
        "style_preset_selections",
        ["niche_key", "selected_style"],
        unique=False,
    )
    op.create_index(
        "ix_style_preset_selections_niche_slide",
        "style_preset_selections",
        ["niche_key", "slide_key"],
        unique=False,
    )


def downgrade() -> None:
    """Drop style-preset selection tracking."""

    op.drop_index(
        "ix_style_preset_selections_niche_slide",
        table_name="style_preset_selections",
    )
    op.drop_index(
        "ix_style_preset_selections_niche_style",
        table_name="style_preset_selections",
    )
    op.drop_index(
        "ix_style_preset_selections_created_at",
        table_name="style_preset_selections",
    )
    op.drop_index(
        "ix_style_preset_selections_selected_style",
        table_name="style_preset_selections",
    )
    op.drop_index(
        "ix_style_preset_selections_slide_key",
        table_name="style_preset_selections",
    )
    op.drop_index(
        "ix_style_preset_selections_niche_key",
        table_name="style_preset_selections",
    )
    op.drop_index(
        "ix_style_preset_selections_generation_job_id",
        table_name="style_preset_selections",
    )
    op.drop_index(
        "ix_style_preset_selections_user_id",
        table_name="style_preset_selections",
    )
    op.drop_table("style_preset_selections")
