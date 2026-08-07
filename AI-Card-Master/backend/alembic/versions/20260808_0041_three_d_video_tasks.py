"""Alembic: 360° video generation tasks + video_assets.

Creates ``three_d_video_tasks`` (FK → three_d_tasks / users) and
``video_assets`` (FK → three_d_video_tasks / users) for orbital MP4/WebP/GIF
outputs stored in Selectel S3.

Revision ID: 20260808_0041
Revises: 20260808_0040
Create Date: 2026-08-08 01:50:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260808_0041"
down_revision: str | None = "20260808_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> Inspector:
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def upgrade() -> None:
    """Create three_d_video_tasks and video_assets."""

    if not _has_table("three_d_video_tasks"):
        op.create_table(
            "three_d_video_tasks",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("task_3d_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "status",
                sa.String(length=32),
                server_default=sa.text("'QUEUED'"),
                nullable=False,
            ),
            sa.Column(
                "resolution",
                sa.String(length=32),
                server_default=sa.text("'1080x1440'"),
                nullable=False,
            ),
            sa.Column(
                "fps",
                sa.Integer(),
                server_default=sa.text("24"),
                nullable=False,
            ),
            sa.Column(
                "duration_seconds",
                sa.Float(),
                server_default=sa.text("5.0"),
                nullable=False,
            ),
            sa.Column(
                "rotation_direction",
                sa.String(length=32),
                server_default=sa.text("'clockwise'"),
                nullable=False,
            ),
            sa.Column(
                "elevation_angle",
                sa.Float(),
                server_default=sa.text("15.0"),
                nullable=False,
            ),
            sa.Column(
                "background_type",
                sa.String(length=32),
                server_default=sa.text("'STUDIO_LIGHT'"),
                nullable=False,
            ),
            sa.Column("error_detail", sa.Text(), nullable=True),
            sa.Column("execution_time_ms", sa.Integer(), nullable=True),
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
                ["task_3d_id"],
                ["three_d_tasks.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint(
                "status IN ('QUEUED', 'RENDERING', 'ENCODING', 'COMPLETED', 'FAILED')",
                name="ck_three_d_video_tasks_status",
            ),
            sa.CheckConstraint(
                "background_type IN ("
                "'TRANSPARENT', 'GRADIENT', 'SOLID_COLOR', 'STUDIO_LIGHT')",
                name="ck_three_d_video_tasks_background_type",
            ),
            sa.CheckConstraint(
                "rotation_direction IN ('clockwise', 'counter_clockwise')",
                name="ck_three_d_video_tasks_rotation_direction",
            ),
            sa.CheckConstraint(
                "fps > 0",
                name="ck_three_d_video_tasks_fps_positive",
            ),
            sa.CheckConstraint(
                "duration_seconds > 0",
                name="ck_three_d_video_tasks_duration_positive",
            ),
        )
        op.create_index(
            "ix_three_d_video_tasks_user_id",
            "three_d_video_tasks",
            ["user_id"],
            unique=False,
        )
        op.create_index(
            "ix_three_d_video_tasks_status",
            "three_d_video_tasks",
            ["status"],
            unique=False,
        )
        op.create_index(
            "ix_three_d_video_tasks_created_at",
            "three_d_video_tasks",
            ["created_at"],
            unique=False,
        )
        op.create_index(
            "ix_three_d_video_tasks_task_3d_id",
            "three_d_video_tasks",
            ["task_3d_id"],
            unique=False,
        )
        op.create_index(
            "ix_three_d_video_tasks_user_status",
            "three_d_video_tasks",
            ["user_id", "status"],
            unique=False,
        )
        op.create_index(
            "ix_three_d_video_tasks_user_created",
            "three_d_video_tasks",
            ["user_id", "created_at"],
            unique=False,
        )

    if not _has_table("video_assets"):
        op.create_table(
            "video_assets",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("video_task_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("file_mp4_url", sa.Text(), nullable=True),
            sa.Column("file_webp_url", sa.Text(), nullable=True),
            sa.Column("file_gif_url", sa.Text(), nullable=True),
            sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
            sa.Column("width", sa.Integer(), nullable=True),
            sa.Column("height", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(
                ["video_task_id"],
                ["three_d_video_tasks.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_video_assets_video_task_id",
            "video_assets",
            ["video_task_id"],
            unique=False,
        )
        op.create_index(
            "ix_video_assets_user_id",
            "video_assets",
            ["user_id"],
            unique=False,
        )
        op.create_index(
            "ix_video_assets_user_video_task",
            "video_assets",
            ["user_id", "video_task_id"],
            unique=False,
        )


def downgrade() -> None:
    """Drop video_assets and three_d_video_tasks."""

    if _has_table("video_assets"):
        op.drop_index("ix_video_assets_user_video_task", table_name="video_assets")
        op.drop_index("ix_video_assets_user_id", table_name="video_assets")
        op.drop_index("ix_video_assets_video_task_id", table_name="video_assets")
        op.drop_table("video_assets")

    if _has_table("three_d_video_tasks"):
        op.drop_index(
            "ix_three_d_video_tasks_user_created",
            table_name="three_d_video_tasks",
        )
        op.drop_index(
            "ix_three_d_video_tasks_user_status",
            table_name="three_d_video_tasks",
        )
        op.drop_index(
            "ix_three_d_video_tasks_task_3d_id",
            table_name="three_d_video_tasks",
        )
        op.drop_index(
            "ix_three_d_video_tasks_created_at",
            table_name="three_d_video_tasks",
        )
        op.drop_index(
            "ix_three_d_video_tasks_status",
            table_name="three_d_video_tasks",
        )
        op.drop_index(
            "ix_three_d_video_tasks_user_id",
            table_name="three_d_video_tasks",
        )
        op.drop_table("three_d_video_tasks")
