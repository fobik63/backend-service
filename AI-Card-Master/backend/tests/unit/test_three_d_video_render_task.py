"""Unit tests for Celery 360° video render task (OOM guards + Redis progress)."""

from __future__ import annotations

import gc
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.application.three_d_video_service import ThreeDVideoRenderService
from app.domain.three_d import (
    ThreeDAssetView,
    ThreeDInputType,
    ThreeDTaskStatus,
    ThreeDTaskView,
)
from app.domain.three_d_video import (
    RENDER_360_VIDEO_HARD_TIME_LIMIT_SECONDS,
    RENDER_360_VIDEO_SOFT_TIME_LIMIT_SECONDS,
    RENDER_360_VIDEO_WORKER_CONCURRENCY,
    ThreeDVideoProgressSnapshot,
    ThreeDVideoTaskStatus,
    ThreeDVideoTaskView,
    VideoAssetFormat,
    VideoBackgroundType,
    VideoRotationDirection,
    VideoUploadResult,
)
from app.infrastructure.celery_app import CELERY_THREE_D_HEAVY_QUEUE, celery_app
from app.workers import three_d_tasks as three_d_tasks_mod
from app.workers.three_d_tasks import render_360_video_task


def _video_task(
    *,
    status: ThreeDVideoTaskStatus = ThreeDVideoTaskStatus.QUEUED,
    cost_coins: int = 5,
    coins_held: bool = False,
    coins_captured: bool = False,
    coins_refunded: bool = False,
    progress_percent: int = 0,
    stage: str | None = "queued",
) -> ThreeDVideoTaskView:
    now = datetime.now(UTC)
    return ThreeDVideoTaskView(
        id=uuid4(),
        task_3d_id=uuid4(),
        user_id=uuid4(),
        status=status,
        resolution="160x90",
        fps=8,
        duration_seconds=1.0,
        rotation_direction=VideoRotationDirection.CLOCKWISE,
        elevation_angle=15.0,
        background_type=VideoBackgroundType.STUDIO_LIGHT,
        error_detail=None,
        execution_time_ms=None,
        created_at=now,
        updated_at=now,
        cost_coins=cost_coins,
        progress_percent=progress_percent,
        stage=stage,
        coins_held=coins_held,
        coins_captured=coins_captured,
        coins_refunded=coins_refunded,
        coin_hold_id=uuid4() if coins_held else None,
    )


def _source_task(task_3d_id, user_id) -> ThreeDTaskView:
    now = datetime.now(UTC)
    return ThreeDTaskView(
        id=task_3d_id,
        user_id=user_id,
        status=ThreeDTaskStatus.COMPLETED,
        input_type=ThreeDInputType.TEXT_TO_3D,
        prompt="cup",
        source_image_url=None,
        provider_name="mock",
        provider_job_id="job-1",
        cost_coins=5,
        progress_percent=100,
        stage=None,
        celery_task_id=None,
        coins_held=False,
        coins_captured=True,
        coins_refunded=False,
        polycount_target=None,
        texture_resolution=None,
        output_format=None,
        idempotency_key=None,
        error_message=None,
        execution_time_seconds=1.0,
        created_at=now,
        updated_at=now,
    )


def test_render_360_video_task_registered_on_heavy_queue_with_time_limits() -> None:
    assert "three_d.render_360_video_task" in celery_app.tasks
    routes = celery_app.conf.task_routes or {}
    assert routes["three_d.render_360_video_task"]["queue"] == CELERY_THREE_D_HEAVY_QUEUE
    assert render_360_video_task.queue == CELERY_THREE_D_HEAVY_QUEUE
    assert int(render_360_video_task.soft_time_limit) == (
        RENDER_360_VIDEO_SOFT_TIME_LIMIT_SECONDS
    )
    assert int(render_360_video_task.time_limit) == (
        RENDER_360_VIDEO_HARD_TIME_LIMIT_SECONDS
    )
    assert RENDER_360_VIDEO_HARD_TIME_LIMIT_SECONDS == 180
    assert RENDER_360_VIDEO_SOFT_TIME_LIMIT_SECONDS == 150
    assert RENDER_360_VIDEO_WORKER_CONCURRENCY == 2


@pytest.mark.asyncio
async def test_fail_and_refund_marks_failed_and_releases_hold() -> None:
    task = _video_task(
        status=ThreeDVideoTaskStatus.RENDERING,
        coins_held=True,
        cost_coins=7,
    )
    failed = replace(task, status=ThreeDVideoTaskStatus.FAILED)
    refunded = replace(failed, coins_held=False, coins_refunded=True)
    repo = AsyncMock()
    repo.get_task = AsyncMock(return_value=task)
    repo.mark_failed = AsyncMock(return_value=failed)
    repo.release_held_coins = AsyncMock(return_value=refunded)
    progress = AsyncMock()
    progress.publish = AsyncMock()

    service = ThreeDVideoRenderService(
        repo,
        three_d_repository=AsyncMock(),
        mesh_storage=AsyncMock(),
        video_storage=AsyncMock(),
        progress_cache=progress,
        cost_coins=7,
        charge_coins=True,
        max_download_bytes=10_000_000,
    )
    result = await service.fail_and_refund(
        video_task_id=task.id,
        error_detail="OutOfMemory: simulated",
    )
    assert result["status"] == "FAILED"
    assert result["coins_refunded"] is True
    repo.mark_failed.assert_awaited_once()
    repo.release_held_coins.assert_awaited_once()
    progress.publish.assert_awaited()
    snapshot: ThreeDVideoProgressSnapshot = progress.publish.await_args.args[0]
    assert snapshot.stage == "failed"


@pytest.mark.asyncio
async def test_orphaned_rendering_on_redelivery_fails_and_refunds() -> None:
    task = _video_task(
        status=ThreeDVideoTaskStatus.RENDERING,
        coins_held=True,
        cost_coins=5,
        progress_percent=40,
        stage="rendering_frames",
    )
    failed = replace(task, status=ThreeDVideoTaskStatus.FAILED)
    refunded = replace(failed, coins_held=False, coins_refunded=True)
    repo = AsyncMock()
    repo.get_task = AsyncMock(return_value=task)
    repo.mark_failed = AsyncMock(return_value=failed)
    repo.release_held_coins = AsyncMock(return_value=refunded)
    progress = AsyncMock()
    progress.publish = AsyncMock()

    service = ThreeDVideoRenderService(
        repo,
        three_d_repository=AsyncMock(),
        mesh_storage=AsyncMock(),
        video_storage=AsyncMock(),
        progress_cache=progress,
        cost_coins=5,
        charge_coins=True,
        max_download_bytes=10_000_000,
    )
    result = await service.process_render_task(task.id)
    assert result["status"] == "FAILED"
    assert "OOM" in (result.get("error") or "")
    repo.release_held_coins.assert_awaited_once()


def test_progress_snapshot_compact_shape() -> None:
    task_id = uuid4()
    snap = ThreeDVideoProgressSnapshot(
        video_task_id=task_id,
        status=ThreeDVideoTaskStatus.RENDERING,
        stage="rendering_frames",
        progress=45,
    )
    payload = snap.to_dict()
    assert payload["stage"] == "rendering_frames"
    assert payload["progress"] == 45
    restored = ThreeDVideoProgressSnapshot.from_dict(payload)
    assert restored.progress == 45
    assert restored.stage == "rendering_frames"


@pytest.mark.asyncio
async def test_process_render_publishes_progress_every_n_frames(tmp_path) -> None:
    task = _video_task(cost_coins=0, coins_held=False)
    source = _source_task(task.task_3d_id, task.user_id)
    asset = ThreeDAssetView(
        id=uuid4(),
        task_id=task.task_3d_id,
        user_id=task.user_id,
        file_glb_url=None,
        file_usdz_url=None,
        file_obj_url="meshes/demo.obj",
        preview_png_url=None,
        thumbnail_url=None,
        polycount_actual=12,
        file_size_bytes=128,
    )

    repo = AsyncMock()
    repo.get_task = AsyncMock(return_value=task)
    repo.hold_coins = AsyncMock(return_value=task)
    repo.update_progress = AsyncMock(
        side_effect=lambda **kwargs: replace(
            task,
            status=kwargs["status"],
            progress_percent=kwargs["progress_percent"],
            stage=kwargs["stage"],
        )
    )
    repo.upsert_assets = AsyncMock()
    repo.capture_held_coins = AsyncMock(return_value=task)
    repo.mark_completed = AsyncMock(
        return_value=replace(
            task,
            status=ThreeDVideoTaskStatus.COMPLETED,
            progress_percent=100,
        )
    )

    three_d_repo = AsyncMock()
    three_d_repo.get_task = AsyncMock(return_value=source)
    three_d_repo.get_asset_for_task = AsyncMock(return_value=asset)

    mesh_storage = AsyncMock()
    mesh_storage.download_bytes = AsyncMock(return_value=b"v 0 0 0\nf 1 1 1\n")

    video_storage = AsyncMock()
    video_storage.upload_bytes = AsyncMock(
        side_effect=lambda **kwargs: VideoUploadResult(
            format=kwargs["asset_format"],
            object_key=f"k/{kwargs['asset_format'].value}",
            content_type="video/mp4",
            size_bytes=16,
            presigned_url="https://example.test/x",
        )
    )

    progress = AsyncMock()
    progress.publish = AsyncMock()

    service = ThreeDVideoRenderService(
        repo,
        three_d_repository=three_d_repo,
        mesh_storage=mesh_storage,
        video_storage=video_storage,
        progress_cache=progress,
        cost_coins=0,
        charge_coins=False,
        max_download_bytes=10_000_000,
        render_backend="software",
        render_width=160,
        render_height=90,
        render_fps=8,
        render_frame_count=8,
        preview_format="gif",
        ffmpeg_bin="ffmpeg",
        mesh_cache_dir=str(tmp_path / "cache"),
        progress_frame_interval=2,
    )

    import io

    from app.services.three_d.render_engine import OrbitVideoResult

    fake_result = OrbitVideoResult(
        mp4=io.BytesIO(b"mp4-bytes"),
        preview=io.BytesIO(b"gif-bytes"),
        preview_mime="image/gif",
        width=160,
        height=90,
        fps=8,
        frame_count=8,
        backend="software",
        gl_backend="software",
    )

    class _FakeRenderer:
        def __init__(self, *_a, **_k) -> None:
            self._poses: list[Any] = []

        def __enter__(self) -> _FakeRenderer:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        async def load_mesh_from_s3(self, *_a, **_k) -> None:
            return None

        def render_orbit_video(self, *, on_frame=None):
            total = 8
            if on_frame is not None:
                for i in range(total):
                    on_frame(i, total)
            return fake_result

    with patch(
        "app.application.three_d_video_service.Offscreen3DRenderer",
        _FakeRenderer,
    ):
        result = await service.process_render_task(task.id)

    assert result["status"] == ThreeDVideoTaskStatus.COMPLETED.value

    frame_progress_payloads = [
        call.args[0].to_dict()
        for call in progress.publish.await_args_list
        if call.args and call.args[0].stage == "rendering_frames"
    ]
    assert frame_progress_payloads
    sample = frame_progress_payloads[-1]
    assert sample["stage"] == "rendering_frames"
    assert isinstance(sample["progress"], int)
    assert sample["progress"] >= 10
    # interval=2 over 8 frames → multiple Redis ticks (0,2,4,6 + last).
    assert len(frame_progress_payloads) >= 4


def test_render_360_video_task_invokes_gc_collect_in_finally() -> None:
    video_task_id = str(uuid4())
    fake_service = MagicMock()
    fake_service.attach_celery_task = AsyncMock()
    fake_service.process_render_task = AsyncMock(
        return_value={"video_task_id": video_task_id, "status": "COMPLETED"}
    )

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(three_d_tasks_mod, "SessionLocal", return_value=session),
        patch.object(
            three_d_tasks_mod,
            "build_three_d_video_render_service",
            return_value=fake_service,
        ),
        patch.object(three_d_tasks_mod, "_install_video_render_signal_handlers"),
        patch.object(three_d_tasks_mod.gc, "collect", wraps=gc.collect) as collect,
    ):
        result = render_360_video_task.run(video_task_id)

    assert result["status"] == "COMPLETED"
    assert collect.called
