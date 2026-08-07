"""Application use cases for Celery 360° orbital video rendering."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from app.application.ports.three_d import ThreeDPersistencePort
from app.application.ports.three_d_storage import ThreeDObjectStoragePort
from app.application.ports.three_d_video import (
    ThreeDVideoPersistencePort,
    ThreeDVideoProgressCachePort,
)
from app.application.ports.three_d_video_storage import VideoAssetUploaderPort
from app.domain.three_d import TERMINAL_THREE_D_STATUSES, ThreeDTaskStatus
from app.domain.three_d_video import (
    DEFAULT_VIDEO_DURATION_SECONDS,
    DEFAULT_VIDEO_FPS,
    RENDER_360_VIDEO_PROGRESS_FRAME_INTERVAL,
    ThreeDVideoProgressSnapshot,
    ThreeDVideoTaskStatus,
    ThreeDVideoTaskView,
    VideoAssetFormat,
    VideoAssetView,
    VideoBackgroundType,
    VideoPresignedUrls,
    VideoRotationDirection,
    parse_rotation_direction,
    video_stage_label,
)
from app.services.billing_service import BillingValidationError
from app.services.three_d.errors import (
    FFmpegEncodeError,
    HeadlessGLError,
    MeshLoadError,
    RenderEngineError,
)
from app.services.three_d.render_engine import Offscreen3DRenderer, RenderEngineConfig
from app.services.three_d.styles import (
    RenderSettingsDTO,
    StudioBackgroundMode,
)

logger = logging.getLogger(__name__)

_BACKGROUND_RGB: dict[VideoBackgroundType, tuple[int, int, int]] = {
    VideoBackgroundType.TRANSPARENT: (0, 0, 0),
    VideoBackgroundType.GRADIENT: (32, 36, 48),
    VideoBackgroundType.SOLID_COLOR: (245, 245, 248),
    VideoBackgroundType.STUDIO_LIGHT: (24, 28, 36),
}

_STUDIO_BG_TO_VIDEO: dict[StudioBackgroundMode, VideoBackgroundType] = {
    StudioBackgroundMode.TRANSPARENT: VideoBackgroundType.TRANSPARENT,
    StudioBackgroundMode.GRADIENT: VideoBackgroundType.GRADIENT,
    StudioBackgroundMode.SOLID: VideoBackgroundType.SOLID_COLOR,
}


class ThreeDVideoServiceError(Exception):
    """Base 360° video workflow failure."""


class ThreeDVideoValidationError(ThreeDVideoServiceError):
    """Invalid video task parameters."""


class ThreeDVideoNotFoundError(ThreeDVideoServiceError):
    """Video task missing."""


class ThreeDVideoRenderService:
    """Coordinate hold → mesh download → orbit render → S3 → settle/refund."""

    def __init__(
        self,
        repository: ThreeDVideoPersistencePort,
        *,
        three_d_repository: ThreeDPersistencePort,
        mesh_storage: ThreeDObjectStoragePort,
        video_storage: VideoAssetUploaderPort,
        progress_cache: ThreeDVideoProgressCachePort,
        cost_coins: int,
        charge_coins: bool,
        max_download_bytes: int,
        render_backend: str = "auto",
        render_width: int = 1280,
        render_height: int = 720,
        render_fps: int = 24,
        render_frame_count: int = 120,
        render_fill_ratio: float = 0.825,
        preview_format: str = "webp",
        ffmpeg_bin: str = "ffmpeg",
        mesh_cache_dir: str | None = None,
        progress_frame_interval: int = RENDER_360_VIDEO_PROGRESS_FRAME_INTERVAL,
    ) -> None:
        if cost_coins < 0:
            raise ThreeDVideoValidationError("cost_coins must be >= 0.")
        if progress_frame_interval < 1:
            raise ThreeDVideoValidationError("progress_frame_interval must be >= 1.")
        self._repository = repository
        self._three_d_repository = three_d_repository
        self._mesh_storage = mesh_storage
        self._video_storage = video_storage
        self._progress = progress_cache
        self._cost_coins = cost_coins if charge_coins else 0
        self._charge_coins = charge_coins
        self._max_download_bytes = max_download_bytes
        self._render_backend = render_backend
        self._render_width = render_width
        self._render_height = render_height
        self._render_fps = render_fps
        self._render_frame_count = render_frame_count
        self._render_fill_ratio = render_fill_ratio
        self._preview_format = preview_format
        self._ffmpeg_bin = ffmpeg_bin
        self._mesh_cache_dir = mesh_cache_dir
        self._progress_frame_interval = progress_frame_interval

    async def create_render_task(
        self,
        *,
        user_id: UUID,
        task_3d_id: UUID,
        ai_coins: int,
        render_settings: RenderSettingsDTO,
        fps: int = DEFAULT_VIDEO_FPS,
        duration_seconds: float = DEFAULT_VIDEO_DURATION_SECONDS,
        rotation_direction: str | VideoRotationDirection = VideoRotationDirection.CLOCKWISE,
        idempotency_key: str | None = None,
    ) -> tuple[ThreeDVideoTaskView, bool]:
        """Validate GLB source, freeze coins, persist ``QUEUED`` video task.

        Returns ``(task, idempotent_replay)``.
        """

        cleaned_key = (
            idempotency_key.strip()
            if idempotency_key and idempotency_key.strip()
            else None
        )
        if cleaned_key is not None:
            existing = await self._repository.find_idempotent_task(
                user_id=user_id,
                idempotency_key=cleaned_key,
            )
            if existing is not None:
                return existing, True

        await self._ensure_ready_glb(task_3d_id=task_3d_id, user_id=user_id)

        if fps <= 0:
            raise ThreeDVideoValidationError("fps must be positive.")
        if duration_seconds <= 0:
            raise ThreeDVideoValidationError("duration_seconds must be positive.")
        try:
            direction = (
                rotation_direction
                if isinstance(rotation_direction, VideoRotationDirection)
                else parse_rotation_direction(str(rotation_direction))
            )
        except ValueError as exc:
            raise ThreeDVideoValidationError(str(exc)) from exc

        cost = int(self._cost_coins)
        if self._charge_coins and cost > 0 and ai_coins < cost:
            raise BillingValidationError(
                f"Insufficient AI-coin balance for 360° video (need {cost})."
            )

        background = self._background_from_studio(render_settings)
        resolution = f"{int(render_settings.width)}x{int(render_settings.height)}"
        studio_payload = render_settings.model_dump(mode="json")

        task = await self._repository.create_task(
            task_3d_id=task_3d_id,
            user_id=user_id,
            resolution=resolution,
            fps=int(fps),
            duration_seconds=float(duration_seconds),
            rotation_direction=direction,
            elevation_angle=float(render_settings.elevation_degrees),
            background_type=background,
            status=ThreeDVideoTaskStatus.QUEUED,
            cost_coins=cost,
            idempotency_key=cleaned_key,
            studio_settings=studio_payload,
        )

        if cost > 0:
            try:
                task = await self._repository.hold_coins(video_task_id=task.id)
            except BillingValidationError:
                await self._repository.mark_failed(
                    video_task_id=task.id,
                    error_detail="Insufficient AI-coin balance for 360° video.",
                )
                raise

        await self._publish_progress_raw(
            video_task_id=task.id,
            status=ThreeDVideoTaskStatus.QUEUED,
            stage="queued",
            progress=0,
        )
        return task, False

    async def get_for_user(
        self, *, video_task_id: UUID, user_id: UUID
    ) -> ThreeDVideoTaskView:
        task = await self._repository.get_task_for_user(
            video_task_id=video_task_id,
            user_id=user_id,
        )
        if task is None:
            raise ThreeDVideoNotFoundError("360° video task was not found.")
        return task

    async def get_result_for_user(
        self, *, video_task_id: UUID, user_id: UUID
    ) -> tuple[ThreeDVideoTaskView, VideoAssetView | None, VideoPresignedUrls]:
        """Return task status plus short-lived MP4/WebP/GIF download URLs."""

        task = await self.get_for_user(video_task_id=video_task_id, user_id=user_id)
        assets = await self._repository.get_assets_for_user(
            video_task_id=video_task_id,
            user_id=user_id,
        )
        if assets is None:
            return task, None, VideoPresignedUrls()
        urls = await self._video_storage.presign_asset_urls(
            file_mp4_url=assets.file_mp4_url,
            file_webp_url=assets.file_webp_url,
            file_gif_url=assets.file_gif_url,
        )
        return task, assets, urls

    async def attach_celery_task(
        self, *, video_task_id: UUID, celery_task_id: str
    ) -> ThreeDVideoTaskView:
        return await self._repository.attach_celery_task(
            video_task_id=video_task_id,
            celery_task_id=celery_task_id,
        )

    async def fail_and_refund(
        self,
        *,
        video_task_id: UUID,
        error_detail: str,
    ) -> dict[str, Any]:
        """Mark FAILED and automatically return frozen coins (OOM / crash path)."""

        task = await self._repository.get_task(video_task_id)
        if task is None:
            raise ThreeDVideoNotFoundError(f"Video task {video_task_id} was not found.")

        if task.status is not ThreeDVideoTaskStatus.FAILED:
            task = await self._repository.mark_failed(
                video_task_id=video_task_id,
                error_detail=error_detail,
            )
        if task.coins_held and not task.coins_captured and not task.coins_refunded:
            task = await self._repository.release_held_coins(video_task_id=video_task_id)

        await self._publish_progress_raw(
            video_task_id=video_task_id,
            status=ThreeDVideoTaskStatus.FAILED,
            stage="failed",
            progress=int(task.progress_percent),
            error_detail=error_detail,
        )
        return {
            "video_task_id": str(video_task_id),
            "status": ThreeDVideoTaskStatus.FAILED.value,
            "error": error_detail[:500],
            "coins_refunded": bool(task.coins_refunded),
        }

    async def process_render_task(self, video_task_id: UUID) -> dict[str, Any]:
        """Run the full orbit render pipeline for one video task."""

        started = time.perf_counter()
        task = await self._repository.get_task(video_task_id)
        if task is None:
            raise ThreeDVideoNotFoundError(f"Video task {video_task_id} was not found.")

        if task.status is ThreeDVideoTaskStatus.COMPLETED:
            return {
                "video_task_id": str(video_task_id),
                "status": task.status.value,
                "idempotent": True,
            }

        # Worker died mid-render (OOM killer / hard time limit) and Celery
        # redelivered the job — settle as FAILED + refund instead of looping.
        if (
            task.status is ThreeDVideoTaskStatus.RENDERING
            and task.coins_held
            and not task.coins_captured
        ):
            logger.warning(
                "Orphaned RENDERING video task detected (likely OOM/crash); "
                "failing and refunding video_task_id=%s",
                video_task_id,
            )
            return await self.fail_and_refund(
                video_task_id=video_task_id,
                error_detail=(
                    "Render worker crashed or was killed (OOM / hard time limit). "
                    "Frozen coins were automatically refunded."
                ),
            )

        if task.status is ThreeDVideoTaskStatus.FAILED:
            return {
                "video_task_id": str(video_task_id),
                "status": task.status.value,
                "error": task.error_detail,
            }

        try:
            if self._charge_coins and int(task.cost_coins) > 0 and not task.coins_held:
                try:
                    task = await self._repository.hold_coins(video_task_id=video_task_id)
                except BillingValidationError as exc:
                    return await self.fail_and_refund(
                        video_task_id=video_task_id,
                        error_detail=f"Insufficient balance to freeze coins: {exc}",
                    )

            await self._set_stage(
                video_task_id,
                status=ThreeDVideoTaskStatus.RENDERING,
                stage="loading_mesh",
                progress=5,
            )

            mesh_key, source_name = await self._resolve_mesh_object_key(task.task_3d_id)
            width, height = self._resolve_resolution(task.resolution)
            frame_count = max(
                2,
                int(round(float(task.duration_seconds) * max(1, int(task.fps)))),
            )

            cfg = self._build_render_engine_config(
                task=task,
                width=width,
                height=height,
                frame_count=frame_count,
            )

            loop = asyncio.get_running_loop()

            def _on_frame(frame_index: int, total_frames: int) -> None:
                if (
                    frame_index % self._progress_frame_interval != 0
                    and frame_index + 1 < total_frames
                ):
                    return
                pct = int(((frame_index + 1) / max(total_frames, 1)) * 90) + 5
                pct = min(95, pct)
                fut = asyncio.run_coroutine_threadsafe(
                    self._publish_progress_raw(
                        video_task_id=video_task_id,
                        status=ThreeDVideoTaskStatus.RENDERING,
                        stage="rendering_frames",
                        progress=pct,
                    ),
                    loop,
                )
                try:
                    fut.result(timeout=2.0)
                except Exception:
                    logger.debug(
                        "Video progress Redis publish skipped frame=%s",
                        frame_index,
                        exc_info=True,
                    )

            with Offscreen3DRenderer(cfg) as renderer:
                await renderer.load_mesh_from_s3(
                    mesh_key,
                    storage=self._mesh_storage,  # type: ignore[arg-type]
                    max_bytes=self._max_download_bytes,
                    source_name=source_name,
                )
                if task.rotation_direction is VideoRotationDirection.COUNTER_CLOCKWISE:
                    poses = getattr(renderer, "_poses", None)
                    if isinstance(poses, list):
                        poses.reverse()

                await self._set_stage(
                    video_task_id,
                    status=ThreeDVideoTaskStatus.RENDERING,
                    stage="rendering_frames",
                    progress=10,
                )

                # Run CPU/GPU encode off the event loop so Redis progress
                # coroutines scheduled from ``_on_frame`` can flush live.
                result = await asyncio.to_thread(
                    renderer.render_orbit_video,
                    on_frame=_on_frame,
                )

            await self._set_stage(
                video_task_id,
                status=ThreeDVideoTaskStatus.ENCODING,
                stage="uploading",
                progress=96,
            )

            mp4_upload = await self._video_storage.upload_bytes(
                user_id=task.user_id,
                video_task_id=video_task_id,
                asset_format=VideoAssetFormat.MP4,
                data=result.mp4_bytes,
            )
            preview_format = (
                VideoAssetFormat.WEBP
                if result.preview_mime == "image/webp"
                else VideoAssetFormat.GIF
            )
            preview_upload = await self._video_storage.upload_bytes(
                user_id=task.user_id,
                video_task_id=video_task_id,
                asset_format=preview_format,
                data=result.preview_bytes,
            )

            file_webp = (
                preview_upload.object_key
                if preview_format is VideoAssetFormat.WEBP
                else None
            )
            file_gif = (
                preview_upload.object_key
                if preview_format is VideoAssetFormat.GIF
                else None
            )
            await self._repository.upsert_assets(
                video_task_id=video_task_id,
                user_id=task.user_id,
                file_mp4_url=mp4_upload.object_key,
                file_webp_url=file_webp,
                file_gif_url=file_gif,
                file_size_bytes=mp4_upload.size_bytes + preview_upload.size_bytes,
                width=result.width,
                height=result.height,
            )

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            refreshed = await self._repository.get_task(video_task_id)
            if (
                refreshed is not None
                and refreshed.coins_held
                and not refreshed.coins_captured
            ):
                await self._repository.capture_held_coins(video_task_id=video_task_id)

            task = await self._repository.mark_completed(
                video_task_id=video_task_id,
                execution_time_ms=elapsed_ms,
            )
            await self._publish_progress_raw(
                video_task_id=video_task_id,
                status=ThreeDVideoTaskStatus.COMPLETED,
                stage="finalizing",
                progress=100,
            )
            return {
                "video_task_id": str(video_task_id),
                "status": ThreeDVideoTaskStatus.COMPLETED.value,
                "execution_time_ms": elapsed_ms,
                "frame_count": result.frame_count,
                "backend": result.backend,
            }
        except (
            MeshLoadError,
            HeadlessGLError,
            FFmpegEncodeError,
            RenderEngineError,
            ThreeDVideoValidationError,
            BillingValidationError,
            LookupError,
            MemoryError,
            OSError,
        ) as exc:
            logger.exception(
                "360° video render failed video_task_id=%s", video_task_id
            )
            return await self.fail_and_refund(
                video_task_id=video_task_id,
                error_detail=f"{type(exc).__name__}: {exc}",
            )

    async def _ensure_ready_glb(self, *, task_3d_id: UUID, user_id: UUID) -> str:
        """Require a completed source 3D task owned by the user with a .glb key."""

        source = await self._three_d_repository.get_task_for_user(
            task_id=task_3d_id,
            user_id=user_id,
        )
        if source is None:
            raise ThreeDVideoNotFoundError("Source 3D task was not found.")
        if source.status is not ThreeDTaskStatus.COMPLETED:
            if source.status in TERMINAL_THREE_D_STATUSES:
                raise ThreeDVideoValidationError(
                    f"Source 3D task is {source.status.value}."
                )
            raise ThreeDVideoValidationError(
                "Source 3D task is not COMPLETED yet; wait for the .glb asset."
            )
        assets = await self._three_d_repository.get_asset_for_task(task_3d_id)
        glb_key = (
            assets.file_glb_url.strip()
            if assets is not None and assets.file_glb_url
            else None
        )
        if not glb_key:
            raise ThreeDVideoValidationError(
                "Source 3D task has no ready .glb asset for video render."
            )
        return glb_key

    @staticmethod
    def _background_from_studio(
        settings: RenderSettingsDTO,
    ) -> VideoBackgroundType:
        mapped = _STUDIO_BG_TO_VIDEO.get(settings.background_mode)
        if mapped is not None:
            return mapped
        return VideoBackgroundType.STUDIO_LIGHT

    async def _resolve_mesh_object_key(
        self, task_3d_id: UUID
    ) -> tuple[str, str]:
        source = await self._three_d_repository.get_task(task_3d_id)
        if source is None:
            raise ThreeDVideoValidationError(
                f"Source 3D task {task_3d_id} was not found."
            )
        if source.status is not ThreeDTaskStatus.COMPLETED:
            if source.status in TERMINAL_THREE_D_STATUSES:
                raise ThreeDVideoValidationError(
                    f"Source 3D task {task_3d_id} is {source.status.value}."
                )
            raise ThreeDVideoValidationError(
                f"Source 3D task {task_3d_id} is not COMPLETED yet."
            )
        assets = await self._three_d_repository.get_asset_for_task(task_3d_id)
        if assets is None:
            raise ThreeDVideoValidationError(
                f"Source 3D task {task_3d_id} has no stored mesh assets."
            )
        for key, name in (
            (assets.file_glb_url, "mesh.glb"),
            (assets.file_obj_url, "mesh.obj"),
            (assets.file_usdz_url, "mesh.usdz"),
        ):
            if key and str(key).strip():
                return str(key).strip(), name
        raise ThreeDVideoValidationError(
            f"Source 3D task {task_3d_id} has no downloadable mesh key."
        )

    def _build_render_engine_config(
        self,
        *,
        task: ThreeDVideoTaskView,
        width: int,
        height: int,
        frame_count: int,
    ) -> RenderEngineConfig:
        """Rebuild engine config, restoring studio lighting / shadow catcher."""

        cache_dir = Path(self._mesh_cache_dir) if self._mesh_cache_dir else None
        fps = int(task.fps) or self._render_fps
        if isinstance(task.studio_settings, dict) and task.studio_settings:
            try:
                studio = RenderSettingsDTO.from_persisted(task.studio_settings)
                return RenderEngineConfig.from_studio_settings(
                    studio,
                    fps=fps,
                    frame_count=frame_count,
                    backend=self._render_backend,  # type: ignore[arg-type]
                    preview_format=self._preview_format,  # type: ignore[arg-type]
                    cache_dir=cache_dir,
                    ffmpeg_bin=self._ffmpeg_bin,
                    background_rgb=_BACKGROUND_RGB.get(
                        task.background_type, studio.background_rgb
                    ),
                )
            except Exception:
                logger.warning(
                    "Invalid studio_settings on video_task_id=%s; using defaults",
                    task.id,
                    exc_info=True,
                )

        return RenderEngineConfig(
            width=width,
            height=height,
            fps=fps,
            frame_count=frame_count,
            fill_ratio=self._render_fill_ratio,
            elevation_degrees=float(task.elevation_angle),
            background_rgb=_BACKGROUND_RGB.get(
                task.background_type, (24, 28, 36)
            ),
            backend=self._render_backend,  # type: ignore[arg-type]
            preview_format=self._preview_format,  # type: ignore[arg-type]
            ffmpeg_bin=self._ffmpeg_bin,
            cache_dir=cache_dir,
        )

    def _resolve_resolution(self, resolution: str) -> tuple[int, int]:
        parts = resolution.lower().split("x")
        if len(parts) != 2:
            return self._render_width, self._render_height
        try:
            return max(64, int(parts[0])), max(64, int(parts[1]))
        except ValueError:
            return self._render_width, self._render_height

    async def _set_stage(
        self,
        video_task_id: UUID,
        *,
        status: ThreeDVideoTaskStatus,
        stage: str,
        progress: int,
    ) -> ThreeDVideoTaskView:
        task = await self._repository.update_progress(
            video_task_id=video_task_id,
            status=status,
            progress_percent=progress,
            stage=stage,
        )
        await self._publish_progress_raw(
            video_task_id=video_task_id,
            status=status,
            stage=stage,
            progress=progress,
        )
        return task

    async def _publish_progress_raw(
        self,
        *,
        video_task_id: UUID,
        status: ThreeDVideoTaskStatus,
        stage: str,
        progress: int,
        error_detail: str | None = None,
    ) -> None:
        snapshot = ThreeDVideoProgressSnapshot(
            video_task_id=video_task_id,
            status=status,
            stage=stage,
            progress=max(0, min(100, int(progress))),
            stage_label=video_stage_label(stage),
            error_detail=error_detail,
        )
        await self._progress.publish(snapshot)


__all__ = [
    "ThreeDVideoNotFoundError",
    "ThreeDVideoRenderService",
    "ThreeDVideoServiceError",
    "ThreeDVideoValidationError",
]
