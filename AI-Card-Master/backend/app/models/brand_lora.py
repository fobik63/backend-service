"""ORM models for Custom Brand LoRA profiles and reference photos."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class BrandLoraProfile(Base):
    """Personal brand style filter (Custom LoRA) owned by one user."""

    __tablename__ = "brand_lora_profiles"
    __table_args__ = (
        Index("ix_brand_lora_profiles_user_status", "user_id", "status"),
        Index(
            "uq_brand_lora_profiles_user_active",
            "user_id",
            unique=True,
            postgresql_where=text("is_active IS TRUE"),
        ),
        Index("ix_brand_lora_profiles_status_updated", "status", "updated_at"),
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
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger_word: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="queued",
        server_default=text("'queued'"),
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        index=True,
    )
    brand_style_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    lora_weights_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    provider_training_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    provider_version_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lora_scale: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.85,
        server_default=text("0.85"),
    )
    reference_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    training_progress: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    coins_charged: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    trained_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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

    references: Mapped[list[BrandLoraReference]] = relationship(
        "BrandLoraReference",
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="BrandLoraReference.position",
        lazy="selectin",
    )


class BrandLoraReference(Base):
    """One brandbook reference photo used to train a Custom LoRA."""

    __tablename__ = "brand_lora_references"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "position",
            name="uq_brand_lora_references_profile_position",
        ),
        Index("ix_brand_lora_references_profile", "profile_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brand_lora_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="image/jpeg",
        server_default=text("'image/jpeg'"),
    )
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )

    profile: Mapped[BrandLoraProfile] = relationship(
        "BrandLoraProfile",
        back_populates="references",
    )
