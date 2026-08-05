"""Alembic migration: tariffs, AI-coins, payments, subscription expiry.

Revision ID: 20260806_0002
Revises: 20260326_0001
Create Date: 2026-08-06 00:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260806_0002"
down_revision: Union[str, None] = "20260326_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

tariff_code_enum = postgresql.ENUM(
    "start",
    "pro",
    "half_year",
    "year",
    name="tariff_code_enum",
    create_type=False,
)

payment_status_enum = postgresql.ENUM(
    "pending",
    "waiting_for_capture",
    "succeeded",
    "canceled",
    "failed",
    name="payment_status_enum",
    create_type=False,
)


def upgrade() -> None:
    """Extend users for billing and create payments table."""

    # PostgreSQL: ADD VALUE cannot run inside a transaction block on older versions.
    # Alembic autocommit_block is the safe pattern for enum extension.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE subscription_status_enum ADD VALUE IF NOT EXISTS 'Start'")
        op.execute("ALTER TYPE subscription_status_enum ADD VALUE IF NOT EXISTS 'HalfYear'")
        op.execute("ALTER TYPE subscription_status_enum ADD VALUE IF NOT EXISTS 'Year'")

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tariff_code_enum') THEN
                CREATE TYPE tariff_code_enum AS ENUM ('start', 'pro', 'half_year', 'year');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payment_status_enum') THEN
                CREATE TYPE payment_status_enum AS ENUM (
                    'pending',
                    'waiting_for_capture',
                    'succeeded',
                    'canceled',
                    'failed'
                );
            END IF;
        END $$;
        """
    )

    op.add_column(
        "users",
        sa.Column(
            "ai_coins",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("subscription_ends_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_subscription_ends_at",
        "users",
        ["subscription_ends_at"],
        unique=False,
    )

    op.create_table(
        "payments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tariff_code", tariff_code_enum, nullable=False),
        sa.Column("yookassa_payment_id", sa.String(length=128), nullable=False),
        sa.Column("amount_rub", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default=sa.text("'RUB'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            payment_status_enum,
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("confirmation_url", sa.String(length=2048), nullable=True),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("raw_webhook_payload", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("yookassa_payment_id"),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"], unique=False)
    op.create_index("ix_payments_tariff_code", "payments", ["tariff_code"], unique=False)
    op.create_index(
        "ix_payments_yookassa_payment_id",
        "payments",
        ["yookassa_payment_id"],
        unique=False,
    )
    op.create_index("ix_payments_status", "payments", ["status"], unique=False)
    op.create_index("ix_payments_created_at", "payments", ["created_at"], unique=False)


def downgrade() -> None:
    """Remove payments table and billing columns from users.

    Note: PostgreSQL cannot easily drop enum values; subscription_status_enum
    values Start/HalfYear/Year are left in place on downgrade.
    """

    op.drop_index("ix_payments_created_at", table_name="payments")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_yookassa_payment_id", table_name="payments")
    op.drop_index("ix_payments_tariff_code", table_name="payments")
    op.drop_index("ix_payments_user_id", table_name="payments")
    op.drop_table("payments")

    op.drop_index("ix_users_subscription_ends_at", table_name="users")
    op.drop_column("users", "subscription_ends_at")
    op.drop_column("users", "ai_coins")

    op.execute("DROP TYPE IF EXISTS payment_status_enum")
    op.execute("DROP TYPE IF EXISTS tariff_code_enum")
