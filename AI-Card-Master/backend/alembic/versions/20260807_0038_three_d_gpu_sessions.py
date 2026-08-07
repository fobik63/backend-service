"""Alembic: 3D generation tasks/assets + GPU rental sessions.

Revision ID: 20260807_0038
Revises: 20260807_0037
Create Date: 2026-08-07 23:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260807_0038"
down_revision: str | None = "20260807_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create three_d_tasks, three_d_assets, and gpu_rental_sessions."""

    op.create_table(
        "three_d_tasks",
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
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column("input_type", sa.String(length=32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("source_image_url", sa.Text(), nullable=True),
        sa.Column("provider_name", sa.String(length=64), nullable=True),
        sa.Column("provider_job_id", sa.String(length=255), nullable=True),
        sa.Column(
            "cost_coins",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("polycount_target", sa.Integer(), nullable=True),
        sa.Column("texture_resolution", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("execution_time_seconds", sa.Float(), nullable=True),
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
        "ix_three_d_tasks_user_id",
        "three_d_tasks",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_three_d_tasks_status",
        "three_d_tasks",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_three_d_tasks_created_at",
        "three_d_tasks",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_three_d_tasks_provider_job_id",
        "three_d_tasks",
        ["provider_job_id"],
        unique=False,
    )
    op.create_index(
        "ix_three_d_tasks_user_status",
        "three_d_tasks",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_three_d_tasks_user_created",
        "three_d_tasks",
        ["user_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "three_d_assets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_glb_url", sa.Text(), nullable=True),
        sa.Column("file_usdz_url", sa.Text(), nullable=True),
        sa.Column("file_obj_url", sa.Text(), nullable=True),
        sa.Column("preview_png_url", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("polycount_actual", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["three_d_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_three_d_assets_task_id",
        "three_d_assets",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        "ix_three_d_assets_user_id",
        "three_d_assets",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_three_d_assets_user_task",
        "three_d_assets",
        ["user_id", "task_id"],
        unique=False,
    )

    op.create_table(
        "gpu_rental_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("instance_type", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'STARTING'"),
            nullable=False,
        ),
        sa.Column(
            "hourly_rate_coins",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "total_cost_coins",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_gpu_rental_sessions_user_id",
        "gpu_rental_sessions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_gpu_rental_sessions_status",
        "gpu_rental_sessions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_gpu_rental_sessions_user_status",
        "gpu_rental_sessions",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_gpu_rental_sessions_user_started",
        "gpu_rental_sessions",
        ["user_id", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop GPU rental and 3D generation tables."""

    op.drop_index(
        "ix_gpu_rental_sessions_user_started",
        table_name="gpu_rental_sessions",
    )
    op.drop_index(
        "ix_gpu_rental_sessions_user_status",
        table_name="gpu_rental_sessions",
    )
    op.drop_index("ix_gpu_rental_sessions_status", table_name="gpu_rental_sessions")
    op.drop_index("ix_gpu_rental_sessions_user_id", table_name="gpu_rental_sessions")
    op.drop_table("gpu_rental_sessions")

    op.drop_index("ix_three_d_assets_user_task", table_name="three_d_assets")
    op.drop_index("ix_three_d_assets_user_id", table_name="three_d_assets")
    op.drop_index("ix_three_d_assets_task_id", table_name="three_d_assets")
    op.drop_table("three_d_assets")

    op.drop_index("ix_three_d_tasks_user_created", table_name="three_d_tasks")
    op.drop_index("ix_three_d_tasks_user_status", table_name="three_d_tasks")
    op.drop_index("ix_three_d_tasks_provider_job_id", table_name="three_d_tasks")
    op.drop_index("ix_three_d_tasks_created_at", table_name="three_d_tasks")
    op.drop_index("ix_three_d_tasks_status", table_name="three_d_tasks")
    op.drop_index("ix_three_d_tasks_user_id", table_name="three_d_tasks")
    op.drop_table("three_d_tasks")
