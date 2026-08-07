"""ORM models for card templates, saved designs, and custom fonts."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Template(Base):
    """Marketplace / user card template with Fabric-compatible canvas JSON."""

    __tablename__ = "templates"
    __table_args__ = (
        Index("ix_templates_category", "category"),
        Index(
            "ix_templates_canvas_data_gin",
            "canvas_data",
            postgresql_using="gin",
        ),
        Index("ix_templates_is_preset", "is_preset"),
        Index("ix_templates_author_id", "author_id"),
        Index("ix_templates_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    is_preset: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    author_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    canvas_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    preview_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    downloads_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        onupdate=datetime.utcnow,
    )


class UserSavedDesign(Base):
    """Per-user autosaved / bookmarked canvas work (optionally from a template)."""

    __tablename__ = "user_saved_designs"
    __table_args__ = (
        Index("ix_user_saved_designs_user_id", "user_id"),
        Index("ix_user_saved_designs_template_id", "template_id"),
        Index("ix_user_saved_designs_updated_at", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    canvas_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    preview_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        onupdate=datetime.utcnow,
    )


class CustomFont(Base):
    """Registry of system and uploaded fonts (TTF + WOFF2 paths)."""

    __tablename__ = "custom_fonts"
    __table_args__ = (
        Index("ix_custom_fonts_font_family", "font_family"),
        Index("ix_custom_fonts_is_system", "is_system"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    font_name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    font_family: Mapped[str] = mapped_column(String(128), nullable=False)
    file_path_ttf: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path_woff2: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
