"""Initial schema: users, generations, generation_error_logs.

Revision ID: 20260326_0001
Revises:
Create Date: 2026-03-26 00:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260326_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

subscription_status_enum = postgresql.ENUM(
    "Free",
    "Pro",
    name="subscription_status_enum",
    create_type=False,
)


def upgrade() -> None:
    """Create core tables matching sql/001_init_schema.sql and ORM models."""

    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'subscription_status_enum'
            ) THEN
                CREATE TYPE subscription_status_enum AS ENUM ('Free', 'Pro');
            END IF;
        END $$;
        """
    )

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=1024), nullable=False),
        sa.Column(
            "is_admin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "subscription_status",
            subscription_status_enum,
            server_default=sa.text("'Free'"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)
    op.create_index("ix_users_is_admin", "users", ["is_admin"], unique=False)

    op.create_table(
        "generations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_image_url", sa.String(length=2048), nullable=False),
        sa.Column("result_image_url", sa.String(length=2048), nullable=False),
        sa.Column("prompt_used", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_generations_user_id", "generations", ["user_id"], unique=False)
    op.create_index("ix_generations_created_at", "generations", ["created_at"], unique=False)

    op.create_table(
        "generation_error_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_generation_error_logs_user_id",
        "generation_error_logs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_generation_error_logs_source",
        "generation_error_logs",
        ["source"],
        unique=False,
    )
    op.create_index(
        "ix_generation_error_logs_created_at",
        "generation_error_logs",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop core tables and enum type."""

    op.drop_index("ix_generation_error_logs_created_at", table_name="generation_error_logs")
    op.drop_index("ix_generation_error_logs_source", table_name="generation_error_logs")
    op.drop_index("ix_generation_error_logs_user_id", table_name="generation_error_logs")
    op.drop_table("generation_error_logs")

    op.drop_index("ix_generations_created_at", table_name="generations")
    op.drop_index("ix_generations_user_id", table_name="generations")
    op.drop_table("generations")

    op.drop_index("ix_users_is_admin", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    op.execute("DROP TYPE IF EXISTS subscription_status_enum")
