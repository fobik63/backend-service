"""Partial capture columns and unique idempotency key on coin_holds.

Revision ID: 20260828_0049
Revises: 20260828_0048
Create Date: 2026-08-28 04:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260828_0049"
down_revision: str | None = "20260828_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table: str) -> bool:
    return table in _inspector().get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return any(item["name"] == column for item in _inspector().get_columns(table))


def _has_constraint(table: str, name: str) -> bool:
    if not _has_table(table):
        return False
    inspector = _inspector()
    for group in (
        inspector.get_check_constraints(table),
        inspector.get_unique_constraints(table),
    ):
        if any(item.get("name") == name for item in group):
            return True
    return False


def upgrade() -> None:
    """Track remaining/captured amounts for stepwise CoinGuard settlement."""

    if not _has_table("coin_holds"):
        return

    if not _has_column("coin_holds", "remaining_amount"):
        op.add_column(
            "coin_holds",
            sa.Column(
                "remaining_amount",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
        )
    if not _has_column("coin_holds", "captured_amount"):
        op.add_column(
            "coin_holds",
            sa.Column(
                "captured_amount",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
        )
    if not _has_column("coin_holds", "idempotency_key"):
        op.add_column(
            "coin_holds",
            sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        )

    op.execute(
        sa.text(
            "UPDATE coin_holds SET remaining_amount = amount "
            "WHERE status = 'held' AND remaining_amount = 0 AND captured_amount = 0"
        )
    )
    op.execute(
        sa.text(
            "UPDATE coin_holds SET captured_amount = amount, remaining_amount = 0 "
            "WHERE status = 'captured' AND captured_amount = 0"
        )
    )

    if not _has_constraint("coin_holds", "ck_coin_holds_remaining_non_negative"):
        op.create_check_constraint(
            "ck_coin_holds_remaining_non_negative",
            "coin_holds",
            "remaining_amount >= 0",
        )
    if not _has_constraint("coin_holds", "ck_coin_holds_captured_non_negative"):
        op.create_check_constraint(
            "ck_coin_holds_captured_non_negative",
            "coin_holds",
            "captured_amount >= 0",
        )
    if not _has_constraint(
        "coin_holds", "ck_coin_holds_remaining_plus_captured_le_amount"
    ):
        op.create_check_constraint(
            "ck_coin_holds_remaining_plus_captured_le_amount",
            "coin_holds",
            "remaining_amount + captured_amount <= amount",
        )
    if not _has_constraint("coin_holds", "uq_coin_holds_idempotency_key"):
        op.create_unique_constraint(
            "uq_coin_holds_idempotency_key",
            "coin_holds",
            ["idempotency_key"],
        )


def downgrade() -> None:
    """Remove CoinGuard partial-settlement columns (held rows stay valid)."""

    if not _has_table("coin_holds"):
        return
    if _has_constraint("coin_holds", "uq_coin_holds_idempotency_key"):
        op.drop_constraint(
            "uq_coin_holds_idempotency_key", "coin_holds", type_="unique"
        )
    for name in (
        "ck_coin_holds_remaining_plus_captured_le_amount",
        "ck_coin_holds_captured_non_negative",
        "ck_coin_holds_remaining_non_negative",
    ):
        if _has_constraint("coin_holds", name):
            op.drop_constraint(name, "coin_holds", type_="check")
    if _has_column("coin_holds", "idempotency_key"):
        op.drop_column("coin_holds", "idempotency_key")
    if _has_column("coin_holds", "captured_amount"):
        op.drop_column("coin_holds", "captured_amount")
    if _has_column("coin_holds", "remaining_amount"):
        op.drop_column("coin_holds", "remaining_amount")
