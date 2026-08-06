"""Automated A/B Testing experiments and variants.

Revision ID: 20260806_0020
Revises: 20260806_0019
Create Date: 2026-08-07 00:50:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0020"
down_revision: str | None = "20260806_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create A/B experiment + variant tables."""

    op.create_table(
        "ab_test_experiments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("marketplace", sa.String(length=32), nullable=False),
        sa.Column("niche_key", sa.String(length=128), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("nm_id", sa.String(length=64), nullable=True),
        sa.Column("campaign_id", sa.String(length=64), nullable=True),
        sa.Column(
            "product_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "hypotheses_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "resolution_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("winner_variant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("measurement_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("measurement_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "input_tokens",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "output_tokens",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ab_test_experiments_user_id",
        "ab_test_experiments",
        ["user_id"],
    )
    op.create_index(
        "ix_ab_test_experiments_status",
        "ab_test_experiments",
        ["status"],
    )
    op.create_index(
        "ix_ab_test_experiments_user_status",
        "ab_test_experiments",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_ab_test_experiments_measurement_ends_at",
        "ab_test_experiments",
        ["measurement_ends_at"],
    )
    op.create_index(
        "ix_ab_test_experiments_measuring_ends",
        "ab_test_experiments",
        ["status", "measurement_ends_at"],
    )
    op.create_index(
        "uq_ab_test_experiments_user_idempotency",
        "ab_test_experiments",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "ab_test_variants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("experiment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("main_image_brief", sa.Text(), nullable=True),
        sa.Column("offer_hook", sa.String(length=300), nullable=True),
        sa.Column("headline", sa.String(length=200), nullable=True),
        sa.Column("rationale", sa.String(length=500), nullable=True),
        sa.Column("prompt_for_generator", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("ads_creative_id", sa.String(length=128), nullable=True),
        sa.Column("ads_campaign_id", sa.String(length=128), nullable=True),
        sa.Column("marketplace_media_id", sa.String(length=128), nullable=True),
        sa.Column(
            "impressions",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "clicks",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "ctr_pct",
            sa.Float(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("spend", sa.Float(), nullable=True),
        sa.Column("metrics_sampled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["ab_test_experiments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ab_test_variants_experiment_id",
        "ab_test_variants",
        ["experiment_id"],
    )
    op.create_index(
        "ix_ab_test_variants_status",
        "ab_test_variants",
        ["status"],
    )
    op.create_index(
        "ix_ab_test_variants_experiment_status",
        "ab_test_variants",
        ["experiment_id", "status"],
    )
    op.create_index(
        "uq_ab_test_variants_experiment_position",
        "ab_test_variants",
        ["experiment_id", "position"],
        unique=True,
    )
    op.create_index(
        "uq_ab_test_variants_experiment_strategy",
        "ab_test_variants",
        ["experiment_id", "strategy"],
        unique=True,
    )


def downgrade() -> None:
    """Drop A/B testing tables."""

    op.drop_index(
        "uq_ab_test_variants_experiment_strategy",
        table_name="ab_test_variants",
    )
    op.drop_index(
        "uq_ab_test_variants_experiment_position",
        table_name="ab_test_variants",
    )
    op.drop_index(
        "ix_ab_test_variants_experiment_status",
        table_name="ab_test_variants",
    )
    op.drop_index("ix_ab_test_variants_status", table_name="ab_test_variants")
    op.drop_index("ix_ab_test_variants_experiment_id", table_name="ab_test_variants")
    op.drop_table("ab_test_variants")

    op.drop_index(
        "uq_ab_test_experiments_user_idempotency",
        table_name="ab_test_experiments",
    )
    op.drop_index(
        "ix_ab_test_experiments_measuring_ends",
        table_name="ab_test_experiments",
    )
    op.drop_index(
        "ix_ab_test_experiments_measurement_ends_at",
        table_name="ab_test_experiments",
    )
    op.drop_index(
        "ix_ab_test_experiments_user_status",
        table_name="ab_test_experiments",
    )
    op.drop_index("ix_ab_test_experiments_status", table_name="ab_test_experiments")
    op.drop_index("ix_ab_test_experiments_user_id", table_name="ab_test_experiments")
    op.drop_table("ab_test_experiments")
