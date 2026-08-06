"""Pro workspaces: membership and shared generation assets.

Revision ID: 20260806_0011
Revises: 20260806_0010
Create Date: 2026-08-06 21:50:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0011"
down_revision: str | None = "20260806_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create workspaces, members, and shared-generation tables."""

    op.create_table(
        "workspaces",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "max_managers",
            sa.Integer(),
            server_default=sa.text("3"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", name="uq_workspaces_owner_user_id"),
    )
    op.create_index("ix_workspaces_owner_user_id", "workspaces", ["owner_user_id"])
    op.create_index("ix_workspaces_created_at", "workspaces", ["created_at"])
    op.create_index("ix_workspaces_updated_at", "workspaces", ["updated_at"])

    op.create_table(
        "workspace_members",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role",
            sa.String(length=32),
            server_default=sa.text("'manager'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_workspace_members_workspace_user",
        ),
        sa.UniqueConstraint("user_id", name="uq_workspace_members_user"),
    )
    op.create_index(
        "ix_workspace_members_workspace_id",
        "workspace_members",
        ["workspace_id"],
    )
    op.create_index("ix_workspace_members_user_id", "workspace_members", ["user_id"])
    op.create_index("ix_workspace_members_role", "workspace_members", ["role"])
    op.create_index(
        "ix_workspace_members_created_at",
        "workspace_members",
        ["created_at"],
    )

    op.create_table(
        "workspace_shared_generations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generation_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shared_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["generation_job_id"],
            ["generation_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["shared_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "generation_job_id",
            name="uq_workspace_shared_generations_job",
        ),
    )
    op.create_index(
        "ix_workspace_shared_generations_workspace_id",
        "workspace_shared_generations",
        ["workspace_id"],
    )
    op.create_index(
        "ix_workspace_shared_generations_generation_job_id",
        "workspace_shared_generations",
        ["generation_job_id"],
    )
    op.create_index(
        "ix_workspace_shared_generations_shared_by_user_id",
        "workspace_shared_generations",
        ["shared_by_user_id"],
    )
    op.create_index(
        "ix_workspace_shared_generations_created_at",
        "workspace_shared_generations",
        ["created_at"],
    )


def downgrade() -> None:
    """Drop workspace tables."""

    op.drop_index(
        "ix_workspace_shared_generations_created_at",
        table_name="workspace_shared_generations",
    )
    op.drop_index(
        "ix_workspace_shared_generations_shared_by_user_id",
        table_name="workspace_shared_generations",
    )
    op.drop_index(
        "ix_workspace_shared_generations_generation_job_id",
        table_name="workspace_shared_generations",
    )
    op.drop_index(
        "ix_workspace_shared_generations_workspace_id",
        table_name="workspace_shared_generations",
    )
    op.drop_table("workspace_shared_generations")

    op.drop_index("ix_workspace_members_created_at", table_name="workspace_members")
    op.drop_index("ix_workspace_members_role", table_name="workspace_members")
    op.drop_index("ix_workspace_members_user_id", table_name="workspace_members")
    op.drop_index("ix_workspace_members_workspace_id", table_name="workspace_members")
    op.drop_table("workspace_members")

    op.drop_index("ix_workspaces_updated_at", table_name="workspaces")
    op.drop_index("ix_workspaces_created_at", table_name="workspaces")
    op.drop_index("ix_workspaces_owner_user_id", table_name="workspaces")
    op.drop_table("workspaces")
