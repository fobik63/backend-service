"""Alembic: signup_trial_claims for fingerprint-based trial anti-abuse.

Revision ID: 20260807_0035
Revises: 20260807_0034
Create Date: 2026-08-07 21:20:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260807_0035"
down_revision: str | None = "20260807_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable signup trial fingerprint claim table."""

    op.create_table(
        "signup_trial_claims",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fingerprint_hash", sa.String(length=64), nullable=True),
        sa.Column("client_ip", sa.String(length=64), nullable=True),
        sa.Column("ip_subnet", sa.String(length=64), nullable=True),
        sa.Column(
            "trial_granted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("denial_reason", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("accept_language", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_signup_trial_claims_user_id",
        "signup_trial_claims",
        ["user_id"],
    )
    op.create_index(
        "ix_signup_trial_claims_fingerprint_hash",
        "signup_trial_claims",
        ["fingerprint_hash"],
    )
    op.create_index(
        "ix_signup_trial_claims_fp_granted",
        "signup_trial_claims",
        ["fingerprint_hash", "trial_granted"],
    )
    op.create_index(
        "ix_signup_trial_claims_ip_subnet",
        "signup_trial_claims",
        ["ip_subnet"],
    )
    op.create_index(
        "ix_signup_trial_claims_created_at",
        "signup_trial_claims",
        ["created_at"],
    )


def downgrade() -> None:
    """Drop signup_trial_claims."""

    op.drop_index("ix_signup_trial_claims_created_at", table_name="signup_trial_claims")
    op.drop_index("ix_signup_trial_claims_ip_subnet", table_name="signup_trial_claims")
    op.drop_index("ix_signup_trial_claims_fp_granted", table_name="signup_trial_claims")
    op.drop_index(
        "ix_signup_trial_claims_fingerprint_hash",
        table_name="signup_trial_claims",
    )
    op.drop_index("ix_signup_trial_claims_user_id", table_name="signup_trial_claims")
    op.drop_table("signup_trial_claims")
