"""ORM models for 3D generation, 360° video tasks, assets, and GPU rentals."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ThreeDTask(Base):
    """Async 3D generation job owned by one user."""

    __tablename__ = "three_d_tasks"
    __table_args__ = (
        Index("ix_three_d_tasks_user_status", "user_id", "status"),
        Index("ix_three_d_tasks_user_created", "user_id", "created_at"),
        Index("ix_three_d_tasks_provider_job_id", "provider_job_id"),
        Index(
            "uq_three_d_tasks_user_idempotency",
            "user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
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
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="PENDING",
        server_default=text("'PENDING'"),
        index=True,
    )
    input_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cost_coins: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    progress_percent: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    coins_held: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    coins_captured: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    coins_refunded: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    coin_hold_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("coin_holds.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    polycount_target: Mapped[int | None] = mapped_column(Integer, nullable=True)
    texture_resolution: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        onupdate=datetime.utcnow,
    )

    assets: Mapped[list[ThreeDAsset]] = relationship(
        "ThreeDAsset",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    video_tasks: Mapped[list[ThreeDVideoTask]] = relationship(
        "ThreeDVideoTask",
        back_populates="source_task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ThreeDAsset(Base):
    """Result files (GLB/USDZ/OBJ + previews) produced by a 3D task.

    URL columns store Selectel/MinIO object keys (or provider CDN URLs).
    Presigned download URLs are generated at read time via ThreeDObjectStorage.
    """

    __tablename__ = "three_d_assets"
    __table_args__ = (
        Index("ix_three_d_assets_task_id", "task_id"),
        Index("ix_three_d_assets_user_id", "user_id"),
        Index("ix_three_d_assets_user_task", "user_id", "task_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("three_d_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_glb_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_usdz_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_obj_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_png_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    polycount_actual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    task: Mapped[ThreeDTask] = relationship(
        "ThreeDTask",
        back_populates="assets",
    )


class GpuRentalSession(Base):
    """Reserved schema for future GPU instance rental billing."""

    __tablename__ = "gpu_rental_sessions"
    __table_args__ = (
        Index("ix_gpu_rental_sessions_user_status", "user_id", "status"),
        Index("ix_gpu_rental_sessions_user_started", "user_id", "started_at"),
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
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    instance_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="STARTING",
        server_default=text("'STARTING'"),
        index=True,
    )
    hourly_rate_coins: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    total_cost_coins: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )


class ThreeDVideoTask(Base):
    """360° orbital video render job derived from a completed 3D mesh task."""

    __tablename__ = "three_d_video_tasks"
    __table_args__ = (
        Index("ix_three_d_video_tasks_user_status", "user_id", "status"),
        Index("ix_three_d_video_tasks_user_created", "user_id", "created_at"),
        Index("ix_three_d_video_tasks_task_3d_id", "task_3d_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    task_3d_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("three_d_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="QUEUED",
        server_default=text("'QUEUED'"),
        index=True,
    )
    resolution: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="1080x1440",
        server_default=text("'1080x1440'"),
    )
    fps: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=24,
        server_default=text("24"),
    )
    duration_seconds: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=5.0,
        server_default=text("5.0"),
    )
    rotation_direction: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="clockwise",
        server_default=text("'clockwise'"),
    )
    elevation_angle: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=15.0,
        server_default=text("15.0"),
    )
    background_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="STUDIO_LIGHT",
        server_default=text("'STUDIO_LIGHT'"),
    )
    cost_coins: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    progress_percent: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    coins_held: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    coins_captured: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    coins_refunded: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    coin_hold_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("coin_holds.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    studio_settings: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        onupdate=datetime.utcnow,
    )

    source_task: Mapped[ThreeDTask] = relationship(
        "ThreeDTask",
        back_populates="video_tasks",
    )
    assets: Mapped[list[VideoAsset]] = relationship(
        "VideoAsset",
        back_populates="video_task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class VideoAsset(Base):
    """Result video containers (MP4 / WebP / GIF) for one 360° video task.

    URL columns store Selectel/MinIO object keys. Presigned download URLs are
    generated at read time via ``VideoAssetUploader``.
    """

    __tablename__ = "video_assets"
    __table_args__ = (
        Index("ix_video_assets_video_task_id", "video_task_id"),
        Index(
            "uq_video_assets_video_task_id",
            "video_task_id",
            unique=True,
        ),
        Index("ix_video_assets_user_id", "user_id"),
        Index("ix_video_assets_user_video_task", "user_id", "video_task_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    video_task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("three_d_video_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_mp4_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_webp_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_gif_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    video_task: Mapped[ThreeDVideoTask] = relationship(
        "ThreeDVideoTask",
        back_populates="assets",
    )
