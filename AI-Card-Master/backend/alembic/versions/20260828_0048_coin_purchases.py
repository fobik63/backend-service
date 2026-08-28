"""Create coin_purchases table for standalone YooKassa AI-coin top-ups.

Revision ID: 20260828_0048
Revises: 20260810_0047
Create Date: 2026-08-28 03:40:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260828_0048"
down_revision: str | None = "20260810_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

payment_status_enum = postgresql.ENUM(
    "pending",
    "waiting_for_capture",
    "succeeded",
    "canceled",
    "failed",
    name="payment_status_enum",
    create_type=False,
)


def _inspector() -> Inspector:
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    if "coin_purchases" in _inspector().get_table_names():
        return

    op.create_table(
        "coin_purchases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount_coins", sa.Integer(), nullable=False),
        sa.Column("unit_price_rub", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("amount_rub", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default=sa.text("'RUB'"),
            nullable=False,
        ),
        sa.Column("package_code", sa.String(length=32), nullable=False),
        sa.Column("yookassa_payment_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            payment_status_enum,
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("confirmation_url", sa.String(length=2048), nullable=True),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("receipt_description", sa.String(length=256), nullable=True),
        sa.Column("raw_webhook_payload", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_coins >= 50", name="ck_coin_purchases_min_coins"),
        sa.CheckConstraint("amount_rub > 0", name="ck_coin_purchases_positive_amount"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "yookassa_payment_id", name="uq_coin_purchases_yookassa_payment_id"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_coin_purchases_idempotency_key"),
    )
    op.create_index(
        "ix_coin_purchases_user_id", "coin_purchases", ["user_id"], unique=False
    )
    op.create_index(
        "ix_coin_purchases_package_code",
        "coin_purchases",
        ["package_code"],
        unique=False,
    )
    op.create_index(
        "ix_coin_purchases_status", "coin_purchases", ["status"], unique=False
    )
    op.create_index(
        "ix_coin_purchases_created_at", "coin_purchases", ["created_at"], unique=False
    )


def downgrade() -> None:
    if "coin_purchases" not in _inspector().get_table_names():
        return
    op.drop_index("ix_coin_purchases_created_at", table_name="coin_purchases")
    op.drop_index("ix_coin_purchases_status", table_name="coin_purchases")
    op.drop_index("ix_coin_purchases_package_code", table_name="coin_purchases")
    op.drop_index("ix_coin_purchases_user_id", table_name="coin_purchases")
    op.drop_table("coin_purchases")
