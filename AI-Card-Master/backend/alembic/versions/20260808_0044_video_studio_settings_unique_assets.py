"""Persist studio render settings + unique video_assets per task.

Adds ``studio_settings`` JSONB on ``three_d_video_tasks`` so lighting /
shadow-catcher choices from POST /api/v1/3d/video/render reach the Celery
worker, and enforces one ``video_assets`` row per ``video_task_id``.

Revision ID: 20260808_0044
Revises: 20260808_0043
Create Date: 2026-08-08 02:45:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260808_0044"
down_revision: str | None = "20260808_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> Inspector:
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return any(col["name"] == column for col in _inspector().get_columns(table))


def _has_index(table: str, index_name: str) -> bool:
    if not _has_table(table):
        return False
    return any(idx["name"] == index_name for idx in _inspector().get_indexes(table))


def upgrade() -> None:
    """Add studio_settings JSONB + unique video_task_id on video_assets."""

    if _has_table("three_d_video_tasks") and not _has_column(
        "three_d_video_tasks", "studio_settings"
    ):
        op.add_column(
            "three_d_video_tasks",
            sa.Column(
                "studio_settings",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
        )

    if _has_table("video_assets") and not _has_index(
        "video_assets", "uq_video_assets_video_task_id"
    ):
        # Collapse accidental duplicates before unique index (keep newest).
        op.execute(
            sa.text(
                """
                DELETE FROM video_assets a
                USING video_assets b
                WHERE a.video_task_id = b.video_task_id
                  AND a.ctid < b.ctid
                """
            )
        )
        op.create_index(
            "uq_video_assets_video_task_id",
            "video_assets",
            ["video_task_id"],
            unique=True,
        )


def downgrade() -> None:
    """Drop unique index and studio_settings column."""

    if _has_table("video_assets") and _has_index(
        "video_assets", "uq_video_assets_video_task_id"
    ):
        op.drop_index("uq_video_assets_video_task_id", table_name="video_assets")

    if _has_table("three_d_video_tasks") and _has_column(
        "three_d_video_tasks", "studio_settings"
    ):
        op.drop_column("three_d_video_tasks", "studio_settings")
