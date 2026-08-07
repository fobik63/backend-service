"""Templates, user saved designs, and custom fonts registry.

Creates ``templates`` (card canvas presets / user templates with GIN on
``canvas_data``), ``user_saved_designs``, and ``custom_fonts``.

Revision ID: 20260808_0043
Revises: 20260808_0042
Create Date: 2026-08-08 02:20:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260808_0043"
down_revision: str | None = "20260808_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> Inspector:
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _has_index(table: str, index_name: str) -> bool:
    if not _has_table(table):
        return False
    return any(idx["name"] == index_name for idx in _inspector().get_indexes(table))


def upgrade() -> None:
    """Create templates, user_saved_designs, and custom_fonts."""

    if not _has_table("templates"):
        op.create_table(
            "templates",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("category", sa.String(length=64), nullable=False),
            sa.Column(
                "is_preset",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
            sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "canvas_data",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
            sa.Column("preview_url", sa.Text(), nullable=True),
            sa.Column(
                "downloads_count",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
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
            sa.ForeignKeyConstraint(
                ["author_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_index("templates", "ix_templates_category"):
        op.create_index(
            "ix_templates_category",
            "templates",
            ["category"],
            unique=False,
        )
    if not _has_index("templates", "ix_templates_canvas_data_gin"):
        op.create_index(
            "ix_templates_canvas_data_gin",
            "templates",
            ["canvas_data"],
            unique=False,
            postgresql_using="gin",
        )
    if not _has_index("templates", "ix_templates_is_preset"):
        op.create_index(
            "ix_templates_is_preset",
            "templates",
            ["is_preset"],
            unique=False,
        )
    if not _has_index("templates", "ix_templates_author_id"):
        op.create_index(
            "ix_templates_author_id",
            "templates",
            ["author_id"],
            unique=False,
        )
    if not _has_index("templates", "ix_templates_created_at"):
        op.create_index(
            "ix_templates_created_at",
            "templates",
            ["created_at"],
            unique=False,
        )

    if not _has_table("user_saved_designs"):
        op.create_table(
            "user_saved_designs",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column(
                "canvas_data",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
            sa.Column("preview_url", sa.Text(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("NOW()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["template_id"],
                ["templates.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_index("user_saved_designs", "ix_user_saved_designs_user_id"):
        op.create_index(
            "ix_user_saved_designs_user_id",
            "user_saved_designs",
            ["user_id"],
            unique=False,
        )
    if not _has_index("user_saved_designs", "ix_user_saved_designs_template_id"):
        op.create_index(
            "ix_user_saved_designs_template_id",
            "user_saved_designs",
            ["template_id"],
            unique=False,
        )
    if not _has_index("user_saved_designs", "ix_user_saved_designs_updated_at"):
        op.create_index(
            "ix_user_saved_designs_updated_at",
            "user_saved_designs",
            ["updated_at"],
            unique=False,
        )

    if not _has_table("custom_fonts"):
        op.create_table(
            "custom_fonts",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("font_name", sa.String(length=128), nullable=False),
            sa.Column("font_family", sa.String(length=128), nullable=False),
            sa.Column("file_path_ttf", sa.Text(), nullable=True),
            sa.Column("file_path_woff2", sa.Text(), nullable=True),
            sa.Column(
                "is_system",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("font_name", name="uq_custom_fonts_font_name"),
        )

    if not _has_index("custom_fonts", "ix_custom_fonts_font_family"):
        op.create_index(
            "ix_custom_fonts_font_family",
            "custom_fonts",
            ["font_family"],
            unique=False,
        )
    if not _has_index("custom_fonts", "ix_custom_fonts_is_system"):
        op.create_index(
            "ix_custom_fonts_is_system",
            "custom_fonts",
            ["is_system"],
            unique=False,
        )


def downgrade() -> None:
    """Drop custom_fonts, user_saved_designs, and templates."""

    if _has_table("custom_fonts"):
        if _has_index("custom_fonts", "ix_custom_fonts_is_system"):
            op.drop_index("ix_custom_fonts_is_system", table_name="custom_fonts")
        if _has_index("custom_fonts", "ix_custom_fonts_font_family"):
            op.drop_index("ix_custom_fonts_font_family", table_name="custom_fonts")
        op.drop_table("custom_fonts")

    if _has_table("user_saved_designs"):
        if _has_index("user_saved_designs", "ix_user_saved_designs_updated_at"):
            op.drop_index(
                "ix_user_saved_designs_updated_at",
                table_name="user_saved_designs",
            )
        if _has_index("user_saved_designs", "ix_user_saved_designs_template_id"):
            op.drop_index(
                "ix_user_saved_designs_template_id",
                table_name="user_saved_designs",
            )
        if _has_index("user_saved_designs", "ix_user_saved_designs_user_id"):
            op.drop_index(
                "ix_user_saved_designs_user_id",
                table_name="user_saved_designs",
            )
        op.drop_table("user_saved_designs")

    if _has_table("templates"):
        if _has_index("templates", "ix_templates_created_at"):
            op.drop_index("ix_templates_created_at", table_name="templates")
        if _has_index("templates", "ix_templates_author_id"):
            op.drop_index("ix_templates_author_id", table_name="templates")
        if _has_index("templates", "ix_templates_is_preset"):
            op.drop_index("ix_templates_is_preset", table_name="templates")
        if _has_index("templates", "ix_templates_canvas_data_gin"):
            op.drop_index("ix_templates_canvas_data_gin", table_name="templates")
        if _has_index("templates", "ix_templates_category"):
            op.drop_index("ix_templates_category", table_name="templates")
        op.drop_table("templates")
