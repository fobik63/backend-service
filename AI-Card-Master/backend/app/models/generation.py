"""Generation ORM model and related schema contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Generation(Base):
    """Image generation record.

    Keeps audit trail for user prompts and generated assets.
    """

    __tablename__ = "generations"
    __table_args__ = (
        Index("ix_generations_user_id_created_at", "user_id", "created_at"),
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
        index=True,
    )
    input_image_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    result_image_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    prompt_used: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        index=True,
    )

    user = relationship("User", back_populates="generations")
