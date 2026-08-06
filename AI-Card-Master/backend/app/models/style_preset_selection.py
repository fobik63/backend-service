"""Durable log of style-preset selections for internal product analytics."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StylePresetSelection(Base):
    """One row per slide style chosen when a generation job is created."""

    __tablename__ = "style_preset_selections"
    __table_args__ = (
        Index(
            "ix_style_preset_selections_niche_style",
            "niche_key",
            "selected_style",
        ),
        Index(
            "ix_style_preset_selections_niche_slide",
            "niche_key",
            "slide_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generation_job_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("generation_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    niche_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    slide_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    selected_style: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        index=True,
    )
