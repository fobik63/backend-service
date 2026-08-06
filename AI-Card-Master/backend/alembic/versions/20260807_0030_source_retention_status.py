"""Zero-Knowledge retention status for heavy originals and ZIP archives.

Revision ID: 20260807_0030
Revises: 20260807_0029
Create Date: 2026-08-07 15:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0030"
down_revision: str | None = "20260807_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Track irreversible purge of heavy source assets (thumbnails stay)."""

    op.add_column(
        "generation_jobs",
        sa.Column(
            "input_retention_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'available'"),
        ),
    )
    op.add_column(
        "generation_jobs",
        sa.Column(
            "archive_retention_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'available'"),
        ),
    )
    op.create_index(
        "ix_generation_jobs_input_retention_status",
        "generation_jobs",
        ["input_retention_status"],
        unique=False,
    )
    op.create_index(
        "ix_generation_jobs_archive_retention_status",
        "generation_jobs",
        ["archive_retention_status"],
        unique=False,
    )

    op.add_column(
        "bulk_generation_batches",
        sa.Column(
            "source_zip_retention_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'available'"),
        ),
    )
    op.create_index(
        "ix_bulk_generation_batches_source_zip_retention_status",
        "bulk_generation_batches",
        ["source_zip_retention_status"],
        unique=False,
    )

    op.add_column(
        "bulk_generation_items",
        sa.Column(
            "input_retention_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'available'"),
        ),
    )
    op.create_index(
        "ix_bulk_generation_items_input_retention_status",
        "bulk_generation_items",
        ["input_retention_status"],
        unique=False,
    )

    op.add_column(
        "smart_variant_syncs",
        sa.Column(
            "source_retention_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'available'"),
        ),
    )
    op.create_index(
        "ix_smart_variant_syncs_source_retention_status",
        "smart_variant_syncs",
        ["source_retention_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_smart_variant_syncs_source_retention_status",
        table_name="smart_variant_syncs",
    )
    op.drop_column("smart_variant_syncs", "source_retention_status")

    op.drop_index(
        "ix_bulk_generation_items_input_retention_status",
        table_name="bulk_generation_items",
    )
    op.drop_column("bulk_generation_items", "input_retention_status")

    op.drop_index(
        "ix_bulk_generation_batches_source_zip_retention_status",
        table_name="bulk_generation_batches",
    )
    op.drop_column("bulk_generation_batches", "source_zip_retention_status")

    op.drop_index(
        "ix_generation_jobs_archive_retention_status",
        table_name="generation_jobs",
    )
    op.drop_index(
        "ix_generation_jobs_input_retention_status",
        table_name="generation_jobs",
    )
    op.drop_column("generation_jobs", "archive_retention_status")
    op.drop_column("generation_jobs", "input_retention_status")
