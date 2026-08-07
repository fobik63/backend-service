"""Custom Brand LoRA tables: profiles + reference photos.

Revision ID: 20260807_0031
Revises: 20260807_0030
Create Date: 2026-08-07 16:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260807_0031"
down_revision: str | None = "20260807_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create brand LoRA profile and reference tables."""

    op.create_table(
        "brand_lora_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("trigger_word", sa.String(length=48), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("brand_style_prompt", sa.Text(), nullable=True),
        sa.Column("lora_weights_url", sa.String(length=2048), nullable=True),
        sa.Column("provider_training_id", sa.String(length=255), nullable=True),
        sa.Column("provider_version_id", sa.String(length=255), nullable=True),
        sa.Column(
            "lora_scale",
            sa.Float(),
            server_default=sa.text("0.85"),
            nullable=False,
        ),
        sa.Column(
            "reference_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "training_progress",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "coins_charged",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(
        "ix_brand_lora_profiles_user_id",
        "brand_lora_profiles",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_brand_lora_profiles_status",
        "brand_lora_profiles",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_brand_lora_profiles_is_active",
        "brand_lora_profiles",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        "ix_brand_lora_profiles_provider_training_id",
        "brand_lora_profiles",
        ["provider_training_id"],
        unique=False,
    )
    op.create_index(
        "ix_brand_lora_profiles_user_status",
        "brand_lora_profiles",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_brand_lora_profiles_status_updated",
        "brand_lora_profiles",
        ["status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "uq_brand_lora_profiles_user_active",
        "brand_lora_profiles",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
    )

    op.create_table(
        "brand_lora_references",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column(
            "mime_type",
            sa.String(length=64),
            server_default=sa.text("'image/jpeg'"),
            nullable=False,
        ),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["brand_lora_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id",
            "position",
            name="uq_brand_lora_references_profile_position",
        ),
    )
    op.create_index(
        "ix_brand_lora_references_profile",
        "brand_lora_references",
        ["profile_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop brand LoRA tables."""

    op.drop_index(
        "ix_brand_lora_references_profile",
        table_name="brand_lora_references",
    )
    op.drop_table("brand_lora_references")
    op.drop_index(
        "uq_brand_lora_profiles_user_active",
        table_name="brand_lora_profiles",
    )
    op.drop_index(
        "ix_brand_lora_profiles_status_updated",
        table_name="brand_lora_profiles",
    )
    op.drop_index(
        "ix_brand_lora_profiles_user_status",
        table_name="brand_lora_profiles",
    )
    op.drop_index(
        "ix_brand_lora_profiles_provider_training_id",
        table_name="brand_lora_profiles",
    )
    op.drop_index(
        "ix_brand_lora_profiles_is_active",
        table_name="brand_lora_profiles",
    )
    op.drop_index(
        "ix_brand_lora_profiles_status",
        table_name="brand_lora_profiles",
    )
    op.drop_index(
        "ix_brand_lora_profiles_user_id",
        table_name="brand_lora_profiles",
    )
    op.drop_table("brand_lora_profiles")
