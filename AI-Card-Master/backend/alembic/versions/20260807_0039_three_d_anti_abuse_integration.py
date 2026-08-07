"""Alembic: unified 3D pipeline + anti-abuse User columns.

Extends ``three_d_tasks`` (progress, hold, idempotency, coin_hold_id),
creates ``coin_holds``, and adds ``users.fingerprint_hash``.

Tables ``three_d_tasks``, ``three_d_assets``, ``gpu_rental_sessions`` are
created by revision ``20260807_0038``. Silent-ban columns ``is_flagged`` /
``flag_reason`` already exist from ``20260807_0036``. This revision is
additive only — existing user rows are left intact (nullable fingerprint,
server defaults on new task columns).

Revision ID: 20260807_0039
Revises: 20260807_0038
Create Date: 2026-08-07 23:50:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260807_0039"
down_revision: str | None = "20260807_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> Inspector:
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {col["name"] for col in _inspector().get_columns(table)}


def _has_index(table: str, index_name: str) -> bool:
    if not _has_table(table):
        return False
    return index_name in {idx["name"] for idx in _inspector().get_indexes(table)}


def _ensure_user_anti_abuse_columns() -> None:
    """Add missing anti-abuse columns without touching existing user data."""

    if not _has_column("users", "is_flagged"):
        op.add_column(
            "users",
            sa.Column(
                "is_flagged",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
        )
    if not _has_index("users", "ix_users_is_flagged"):
        op.create_index("ix_users_is_flagged", "users", ["is_flagged"])

    if not _has_column("users", "flag_reason"):
        op.add_column(
            "users",
            sa.Column("flag_reason", sa.String(length=64), nullable=True),
        )

    if not _has_column("users", "fingerprint_hash"):
        op.add_column(
            "users",
            sa.Column("fingerprint_hash", sa.String(length=64), nullable=True),
        )
    if not _has_index("users", "ix_users_fingerprint_hash"):
        op.create_index(
            "ix_users_fingerprint_hash",
            "users",
            ["fingerprint_hash"],
            unique=False,
        )


def _ensure_three_d_pipeline_columns() -> None:
    """Add progress / Safe-Spend / generate-API columns on three_d_tasks."""

    if not _has_table("three_d_tasks"):
        return

    if not _has_column("three_d_tasks", "progress_percent"):
        op.add_column(
            "three_d_tasks",
            sa.Column(
                "progress_percent",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
        )
    if not _has_column("three_d_tasks", "stage"):
        op.add_column(
            "three_d_tasks",
            sa.Column("stage", sa.String(length=64), nullable=True),
        )
    if not _has_column("three_d_tasks", "celery_task_id"):
        op.add_column(
            "three_d_tasks",
            sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        )
    if not _has_index("three_d_tasks", "ix_three_d_tasks_celery_task_id"):
        op.create_index(
            "ix_three_d_tasks_celery_task_id",
            "three_d_tasks",
            ["celery_task_id"],
            unique=False,
        )

    for flag_col in ("coins_held", "coins_captured", "coins_refunded"):
        if not _has_column("three_d_tasks", flag_col):
            op.add_column(
                "three_d_tasks",
                sa.Column(
                    flag_col,
                    sa.Boolean(),
                    server_default=sa.text("false"),
                    nullable=False,
                ),
            )

    if not _has_column("three_d_tasks", "idempotency_key"):
        op.add_column(
            "three_d_tasks",
            sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        )
    if not _has_column("three_d_tasks", "output_format"):
        op.add_column(
            "three_d_tasks",
            sa.Column("output_format", sa.String(length=16), nullable=True),
        )
    if not _has_index("three_d_tasks", "uq_three_d_tasks_user_idempotency"):
        op.create_index(
            "uq_three_d_tasks_user_idempotency",
            "three_d_tasks",
            ["user_id", "idempotency_key"],
            unique=True,
            postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        )


def _ensure_coin_holds() -> None:
    """Create coin_holds ledger and optional FK from three_d_tasks."""

    if not _has_table("coin_holds"):
        op.create_table(
            "coin_holds",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "amount",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                server_default=sa.text("'held'"),
                nullable=False,
            ),
            sa.Column("service_type", sa.String(length=64), nullable=True),
            sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=True),
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
            sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint(
                "amount >= 0",
                name="ck_coin_holds_amount_non_negative",
            ),
        )
        op.create_index("ix_coin_holds_user_id", "coin_holds", ["user_id"], unique=False)
        op.create_index("ix_coin_holds_status", "coin_holds", ["status"], unique=False)
        op.create_index(
            "ix_coin_holds_user_status",
            "coin_holds",
            ["user_id", "status"],
            unique=False,
        )
        op.create_index(
            "ix_coin_holds_reference_id",
            "coin_holds",
            ["reference_id"],
            unique=False,
        )

    if _has_table("three_d_tasks") and not _has_column("three_d_tasks", "coin_hold_id"):
        op.add_column(
            "three_d_tasks",
            sa.Column("coin_hold_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_three_d_tasks_coin_hold_id",
            "three_d_tasks",
            "coin_holds",
            ["coin_hold_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            "ix_three_d_tasks_coin_hold_id",
            "three_d_tasks",
            ["coin_hold_id"],
            unique=False,
        )


def upgrade() -> None:
    """Apply additive 3D pipeline + anti-abuse schema (idempotent guards)."""

    _ensure_user_anti_abuse_columns()
    _ensure_three_d_pipeline_columns()
    _ensure_coin_holds()


def downgrade() -> None:
    """Roll back this revision only; does not drop base 3D tables from 0038."""

    if _has_column("three_d_tasks", "coin_hold_id"):
        if _has_index("three_d_tasks", "ix_three_d_tasks_coin_hold_id"):
            op.drop_index(
                "ix_three_d_tasks_coin_hold_id",
                table_name="three_d_tasks",
            )
        op.drop_constraint(
            "fk_three_d_tasks_coin_hold_id",
            "three_d_tasks",
            type_="foreignkey",
        )
        op.drop_column("three_d_tasks", "coin_hold_id")

    if _has_table("coin_holds"):
        for index_name in (
            "ix_coin_holds_reference_id",
            "ix_coin_holds_user_status",
            "ix_coin_holds_status",
            "ix_coin_holds_user_id",
        ):
            if _has_index("coin_holds", index_name):
                op.drop_index(index_name, table_name="coin_holds")
        op.drop_table("coin_holds")

    if _has_index("three_d_tasks", "uq_three_d_tasks_user_idempotency"):
        op.drop_index(
            "uq_three_d_tasks_user_idempotency",
            table_name="three_d_tasks",
        )
    if _has_column("three_d_tasks", "output_format"):
        op.drop_column("three_d_tasks", "output_format")
    if _has_column("three_d_tasks", "idempotency_key"):
        op.drop_column("three_d_tasks", "idempotency_key")

    if _has_index("three_d_tasks", "ix_three_d_tasks_celery_task_id"):
        op.drop_index(
            "ix_three_d_tasks_celery_task_id",
            table_name="three_d_tasks",
        )
    for col in (
        "coins_refunded",
        "coins_captured",
        "coins_held",
        "celery_task_id",
        "stage",
        "progress_percent",
    ):
        if _has_column("three_d_tasks", col):
            op.drop_column("three_d_tasks", col)

    # Only drop fingerprint_hash added here; leave is_flagged/flag_reason
    # (owned by 20260807_0036) untouched so user silent-ban data survives.
    if _has_index("users", "ix_users_fingerprint_hash"):
        op.drop_index("ix_users_fingerprint_hash", table_name="users")
    if _has_column("users", "fingerprint_hash"):
        op.drop_column("users", "fingerprint_hash")
