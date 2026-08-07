"""Unit tests for async 3D pipeline: hold coins, poll/webhook, progress Redis."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.application.three_d_service import (
    ThreeDNotFoundError,
    ThreeDService,
    ThreeDValidationError,
    parse_webhook_json,
)
from app.domain.three_d import (
    ThreeDAssetFormat,
    ThreeDAssetView,
    ThreeDInputType,
    ThreeDOutputFormat,
    ThreeDProgressSnapshot,
    ThreeDTaskStatus,
    ThreeDTaskView,
    ThreeDUploadResult,
    map_provider_status_to_domain,
    stage_label,
)
from app.services.billing_service import BillingValidationError
from app.services.three_d import (
    MockThreeDEngineAdapter,
    ThreeDGenerationStage,
    ThreeDTaskLifecycleStatus,
)


@dataclass
class _FakeTaskStore:
    tasks: dict[UUID, ThreeDTaskView] = field(default_factory=dict)
    assets: dict[UUID, ThreeDAssetView] = field(default_factory=dict)
    balances: dict[UUID, int] = field(default_factory=dict)


class FakeThreeDRepository:
    def __init__(self, store: _FakeTaskStore) -> None:
        self._store = store

    async def create_task(
        self,
        *,
        user_id: UUID,
        input_type: ThreeDInputType,
        prompt: str | None,
        source_image_url: str | None,
        provider_name: str,
        cost_coins: int,
        polycount_target: int | None,
        texture_resolution: int | None,
        output_format: ThreeDOutputFormat | None = None,
        idempotency_key: str | None = None,
    ) -> ThreeDTaskView:
        now = datetime.now(UTC)
        task = ThreeDTaskView(
            id=uuid4(),
            user_id=user_id,
            status=ThreeDTaskStatus.PENDING,
            input_type=input_type,
            prompt=prompt,
            source_image_url=source_image_url,
            provider_name=provider_name,
            provider_job_id=None,
            cost_coins=cost_coins,
            progress_percent=0,
            stage=None,
            celery_task_id=None,
            coins_held=False,
            coins_captured=False,
            coins_refunded=False,
            polycount_target=polycount_target,
            texture_resolution=texture_resolution,
            output_format=output_format,
            idempotency_key=idempotency_key,
            error_message=None,
            execution_time_seconds=None,
            created_at=now,
            updated_at=now,
        )
        self._store.tasks[task.id] = task
        return task

    async def find_idempotent_task(
        self, *, user_id: UUID, idempotency_key: str
    ) -> ThreeDTaskView | None:
        for task in self._store.tasks.values():
            if task.user_id == user_id and task.idempotency_key == idempotency_key:
                return task
        return None

    async def get_task(self, task_id: UUID) -> ThreeDTaskView | None:
        return self._store.tasks.get(task_id)

    async def get_task_for_user(
        self, *, task_id: UUID, user_id: UUID
    ) -> ThreeDTaskView | None:
        task = self._store.tasks.get(task_id)
        if task is None or task.user_id != user_id:
            return None
        return task

    async def attach_celery_task(
        self, *, task_id: UUID, celery_task_id: str
    ) -> ThreeDTaskView:
        task = self._store.tasks[task_id]
        updated = _replace(task, celery_task_id=celery_task_id)
        self._store.tasks[task_id] = updated
        return updated

    async def hold_coins(self, *, task_id: UUID) -> ThreeDTaskView:
        task = self._store.tasks[task_id]
        if task.coins_held or task.coins_captured:
            return task
        balance = self._store.balances.get(task.user_id, 0)
        if task.cost_coins > balance:
            raise BillingValidationError("Insufficient AI-coin balance.")
        self._store.balances[task.user_id] = balance - task.cost_coins
        updated = _replace(task, coins_held=True)
        self._store.tasks[task_id] = updated
        return updated

    async def capture_held_coins(self, *, task_id: UUID) -> ThreeDTaskView:
        task = self._store.tasks[task_id]
        updated = _replace(task, coins_held=False, coins_captured=True)
        self._store.tasks[task_id] = updated
        return updated

    async def release_held_coins(self, *, task_id: UUID) -> ThreeDTaskView:
        task = self._store.tasks[task_id]
        if task.coins_refunded or task.coins_captured:
            return task
        if task.coins_held:
            self._store.balances[task.user_id] = (
                self._store.balances.get(task.user_id, 0) + task.cost_coins
            )
        updated = _replace(task, coins_held=False, coins_refunded=True)
        self._store.tasks[task_id] = updated
        return updated

    async def mark_provider_submitted(
        self,
        *,
        task_id: UUID,
        provider_job_id: str,
        status: ThreeDTaskStatus,
        progress_percent: int,
        stage: str | None,
    ) -> ThreeDTaskView:
        task = self._store.tasks[task_id]
        updated = _replace(
            task,
            provider_job_id=provider_job_id,
            status=status,
            progress_percent=progress_percent,
            stage=stage,
        )
        self._store.tasks[task_id] = updated
        return updated

    async def update_progress(
        self,
        *,
        task_id: UUID,
        status: ThreeDTaskStatus,
        progress_percent: int,
        stage: str | None,
        error_message: str | None = None,
        provider_job_id: str | None = None,
    ) -> ThreeDTaskView:
        task = self._store.tasks[task_id]
        updated = _replace(
            task,
            status=status,
            progress_percent=progress_percent,
            stage=stage,
            error_message=error_message if error_message is not None else task.error_message,
            provider_job_id=provider_job_id or task.provider_job_id,
        )
        self._store.tasks[task_id] = updated
        return updated

    async def mark_failed(
        self,
        *,
        task_id: UUID,
        error_message: str,
        release_coins: bool = True,
    ) -> ThreeDTaskView:
        task = self._store.tasks[task_id]
        coins_held = task.coins_held
        coins_refunded = task.coins_refunded
        if release_coins and task.coins_held and not task.coins_captured and not task.coins_refunded:
            self._store.balances[task.user_id] = (
                self._store.balances.get(task.user_id, 0) + task.cost_coins
            )
            coins_held = False
            coins_refunded = True
        updated = _replace(
            task,
            status=ThreeDTaskStatus.FAILED,
            error_message=error_message,
            stage=None,
            coins_held=coins_held,
            coins_refunded=coins_refunded,
        )
        self._store.tasks[task_id] = updated
        return updated

    async def complete_with_assets(
        self,
        *,
        task_id: UUID,
        file_glb_url: str | None,
        file_usdz_url: str | None,
        file_obj_url: str | None,
        preview_png_url: str | None,
        thumbnail_url: str | None,
        polycount_actual: int | None,
        file_size_bytes: int | None,
        execution_time_seconds: float | None,
    ) -> tuple[ThreeDTaskView, ThreeDAssetView]:
        task = self._store.tasks[task_id]
        updated = _replace(
            task,
            status=ThreeDTaskStatus.COMPLETED,
            progress_percent=100,
            stage=None,
            error_message=None,
            execution_time_seconds=execution_time_seconds,
            coins_held=False,
            coins_captured=True,
        )
        self._store.tasks[task_id] = updated
        asset = ThreeDAssetView(
            id=uuid4(),
            task_id=task_id,
            user_id=task.user_id,
            file_glb_url=file_glb_url,
            file_usdz_url=file_usdz_url,
            file_obj_url=file_obj_url,
            preview_png_url=preview_png_url,
            thumbnail_url=thumbnail_url,
            polycount_actual=polycount_actual,
            file_size_bytes=file_size_bytes,
        )
        self._store.assets[task_id] = asset
        return updated, asset

    async def get_asset_for_task(self, task_id: UUID) -> ThreeDAssetView | None:
        return self._store.assets.get(task_id)

    async def list_assets_for_user(
        self, *, user_id: UUID, limit: int, offset: int
    ) -> tuple[tuple[ThreeDAssetView, ...], int]:
        owned = [a for a in self._store.assets.values() if a.user_id == user_id]
        total = len(owned)
        page = owned[offset : offset + limit]
        return tuple(page), total

    async def list_active_task_ids(self, *, limit: int) -> tuple[UUID, ...]:
        active = [
            t.id
            for t in self._store.tasks.values()
            if t.status in {ThreeDTaskStatus.PENDING, ThreeDTaskStatus.PROCESSING}
            and t.provider_job_id
        ]
        return tuple(active[:limit])

    async def get_by_provider_job_id(
        self, *, provider_name: str, provider_job_id: str
    ) -> ThreeDTaskView | None:
        for task in self._store.tasks.values():
            if (
                task.provider_name == provider_name
                and task.provider_job_id == provider_job_id
            ):
                return task
        return None

    async def get_active_gpu_rental(self, *, user_id: UUID):
        return None

    async def create_gpu_rental(self, **kwargs):
        raise NotImplementedError

    async def get_gpu_rental_for_user(self, *, session_id: UUID, user_id: UUID):
        return None

    async def stop_gpu_rental(self, **kwargs):
        raise NotImplementedError


class FakeProgressCache:
    def __init__(self) -> None:
        self.snapshots: list[ThreeDProgressSnapshot] = []
        self._latest: dict[UUID, ThreeDProgressSnapshot] = {}

    async def publish(self, snapshot: ThreeDProgressSnapshot) -> None:
        self.snapshots.append(snapshot)
        self._latest[snapshot.task_id] = snapshot

    async def get(self, task_id: UUID) -> ThreeDProgressSnapshot | None:
        return self._latest.get(task_id)

    async def subscribe_payloads(
        self, task_id: UUID
    ) -> AsyncIterator[dict[str, Any]]:
        if False:  # pragma: no cover
            yield {}
        return


class FakeStorage:
    def __init__(self) -> None:
        self.uploads: list[tuple[ThreeDAssetFormat, int]] = []

    async def upload_bytes(
        self,
        *,
        user_id: UUID,
        task_id: UUID,
        asset_format: ThreeDAssetFormat,
        data: bytes,
        filename: str | None = None,
        presign: bool = True,
    ) -> ThreeDUploadResult:
        self.uploads.append((asset_format, len(data)))
        return ThreeDUploadResult(
            format=asset_format,
            object_key=f"three-d/{user_id}/{task_id}/{asset_format.value}",
            content_type="application/octet-stream",
            size_bytes=len(data),
            presigned_url="",
        )

    async def upload_file(self, **kwargs: Any) -> ThreeDUploadResult:
        raise NotImplementedError

    async def generate_presigned_url(self, object_key: str, *, expires_in: int | None = None) -> str:
        return f"https://s3.example/{object_key}"

    async def presign_asset_urls(self, **kwargs: Any) -> Any:
        from app.domain.three_d import ThreeDPresignedUrls

        return ThreeDPresignedUrls(
            glb=f"https://s3.example/{kwargs.get('file_glb_url')}"
            if kwargs.get("file_glb_url")
            else None,
            usdz=f"https://s3.example/{kwargs.get('file_usdz_url')}"
            if kwargs.get("file_usdz_url")
            else None,
            obj=f"https://s3.example/{kwargs.get('file_obj_url')}"
            if kwargs.get("file_obj_url")
            else None,
            preview_png=f"https://s3.example/{kwargs.get('preview_png_url')}"
            if kwargs.get("preview_png_url")
            else None,
            thumbnail=f"https://s3.example/{kwargs.get('thumbnail_url')}"
            if kwargs.get("thumbnail_url")
            else None,
        )

    async def delete_object(self, object_key: str) -> None:
        return None


def _replace(task: ThreeDTaskView, **kwargs: Any) -> ThreeDTaskView:
    data = {
        "id": task.id,
        "user_id": task.user_id,
        "status": task.status,
        "input_type": task.input_type,
        "prompt": task.prompt,
        "source_image_url": task.source_image_url,
        "provider_name": task.provider_name,
        "provider_job_id": task.provider_job_id,
        "cost_coins": task.cost_coins,
        "progress_percent": task.progress_percent,
        "stage": task.stage,
        "celery_task_id": task.celery_task_id,
        "coins_held": task.coins_held,
        "coins_captured": task.coins_captured,
        "coins_refunded": task.coins_refunded,
        "coin_hold_id": task.coin_hold_id,
        "polycount_target": task.polycount_target,
        "texture_resolution": task.texture_resolution,
        "output_format": task.output_format,
        "idempotency_key": task.idempotency_key,
        "error_message": task.error_message,
        "execution_time_seconds": task.execution_time_seconds,
        "created_at": task.created_at,
        "updated_at": datetime.now(UTC),
    }
    data.update(kwargs)
    return ThreeDTaskView(**data)


def _build_service(
    *,
    store: _FakeTaskStore,
    engine: MockThreeDEngineAdapter | None = None,
    delivery_mode: str = "poll",
    cost_coins: int = 5,
    webhook_secret: str = "test-secret",
) -> tuple[ThreeDService, FakeProgressCache, FakeStorage]:
    progress = FakeProgressCache()
    storage = FakeStorage()
    service = ThreeDService(
        FakeThreeDRepository(store),
        engine=engine
        or MockThreeDEngineAdapter(
            duration_seconds=0.0,
            queue_delay_seconds=0.0,
            ticks_per_stage=1,
        ),
        storage=storage,
        progress_cache=progress,
        provider_name="mock",
        cost_coins=cost_coins,
        charge_coins=True,
        delivery_mode=delivery_mode,
        poll_interval_seconds=0.01,
        task_timeout_seconds=30,
        max_download_bytes=10_000_000,
        webhook_secret=webhook_secret,
        progress_ttl_seconds=3600,
    )
    return service, progress, storage


def test_map_provider_status_and_stage_labels() -> None:
    assert map_provider_status_to_domain("QUEUED") == ThreeDTaskStatus.PENDING
    assert map_provider_status_to_domain("PROCESSING") == ThreeDTaskStatus.PROCESSING
    assert stage_label("drafting_mesh") == "генерация сетки"
    assert stage_label("generating_textures") == "текстурирование"


@pytest.mark.asyncio
async def test_process_generation_holds_captures_and_uploads() -> None:
    user_id = uuid4()
    store = _FakeTaskStore(balances={user_id: 20})
    service, progress, storage = _build_service(store=store, cost_coins=5)

    task, _replay = await service.create_task(
        user_id=user_id,
        prompt="red sneakers",
        source_image_url=None,
        ai_coins=20,
    )
    assert task.coins_held is True
    assert store.balances[user_id] == 15
    result = await service.process_generation_task(task.id)

    assert result["status"] == ThreeDTaskStatus.COMPLETED.value
    final = store.tasks[task.id]
    assert final.coins_captured is True
    assert final.coins_held is False
    assert final.coins_refunded is False
    assert store.balances[user_id] == 15
    assert final.progress_percent == 100
    assert any(fmt == ThreeDAssetFormat.GLB for fmt, _ in storage.uploads)
    assert any(fmt == ThreeDAssetFormat.USDZ for fmt, _ in storage.uploads)
    assert progress.snapshots
    assert progress.snapshots[-1].status == ThreeDTaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_process_generation_releases_hold_on_failure() -> None:
    user_id = uuid4()
    store = _FakeTaskStore(balances={user_id: 10})
    engine = MockThreeDEngineAdapter(
        duration_seconds=0.0,
        queue_delay_seconds=0.0,
        ticks_per_stage=1,
    )
    service, _progress, _storage = _build_service(
        store=store, engine=engine, cost_coins=3
    )
    task, _replay = await service.create_task(
        user_id=user_id,
        prompt="broken",
        source_image_url=None,
        ai_coins=10,
    )
    # Force provider failure via simulate_failure param after create in process —
    # recreate by monkeypatching engine create to use simulate_failure.
    original_create = engine.create_generation_task

    async def _failing_create(prompt: str, image_url: str | None, params: dict) -> str:
        return await original_create(prompt, image_url, {**params, "simulate_failure": True})

    engine.create_generation_task = _failing_create  # type: ignore[method-assign]

    result = await service.process_generation_task(task.id)
    assert result["status"] == ThreeDTaskStatus.FAILED.value
    final = store.tasks[task.id]
    assert final.coins_refunded is True
    assert final.coins_held is False
    assert store.balances[user_id] == 10


@pytest.mark.asyncio
async def test_webhook_hmac_and_progress_update() -> None:
    user_id = uuid4()
    store = _FakeTaskStore(balances={user_id: 10})
    secret = "whsec_test"
    service, progress, _storage = _build_service(
        store=store,
        delivery_mode="webhook",
        cost_coins=2,
        webhook_secret=secret,
    )
    task, _replay = await service.create_task(
        user_id=user_id,
        prompt="bag",
        source_image_url=None,
        ai_coins=10,
    )
    assert task.coins_held is True
    assert store.balances[user_id] == 8
    # Submit without polling to completion.
    result = await service.process_generation_task(task.id)
    assert result["mode"] == "webhook"
    assert store.balances[user_id] == 8
    mid = store.tasks[task.id]
    assert mid.provider_job_id
    assert mid.coins_held is True

    body = (
        b'{"provider_task_id":"%s","status":"PROCESSING",'
        b'"progress_percent":25,"stage":"drafting_mesh"}'
        % mid.provider_job_id.encode()
    )
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert service.verify_webhook_signature(
        headers={"x-webhook-signature": f"sha256={signature}"},
        raw_body=body,
    )
    assert not service.verify_webhook_signature(
        headers={"x-webhook-signature": "sha256=deadbeef"},
        raw_body=body,
    )

    payload = parse_webhook_json(body)
    updated, already = await service.accept_webhook(provider_name="mock", payload=payload)
    assert already is False
    assert updated.progress_percent == 25
    assert updated.stage == "drafting_mesh"
    assert progress.snapshots[-1].stage_label == "генерация сетки"

    done_payload = {
        "provider_task_id": mid.provider_job_id,
        "status": "COMPLETED",
        "progress_percent": 100,
        "result_urls": {
            "glb": "https://fixtures.ai-card-master.local/3d/a.glb",
            "usdz": "https://fixtures.ai-card-master.local/3d/a.usdz",
        },
    }
    completed, _ = await service.accept_webhook(
        provider_name="mock", payload=done_payload
    )
    assert completed.status == ThreeDTaskStatus.COMPLETED
    assert completed.coins_captured is True
    assert store.balances[user_id] == 8  # held coins captured, not refunded


@pytest.mark.asyncio
async def test_create_task_idempotency_replay() -> None:
    user_id = uuid4()
    store = _FakeTaskStore(balances={user_id: 20})
    service, _, _ = _build_service(store=store, cost_coins=5)
    first, replay1 = await service.create_task(
        user_id=user_id,
        prompt="chair",
        source_image_url=None,
        ai_coins=20,
        idempotency_key="idem-3d-key-01",
        output_format="GLB",
        polycount_target=50_000,
    )
    second, replay2 = await service.create_task(
        user_id=user_id,
        prompt="chair",
        source_image_url=None,
        ai_coins=20,
        idempotency_key="idem-3d-key-01",
    )
    assert replay1 is False
    assert replay2 is True
    assert first.id == second.id
    assert store.balances[user_id] == 15
    assert first.output_format == ThreeDOutputFormat.GLB
    assert len(store.tasks) == 1


@pytest.mark.asyncio
async def test_insufficient_balance_on_create() -> None:
    user_id = uuid4()
    store = _FakeTaskStore(balances={user_id: 1})
    service, _, _ = _build_service(store=store, cost_coins=5)
    with pytest.raises(BillingValidationError):
        await service.create_task(
            user_id=user_id,
            prompt="x",
            source_image_url=None,
            ai_coins=1,
        )


@pytest.mark.asyncio
async def test_get_for_user_not_found() -> None:
    store = _FakeTaskStore()
    service, _, _ = _build_service(store=store)
    with pytest.raises(ThreeDNotFoundError):
        await service.get_for_user(task_id=uuid4(), user_id=uuid4())


def test_parse_webhook_json_rejects_invalid() -> None:
    with pytest.raises(ThreeDValidationError):
        parse_webhook_json(b"")
    with pytest.raises(ThreeDValidationError):
        parse_webhook_json(b"[1,2]")
