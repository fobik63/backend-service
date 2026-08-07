"""Composition root for 360° video render (API + Celery + WebSocket)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.three_d_video_service import ThreeDVideoRenderService
from app.core.config import get_settings
from app.infrastructure.persistence.three_d_repository import ThreeDRepository
from app.infrastructure.persistence.three_d_video_repository import ThreeDVideoRepository
from app.infrastructure.three_d_video_progress_cache import RedisThreeDVideoProgressCache
from app.services.three_d.storage import get_three_d_object_storage
from app.services.three_d.video_storage import get_video_asset_uploader


def build_three_d_video_render_service(
    db_session: AsyncSession,
) -> ThreeDVideoRenderService:
    """Wire ports for HTTP handlers, WebSocket, and Celery workers."""

    settings = get_settings()
    cache_dir = (settings.three_d_mesh_cache_dir or "").strip() or None
    return ThreeDVideoRenderService(
        ThreeDVideoRepository(db_session),
        three_d_repository=ThreeDRepository(db_session),
        mesh_storage=get_three_d_object_storage(),
        video_storage=get_video_asset_uploader(),
        progress_cache=RedisThreeDVideoProgressCache(
            ttl_seconds=settings.three_d_progress_ttl_seconds,
        ),
        cost_coins=settings.three_d_video_cost_coins,
        charge_coins=settings.generation_charge_coins,
        max_download_bytes=settings.three_d_max_download_bytes,
        render_backend=settings.three_d_render_backend,
        render_width=settings.three_d_render_width,
        render_height=settings.three_d_render_height,
        render_fps=settings.three_d_render_fps,
        render_frame_count=settings.three_d_render_frame_count,
        render_fill_ratio=settings.three_d_render_fill_ratio,
        preview_format=settings.three_d_render_preview_format,
        ffmpeg_bin=settings.three_d_ffmpeg_bin,
        mesh_cache_dir=cache_dir,
        progress_frame_interval=settings.three_d_video_progress_frame_interval,
    )
