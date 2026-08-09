"""Unit tests for 360° video API use-cases: hold coins + FAILED/COMPLETED."""

from __future__ import annotations

import io
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.three_d_video_service import (
    ThreeDVideoNotFoundError,
    ThreeDVideoRenderService,
    ThreeDVideoValidationError,
)
from app.domain.three_d import (
    ThreeDAssetView,
    ThreeDInputType,
    ThreeDTaskStatus,
    ThreeDTaskView,
)
from app.domain.three_d_video import (
    ThreeDVideoTaskStatus,
    ThreeDVideoTaskView,
    VideoAssetView,
    VideoBackgroundType,
    VideoPresignedUrls,
    VideoRotationDirection,
    VideoUploadResult,
)
from app.services.billing_service import BillingValidationError
from app.services.three_d.render_engine import OrbitVideoResult
from app.services.three_d.styles import RenderSettingsDTO, ShadowCatcherFloorSettings


@dataclass
class _Store:
    video_tasks: dict[UUID, ThreeDVideoTaskView] = field(default_factory=dict)
    assets: dict[UUID, VideoAssetView] = field(default_factory=dict)
    balances: dict[UUID, int] = field(default_factory=dict)
    source_tasks: dict[UUID, ThreeDTaskView] = field(default_factory=dict)
    source_assets: dict[UUID, ThreeDAssetView] = field(default_factory=dict)


class FakeVideoRepository:
    def __init__(self, store: _Store) -> None:
        self._store = store

    async def create_task(self, **kwargs: Any) -> ThreeDVideoTaskView:
        now = datetime.now(UTC)
        task = ThreeDVideoTaskView(
            id=uuid4(),
            task_3d_id=kwargs["task_3d_id"],
            user_id=kwargs["user_id"],
            status=kwargs.get("status", ThreeDVideoTaskStatus.QUEUED),
            resolution=kwargs.get("resolution", "1080x1440"),
            fps=int(kwargs.get("fps", 24)),
            duration_seconds=float(kwargs.get("duration_seconds", 5.0)),
            rotation_direction=kwargs.get(
                "rotation_direction", VideoRotationDirection.CLOCKWISE
            ),
            elevation_angle=float(kwargs.get("elevation_angle", 15.0)),
            background_type=kwargs.get(
                "background_type", VideoBackgroundType.STUDIO_LIGHT
            ),
            error_detail=None,
            execution_time_ms=None,
            created_at=now,
            updated_at=now,
            cost_coins=int(kwargs.get("cost_coins", 0)),
            progress_percent=0,
            stage="queued",
            idempotency_key=kwargs.get("idempotency_key"),
            studio_settings=(
                dict(kwargs["studio_settings"])
                if isinstance(kwargs.get("studio_settings"), dict)
                else None
            ),
        )
        self._store.video_tasks[task.id] = task
        return task

    async def find_idempotent_task(
        self, *, user_id: UUID, idempotency_key: str
    ) -> ThreeDVideoTaskView | None:
        for task in self._store.video_tasks.values():
            if task.user_id == user_id and task.idempotency_key == idempotency_key:
                return task
        return None

    async def get_task(self, video_task_id: UUID) -> ThreeDVideoTaskView | None:
        return self._store.video_tasks.get(video_task_id)

    async def get_task_for_user(
        self, *, video_task_id: UUID, user_id: UUID
    ) -> ThreeDVideoTaskView | None:
        task = self._store.video_tasks.get(video_task_id)
        if task is None or task.user_id != user_id:
            return None
        return task

    async def list_tasks_for_3d(self, **_kwargs: Any) -> list[ThreeDVideoTaskView]:
        return []

    async def attach_celery_task(
        self, *, video_task_id: UUID, celery_task_id: str
    ) -> ThreeDVideoTaskView:
        task = self._store.video_tasks[video_task_id]
        updated = replace(task, celery_task_id=celery_task_id)
        self._store.video_tasks[video_task_id] = updated
        return updated

    async def hold_coins(self, *, video_task_id: UUID) -> ThreeDVideoTaskView:
        task = self._store.video_tasks[video_task_id]
        if task.coins_held or task.coins_captured:
            return task
        balance = self._store.balances.get(task.user_id, 0)
        if task.cost_coins > balance:
            raise BillingValidationError("Insufficient AI-coin balance.")
        self._store.balances[task.user_id] = balance - task.cost_coins
        updated = replace(task, coins_held=True, coin_hold_id=uuid4())
        self._store.video_tasks[video_task_id] = updated
        return updated

    async def capture_held_coins(self, *, video_task_id: UUID) -> ThreeDVideoTaskView:
        task = self._store.video_tasks[video_task_id]
        updated = replace(task, coins_held=False, coins_captured=True)
        self._store.video_tasks[video_task_id] = updated
        return updated

    async def release_held_coins(self, *, video_task_id: UUID) -> ThreeDVideoTaskView:
        task = self._store.video_tasks[video_task_id]
        if task.coins_refunded or task.coins_captured:
            return task
        if task.coins_held:
            self._store.balances[task.user_id] = (
                self._store.balances.get(task.user_id, 0) + task.cost_coins
            )
        updated = replace(task, coins_held=False, coins_refunded=True)
        self._store.video_tasks[video_task_id] = updated
        return updated

    async def update_progress(self, **kwargs: Any) -> ThreeDVideoTaskView:
        task = self._store.video_tasks[kwargs["video_task_id"]]
        updated = replace(
            task,
            status=kwargs["status"],
            progress_percent=kwargs["progress_percent"],
            stage=kwargs["stage"],
            error_detail=(
                kwargs["error_detail"]
                if kwargs.get("error_detail") is not None
                else task.error_detail
            ),
        )
        self._store.video_tasks[task.id] = updated
        return updated

    async def update_status(self, **kwargs: Any) -> ThreeDVideoTaskView:
        task = self._store.video_tasks[kwargs["video_task_id"]]
        updated = replace(
            task,
            status=kwargs["status"],
            error_detail=(
                kwargs["error_detail"]
                if kwargs.get("error_detail") is not None
                else task.error_detail
            ),
            execution_time_ms=(
                kwargs["execution_time_ms"]
                if kwargs.get("execution_time_ms") is not None
                else task.execution_time_ms
            ),
            progress_percent=(
                100
                if kwargs["status"] is ThreeDVideoTaskStatus.COMPLETED
                else task.progress_percent
            ),
        )
        self._store.video_tasks[task.id] = updated
        return updated

    async def mark_failed(
        self, *, video_task_id: UUID, error_detail: str
    ) -> ThreeDVideoTaskView:
        task = self._store.video_tasks[video_task_id]
        updated = replace(
            task,
            status=ThreeDVideoTaskStatus.FAILED,
            error_detail=error_detail,
            stage=None,
        )
        self._store.video_tasks[video_task_id] = updated
        return updated

    async def mark_completed(
        self, *, video_task_id: UUID, execution_time_ms: int | None = None
    ) -> ThreeDVideoTaskView:
        return await self.update_status(
            video_task_id=video_task_id,
            status=ThreeDVideoTaskStatus.COMPLETED,
            execution_time_ms=execution_time_ms,
        )

    async def upsert_assets(self, **kwargs: Any) -> VideoAssetView:
        asset = VideoAssetView(
            id=uuid4(),
            video_task_id=kwargs["video_task_id"],
            user_id=kwargs["user_id"],
            file_mp4_url=kwargs.get("file_mp4_url"),
            file_webp_url=kwargs.get("file_webp_url"),
            file_gif_url=kwargs.get("file_gif_url"),
            file_size_bytes=kwargs.get("file_size_bytes"),
            width=kwargs.get("width"),
            height=kwargs.get("height"),
        )
        self._store.assets[asset.video_task_id] = asset
        return asset

    async def get_assets(self, *, video_task_id: UUID) -> VideoAssetView | None:
        return self._store.assets.get(video_task_id)

    async def get_assets_for_user(
        self, *, video_task_id: UUID, user_id: UUID
    ) -> VideoAssetView | None:
        asset = self._store.assets.get(video_task_id)
        if asset is None or asset.user_id != user_id:
            return None
        return asset


class FakeThreeDRepository:
    def __init__(self, store: _Store) -> None:
        self._store = store

    async def get_task(self, task_id: UUID) -> ThreeDTaskView | None:
        return self._store.source_tasks.get(task_id)

    async def get_task_for_user(
        self, *, task_id: UUID, user_id: UUID
    ) -> ThreeDTaskView | None:
        task = self._store.source_tasks.get(task_id)
        if task is None or task.user_id != user_id:
            return None
        return task

    async def get_asset_for_task(self, task_id: UUID) -> ThreeDAssetView | None:
        return self._store.source_assets.get(task_id)


def _source(user_id: UUID, task_3d_id: UUID | None = None) -> ThreeDTaskView:
    now = datetime.now(UTC)
    tid = task_3d_id or uuid4()
    return ThreeDTaskView(
        id=tid,
        user_id=user_id,
        status=ThreeDTaskStatus.COMPLETED,
        input_type=ThreeDInputType.TEXT_TO_3D,
        prompt="bottle",
        source_image_url=None,
        provider_name="mock",
        provider_job_id="job-1",
        cost_coins=30,
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


def _glb_asset(task_3d_id: UUID, user_id: UUID) -> ThreeDAssetView:
    return ThreeDAssetView(
        id=uuid4(),
        task_id=task_3d_id,
        user_id=user_id,
        file_glb_url=f"three-d/{user_id}/{task_3d_id}/model.glb",
        file_usdz_url=None,
        file_obj_url=None,
        preview_png_url=None,
        thumbnail_url=None,
        polycount_actual=1200,
        file_size_bytes=4096,
    )


def _build_service(
    store: _Store,
    *,
    cost_coins: int = 10,
    charge_coins: bool = True,
) -> ThreeDVideoRenderService:
    video_storage = AsyncMock()
    video_storage.upload_bytes = AsyncMock(
        side_effect=lambda **kwargs: VideoUploadResult(
            format=kwargs["asset_format"],
            object_key=f"k/{kwargs['asset_format'].value}",
            content_type="video/mp4",
            size_bytes=32,
            presigned_url=f"https://cdn.test/{kwargs['asset_format'].value}",
        )
    )
    video_storage.presign_asset_urls = AsyncMock(
        side_effect=lambda **kwargs: VideoPresignedUrls(
            mp4=(
                f"https://cdn.test/{kwargs['file_mp4_url']}"
                if kwargs.get("file_mp4_url")
                else None
            ),
            webp=(
                f"https://cdn.test/{kwargs['file_webp_url']}"
                if kwargs.get("file_webp_url")
                else None
            ),
            gif=(
                f"https://cdn.test/{kwargs['file_gif_url']}"
                if kwargs.get("file_gif_url")
                else None
            ),
        )
    )
    return ThreeDVideoRenderService(
        FakeVideoRepository(store),
        three_d_repository=FakeThreeDRepository(store),
        mesh_storage=AsyncMock(),
        video_storage=video_storage,
        progress_cache=AsyncMock(publish=AsyncMock(), get=AsyncMock(return_value=None)),
        cost_coins=cost_coins,
        charge_coins=charge_coins,
        max_download_bytes=10_000_000,
        render_backend="software",
        render_width=108,
        render_height=144,
        render_fps=8,
        render_frame_count=8,
        preview_format="webp",
        progress_frame_interval=2,
    )


class _FakeRenderer:
    def __init__(self, *_a: object, **_k: object) -> None:
        self._poses: list[Any] = []

    def __enter__(self) -> _FakeRenderer:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    async def load_mesh_from_s3(self, *_a: object, **_k: object) -> None:
        return None

    def render_orbit_video(self, *, on_frame=None):
        total = 4
        if on_frame is not None:
            for i in range(total):
                on_frame(i, total)
        return OrbitVideoResult(
            mp4=io.BytesIO(b"mp4-bytes"),
            preview=io.BytesIO(b"webp-bytes"),
            preview_mime="image/webp",
            width=108,
            height=144,
            fps=8,
            frame_count=total,
            backend="software",
            gl_backend="software",
        )


@pytest.mark.asyncio
async def test_create_render_holds_ten_coins_and_requires_glb() -> None:
    user_id = uuid4()
    store = _Store(balances={user_id: 50})
    source = _source(user_id)
    store.source_tasks[source.id] = source
    store.source_assets[source.id] = _glb_asset(source.id, user_id)
    service = _build_service(store, cost_coins=10)

    settings = RenderSettingsDTO.for_marketplace_card(lighting_preset="studio_soft")
    task, replay = await service.create_render_task(
        user_id=user_id,
        task_3d_id=source.id,
        ai_coins=50,
        render_settings=settings,
        fps=24,
        duration_seconds=2.0,
    )
    assert replay is False
    assert task.cost_coins == 10
    assert task.coins_held is True
    assert task.resolution == "1080x1440"
    assert store.balances[user_id] == 40

    store_no_glb = _Store(balances={user_id: 50})
    store_no_glb.source_tasks[source.id] = source
    store_no_glb.source_assets[source.id] = replace(
        _glb_asset(source.id, user_id), file_glb_url=None, file_obj_url="x.obj"
    )
    service_no_glb = _build_service(store_no_glb, cost_coins=10)
    with pytest.raises(ThreeDVideoValidationError, match=r"\.glb"):
        await service_no_glb.create_render_task(
            user_id=user_id,
            task_3d_id=source.id,
            ai_coins=50,
            render_settings=settings,
        )


@pytest.mark.asyncio
async def test_create_render_persists_studio_lighting_for_worker() -> None:
    """API lighting / shadow-catcher must survive into RenderEngineConfig."""

    user_id = uuid4()
    store = _Store(balances={user_id: 50})
    source = _source(user_id)
    store.source_tasks[source.id] = source
    store.source_assets[source.id] = _glb_asset(source.id, user_id)
    service = _build_service(store, cost_coins=0)

    settings = RenderSettingsDTO.for_marketplace_card(
        lighting_preset="cyberpunk",
        shadow_catcher=ShadowCatcherFloorSettings(
            enabled=True,
            opacity=0.4,
            shadow_strength=0.9,
        ),
    )
    task, _ = await service.create_render_task(
        user_id=user_id,
        task_3d_id=source.id,
        ai_coins=50,
        render_settings=settings,
        fps=12,
        duration_seconds=1.0,
    )
    assert task.studio_settings is not None
    assert task.studio_settings["lighting_preset"] == "cyberpunk"
    assert task.studio_settings["shadow_catcher"]["shadow_strength"] == pytest.approx(
        0.9
    )

    cfg = service._build_render_engine_config(
        task=task,
        width=1080,
        height=1440,
        frame_count=12,
    )
    assert cfg.lighting_preset.value == "cyberpunk"
    assert cfg.resolved_shadow_catcher().shadow_strength == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_create_render_rejects_insufficient_balance() -> None:
    user_id = uuid4()
    store = _Store(balances={user_id: 3})
    source = _source(user_id)
    store.source_tasks[source.id] = source
    store.source_assets[source.id] = _glb_asset(source.id, user_id)
    service = _build_service(store, cost_coins=10)

    with pytest.raises(BillingValidationError, match="need 10"):
        await service.create_render_task(
            user_id=user_id,
            task_3d_id=source.id,
            ai_coins=3,
            render_settings=RenderSettingsDTO.for_square(side=512),
        )


@pytest.mark.asyncio
async def test_process_render_completed_captures_coins_with_mocked_renderer() -> None:
    user_id = uuid4()
    store = _Store(balances={user_id: 100})
    source = _source(user_id)
    store.source_tasks[source.id] = source
    store.source_assets[source.id] = _glb_asset(source.id, user_id)
    service = _build_service(store, cost_coins=10)

    task, _ = await service.create_render_task(
        user_id=user_id,
        task_3d_id=source.id,
        ai_coins=100,
        render_settings=RenderSettingsDTO.for_marketplace_card(),
        duration_seconds=1.0,
        fps=8,
    )
    assert store.balances[user_id] == 90

    with patch(
        "app.application.three_d_video_service.Offscreen3DRenderer",
        _FakeRenderer,
    ):
        result = await service.process_render_task(task.id)

    assert result["status"] == ThreeDVideoTaskStatus.COMPLETED.value
    final = store.video_tasks[task.id]
    assert final.status is ThreeDVideoTaskStatus.COMPLETED
    assert final.coins_captured is True
    assert final.coins_refunded is False
    assert store.balances[user_id] == 90  # held then captured (no refund)
    assert task.id in store.assets
    assert store.assets[task.id].file_mp4_url is not None

    view, assets, urls = await service.get_result_for_user(
        video_task_id=task.id, user_id=user_id
    )
    assert view.status is ThreeDVideoTaskStatus.COMPLETED
    assert assets is not None
    assert urls.mp4 is not None
    assert urls.webp is not None


@pytest.mark.asyncio
async def test_process_render_failed_refunds_held_coins() -> None:
    user_id = uuid4()
    store = _Store(balances={user_id: 100})
    source = _source(user_id)
    store.source_tasks[source.id] = source
    store.source_assets[source.id] = _glb_asset(source.id, user_id)
    service = _build_service(store, cost_coins=10)

    task, _ = await service.create_render_task(
        user_id=user_id,
        task_3d_id=source.id,
        ai_coins=100,
        render_settings=RenderSettingsDTO.for_square(side=256),
        duration_seconds=1.0,
        fps=8,
    )
    assert store.balances[user_id] == 90

    class _BoomRenderer(_FakeRenderer):
        def render_orbit_video(self, *, on_frame=None):
            raise MemoryError("simulated OOM")

    with patch(
        "app.application.three_d_video_service.Offscreen3DRenderer",
        _BoomRenderer,
    ):
        result = await service.process_render_task(task.id)

    assert result["status"] == ThreeDVideoTaskStatus.FAILED.value
    assert result["coins_refunded"] is True
    final = store.video_tasks[task.id]
    assert final.status is ThreeDVideoTaskStatus.FAILED
    assert final.coins_refunded is True
    assert final.coins_captured is False
    assert store.balances[user_id] == 100

    view, assets, urls = await service.get_result_for_user(
        video_task_id=task.id, user_id=user_id
    )
    assert view.status is ThreeDVideoTaskStatus.FAILED
    assert view.error_detail is not None
    assert assets is None
    assert urls.mp4 is None


@pytest.mark.asyncio
async def test_get_result_for_user_not_found() -> None:
    store = _Store()
    service = _build_service(store, charge_coins=False, cost_coins=0)
    with pytest.raises(ThreeDVideoNotFoundError):
        await service.get_result_for_user(video_task_id=uuid4(), user_id=uuid4())


def test_http_render_endpoint_returns_202_with_video_task_id() -> None:
    """Integration-style TestClient: enqueue returns 202 + video_task_id."""

    from app.api import three_d_video as video_api

    user_id = uuid4()
    task_3d_id = uuid4()
    video_task_id = uuid4()
    now = datetime.now(UTC)
    queued = ThreeDVideoTaskView(
        id=video_task_id,
        task_3d_id=task_3d_id,
        user_id=user_id,
        status=ThreeDVideoTaskStatus.QUEUED,
        resolution="1080x1440",
        fps=24,
        duration_seconds=5.0,
        rotation_direction=VideoRotationDirection.CLOCKWISE,
        elevation_angle=20.0,
        background_type=VideoBackgroundType.GRADIENT,
        error_detail=None,
        execution_time_ms=None,
        created_at=now,
        updated_at=now,
        cost_coins=10,
        progress_percent=0,
        stage="queued",
        coins_held=True,
        celery_task_id=None,
    )

    fake_user = MagicMock()
    fake_user.id = user_id
    fake_user.ai_coins = 100

    fake_service = AsyncMock()
    fake_service.create_render_task = AsyncMock(return_value=(queued, False))
    fake_service.attach_celery_task = AsyncMock(
        return_value=replace(queued, celery_task_id="celery-xyz")
    )

    app = FastAPI()
    app.include_router(video_api.router)

    async def _override_user() -> Any:
        return fake_user

    async def _override_svc() -> Any:
        return fake_service

    app.dependency_overrides[video_api.get_current_user] = _override_user
    app.dependency_overrides[video_api.get_three_d_video_svc] = _override_svc

    celery_result = MagicMock()
    celery_result.id = "celery-xyz"

    with (
        patch.object(video_api.celery_app, "send_task", return_value=celery_result),
        TestClient(app) as client,
    ):
        response = client.post(
            "/api/v1/3d/video/render",
            json={
                "task_3d_id": str(task_3d_id),
                "render_settings": {
                    "aspect_ratio": "3:4",
                    "width": 1080,
                    "height": 1440,
                    "lighting_preset": "studio_soft",
                    "background_mode": "gradient",
                },
                "fps": 24,
                "duration_seconds": 5.0,
                "rotation_direction": "clockwise",
            },
        )

    assert response.status_code == 202
    body = response.json()
    assert body["video_task_id"] == str(video_task_id)
    assert body["status"] == "QUEUED"
    assert body["cost_coins"] == 10
    assert body["celery_task_id"] == "celery-xyz"
    assert body["status_url"] == f"/api/v1/3d/video/{video_task_id}"
    assert body["ws_url"] == f"/ws/v1/3d/video/{video_task_id}"
    fake_service.create_render_task.assert_awaited()


def test_http_get_returns_completed_urls_and_failed_status() -> None:
    from app.api import three_d_video as video_api

    user_id = uuid4()
    video_task_id = uuid4()
    now = datetime.now(UTC)

    completed = ThreeDVideoTaskView(
        id=video_task_id,
        task_3d_id=uuid4(),
        user_id=user_id,
        status=ThreeDVideoTaskStatus.COMPLETED,
        resolution="1080x1440",
        fps=24,
        duration_seconds=5.0,
        rotation_direction=VideoRotationDirection.CLOCKWISE,
        elevation_angle=20.0,
        background_type=VideoBackgroundType.GRADIENT,
        error_detail=None,
        execution_time_ms=1200,
        created_at=now,
        updated_at=now,
        cost_coins=10,
        progress_percent=100,
        stage=None,
        coins_captured=True,
    )
    assets = VideoAssetView(
        id=uuid4(),
        video_task_id=video_task_id,
        user_id=user_id,
        file_mp4_url="three-d-video/a/b/mp4.mp4",
        file_webp_url="three-d-video/a/b/webp.webp",
        file_gif_url=None,
        file_size_bytes=2048,
        width=1080,
        height=1440,
    )
    urls = VideoPresignedUrls(
        mp4="https://cdn.test/mp4.mp4",
        webp="https://cdn.test/webp.webp",
        gif=None,
    )

    fake_user = MagicMock()
    fake_user.id = user_id
    fake_service = AsyncMock()
    fake_service.get_result_for_user = AsyncMock(
        return_value=(completed, assets, urls)
    )

    app = FastAPI()
    app.include_router(video_api.router)
    app.dependency_overrides[video_api.get_current_user] = lambda: fake_user
    app.dependency_overrides[video_api.get_three_d_video_svc] = lambda: fake_service

    with TestClient(app) as client:
        ok = client.get(f"/api/v1/3d/video/{video_task_id}")
    assert ok.status_code == 200
    payload = ok.json()
    assert payload["status"] == "COMPLETED"
    assert payload["file_mp4_url"] == "https://cdn.test/mp4.mp4"
    assert payload["file_webp_url"] == "https://cdn.test/webp.webp"
    assert payload["coins_captured"] is True

    failed = replace(
        completed,
        status=ThreeDVideoTaskStatus.FAILED,
        error_detail="FFmpegEncodeError: boom",
        coins_captured=False,
        coins_refunded=True,
        progress_percent=40,
    )
    fake_service.get_result_for_user = AsyncMock(
        return_value=(failed, None, VideoPresignedUrls())
    )
    with TestClient(app) as client:
        bad = client.get(f"/api/v1/3d/video/{video_task_id}")
    assert bad.status_code == 200
    failed_body = bad.json()
    assert failed_body["status"] == "FAILED"
    assert failed_body["error_detail"] == "FFmpegEncodeError: boom"
    assert failed_body["file_mp4_url"] is None
    assert failed_body["coins_refunded"] is True
