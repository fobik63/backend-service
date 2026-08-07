"""Alembic: billing + Celery/progress columns on three_d_video_tasks.

Adds Safe-Spend hold fields, celery_task_id, and live progress columns so
``render_360_video_task`` can freeze/refund coins and mirror Redis progress.

Revision ID: 20260808_0042
Revises: 20260808_0041
Create Date: 2026-08-08 02:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260808_0042"
down_revision: str | None = "20260808_0041"
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
    """Extend three_d_video_tasks with hold ledger + Celery progress fields."""

    if not _has_table("three_d_video_tasks"):
        return

    if not _has_column("three_d_video_tasks", "cost_coins"):
        op.add_column(
            "three_d_video_tasks",
            sa.Column(
                "cost_coins",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if not _has_column("three_d_video_tasks", "progress_percent"):
        op.add_column(
            "three_d_video_tasks",
            sa.Column(
                "progress_percent",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if not _has_column("three_d_video_tasks", "stage"):
        op.add_column(
            "three_d_video_tasks",
            sa.Column("stage", sa.String(length=64), nullable=True),
        )
    if not _has_column("three_d_video_tasks", "celery_task_id"):
        op.add_column(
            "three_d_video_tasks",
            sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        )
        if not _has_index("three_d_video_tasks", "ix_three_d_video_tasks_celery_task_id"):
            op.create_index(
                "ix_three_d_video_tasks_celery_task_id",
                "three_d_video_tasks",
                ["celery_task_id"],
                unique=False,
            )
    if not _has_column("three_d_video_tasks", "coins_held"):
        op.add_column(
            "three_d_video_tasks",
            sa.Column(
                "coins_held",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if not _has_column("three_d_video_tasks", "coins_captured"):
        op.add_column(
            "three_d_video_tasks",
            sa.Column(
                "coins_captured",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if not _has_column("three_d_video_tasks", "coins_refunded"):
        op.add_column(
            "three_d_video_tasks",
            sa.Column(
                "coins_refunded",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if not _has_column("three_d_video_tasks", "coin_hold_id"):
        op.add_column(
            "three_d_video_tasks",
            sa.Column("coin_hold_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_three_d_video_tasks_coin_hold_id",
            "three_d_video_tasks",
            "coin_holds",
            ["coin_hold_id"],
            ["id"],
            ondelete="SET NULL",
        )
        if not _has_index("three_d_video_tasks", "ix_three_d_video_tasks_coin_hold_id"):
            op.create_index(
                "ix_three_d_video_tasks_coin_hold_id",
                "three_d_video_tasks",
                ["coin_hold_id"],
                unique=False,
            )
    if not _has_column("three_d_video_tasks", "idempotency_key"):
        op.add_column(
            "three_d_video_tasks",
            sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        )


def downgrade() -> None:
    """Drop billing/progress columns from three_d_video_tasks."""

    if not _has_table("three_d_video_tasks"):
        return

    if _has_column("three_d_video_tasks", "idempotency_key"):
        op.drop_column("three_d_video_tasks", "idempotency_key")
    if _has_column("three_d_video_tasks", "coin_hold_id"):
        if _has_index("three_d_video_tasks", "ix_three_d_video_tasks_coin_hold_id"):
            op.drop_index(
                "ix_three_d_video_tasks_coin_hold_id",
                table_name="three_d_video_tasks",
            )
        op.drop_constraint(
            "fk_three_d_video_tasks_coin_hold_id",
            "three_d_video_tasks",
            type_="foreignkey",
        )
        op.drop_column("three_d_video_tasks", "coin_hold_id")
    for col in ("coins_refunded", "coins_captured", "coins_held"):
        if _has_column("three_d_video_tasks", col):
            op.drop_column("three_d_video_tasks", col)
    if _has_column("three_d_video_tasks", "celery_task_id"):
        if _has_index("three_d_video_tasks", "ix_three_d_video_tasks_celery_task_id"):
            op.drop_index(
                "ix_three_d_video_tasks_celery_task_id",
                table_name="three_d_video_tasks",
            )
        op.drop_column("three_d_video_tasks", "celery_task_id")
    for col in ("stage", "progress_percent", "cost_coins"):
        if _has_column("three_d_video_tasks", col):
            op.drop_column("three_d_video_tasks", col)
