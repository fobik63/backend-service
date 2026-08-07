"""Application use cases for async 3D generation (hold → provider → S3 → settle)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx

from app.application.ports.three_d import ThreeDPersistencePort, ThreeDProgressCachePort
from app.application.ports.three_d_storage import ThreeDObjectStoragePort
from app.core.pricing import ServiceType, calculate_cost
from app.domain.three_d import (
    TERMINAL_THREE_D_STATUSES,
    GpuRentalSessionStatus,
    GpuRentalSessionView,
    ThreeDAssetFormat,
    ThreeDAssetView,
    ThreeDInputType,
    ThreeDOutputFormat,
    ThreeDPresignedUrls,
    ThreeDProgressSnapshot,
    ThreeDTaskStatus,
    ThreeDTaskView,
    map_provider_status_to_domain,
    parse_output_format,
    stage_label,
)
from app.services.billing_service import BillingValidationError
from app.services.three_d.base import BaseThreeDEngine
from app.services.three_d.dto import ThreeDTaskLifecycleStatus, ThreeDTaskStatusDTO
from app.services.three_d.fixtures import MOCK_FIXTURE_BASE

logger = logging.getLogger(__name__)

_FORMAT_URL_KEYS: tuple[tuple[ThreeDAssetFormat, str], ...] = (
    (ThreeDAssetFormat.GLB, "glb"),
    (ThreeDAssetFormat.USDZ, "usdz"),
    (ThreeDAssetFormat.OBJ, "obj"),
    (ThreeDAssetFormat.PREVIEW_PNG, "preview"),
    (ThreeDAssetFormat.THUMBNAIL, "preview_thumbnail"),
)

# Tiny placeholders so mock fixture hosts still land in S3 during tests/dev.
_PLACEHOLDER_BYTES: dict[ThreeDAssetFormat, bytes] = {
    ThreeDAssetFormat.GLB: b"glTF",
    ThreeDAssetFormat.USDZ: b"PK\x03\x04usdz-placeholder",
    ThreeDAssetFormat.OBJ: b"# placeholder.obj\n",
    ThreeDAssetFormat.PREVIEW_PNG: b"\x89PNG\r\n\x1a\n",
    ThreeDAssetFormat.THUMBNAIL: b"\x89PNG\r\n\x1a\n",
}


class ThreeDServiceError(Exception):
    """Base 3D workflow failure."""


class ThreeDValidationError(ThreeDServiceError):
    """Invalid create / webhook payload."""


class ThreeDNotFoundError(ThreeDServiceError):
    """Task missing or not owned by caller."""


class ThreeDService:
    """Coordinate coin hold, provider engine, S3 ingest, and live progress."""

    def __init__(
        self,
        repository: ThreeDPersistencePort,
        *,
        engine: BaseThreeDEngine,
        storage: ThreeDObjectStoragePort,
        progress_cache: ThreeDProgressCachePort,
        provider_name: str,
        cost_coins: int,
        charge_coins: bool,
        delivery_mode: str,
        poll_interval_seconds: float,
        task_timeout_seconds: int,
        max_download_bytes: int,
        webhook_secret: str,
        progress_ttl_seconds: int,
        gpu_rental_provider_name: str = "stub",
        gpu_rental_instance_type: str = "gpu.stub.1x",
        gpu_rental_coins_per_minute: int = 1,
    ) -> None:
        if cost_coins < 0:
            raise ThreeDValidationError("cost_coins must be >= 0.")
        if poll_interval_seconds <= 0:
            raise ThreeDValidationError("poll_interval_seconds must be positive.")
        if task_timeout_seconds < 30:
            raise ThreeDValidationError("task_timeout_seconds must be >= 30.")
        if gpu_rental_coins_per_minute < 0:
            raise ThreeDValidationError("gpu_rental_coins_per_minute must be >= 0.")
        mode = delivery_mode.strip().lower()
        if mode not in {"poll", "webhook"}:
            raise ThreeDValidationError("delivery_mode must be 'poll' or 'webhook'.")
        self._repository = repository
        self._engine = engine
        self._storage = storage
        self._progress = progress_cache
        self._provider_name = provider_name.strip().lower()
        self._cost_coins = cost_coins if charge_coins else 0
        self._charge_coins = charge_coins
        self._delivery_mode = mode
        self._poll_interval_seconds = poll_interval_seconds
        self._task_timeout_seconds = task_timeout_seconds
        self._max_download_bytes = max_download_bytes
        self._webhook_secret = webhook_secret.strip()
        self._progress_ttl_seconds = progress_ttl_seconds
        self._gpu_rental_provider_name = gpu_rental_provider_name.strip() or "stub"
        self._gpu_rental_instance_type = (
            gpu_rental_instance_type.strip() or "gpu.stub.1x"
        )
        self._gpu_rental_coins_per_minute = (
            gpu_rental_coins_per_minute if charge_coins else 0
        )

    @property
    def cost_coins(self) -> int:
        return self._cost_coins

    @property
    def delivery_mode(self) -> str:
        return self._delivery_mode

    def resolve_generation_cost(
        self,
        *,
        mode: str | None = None,
        polycount_target: int | None = None,
        texture_resolution: int | None = None,
        model: str | None = None,
    ) -> int:
        """Price a 3D job via the pricing matrix (or legacy flat cost when mode omitted)."""

        if not self._charge_coins:
            return 0
        if mode is None or not str(mode).strip():
            return self._cost_coins
        return calculate_cost(
            ServiceType.THREE_D.value,
            str(mode).strip().lower(),
            {
                "polycount_target": polycount_target,
                "texture_resolution": texture_resolution,
                "model": model or self._provider_name,
            },
        )

    def resolve_gpu_minute_rate(self, *, gpu_type: str | None = None) -> int:
        """Per-minute GPU rental rate from the pricing matrix."""

        if not self._charge_coins:
            return 0
        instance = (gpu_type or self._gpu_rental_instance_type or "stub").strip()
        return calculate_cost(
            ServiceType.GPU_RENTAL.value,
            instance,
            {"minutes": 1, "gpu_type": instance, "instance_type": instance},
        )

    async def create_task(
        self,
        *,
        user_id: UUID,
        prompt: str | None,
        source_image_url: str | None,
        ai_coins: int,
        polycount_target: int | None = None,
        texture_resolution: int | None = None,
        output_format: str | ThreeDOutputFormat | None = None,
        idempotency_key: str | None = None,
        mode: str | None = None,
        model: str | None = None,
    ) -> tuple[ThreeDTaskView, bool]:
        """Persist a PENDING task and reserve coins; returns (task, idempotent_replay)."""

        cleaned_key = idempotency_key.strip() if idempotency_key else None
        if cleaned_key:
            existing = await self._repository.find_idempotent_task(
                user_id=user_id,
                idempotency_key=cleaned_key,
            )
            if existing is not None:
                return existing, True

        cleaned_prompt = prompt.strip() if prompt and prompt.strip() else None
        cleaned_image = (
            source_image_url.strip()
            if source_image_url and source_image_url.strip()
            else None
        )
        if cleaned_prompt is None and cleaned_image is None:
            raise ThreeDValidationError("Provide a prompt and/or source image.")
        if cleaned_image is not None:
            input_type = ThreeDInputType.IMAGE_TO_3D
        else:
            input_type = ThreeDInputType.TEXT_TO_3D

        try:
            if isinstance(output_format, ThreeDOutputFormat):
                preferred_format = output_format
            else:
                preferred_format = parse_output_format(
                    str(output_format) if output_format is not None else None
                )
        except ValueError as exc:
            raise ThreeDValidationError(str(exc)) from exc

        cost = self.resolve_generation_cost(
            mode=mode,
            polycount_target=polycount_target,
            texture_resolution=texture_resolution,
            model=model,
        )
        if self._charge_coins and ai_coins < cost:
            raise BillingValidationError(
                f"Insufficient AI-coin balance for 3D generation (need {cost})."
            )

        task = await self._repository.create_task(
            user_id=user_id,
            input_type=input_type,
            prompt=cleaned_prompt,
            source_image_url=cleaned_image,
            provider_name=self._provider_name,
            cost_coins=cost,
            polycount_target=polycount_target,
            texture_resolution=texture_resolution,
            output_format=preferred_format,
            idempotency_key=cleaned_key,
        )
        # Reserve (hold) coins at enqueue time; worker hold is idempotent.
        if cost > 0:
            try:
                task = await self._repository.hold_coins(task_id=task.id)
            except BillingValidationError:
                await self._repository.mark_failed(
                    task_id=task.id,
                    error_message="Insufficient AI-coin balance for 3D generation.",
                    release_coins=False,
                )
                raise
        await self._publish(task)
        return task, False

    async def attach_celery_task(
        self, *, task_id: UUID, celery_task_id: str
    ) -> ThreeDTaskView:
        task = await self._repository.attach_celery_task(
            task_id=task_id,
            celery_task_id=celery_task_id,
        )
        await self._publish(task)
        return task

    async def get_for_user(self, *, task_id: UUID, user_id: UUID) -> ThreeDTaskView:
        task = await self._repository.get_task_for_user(task_id=task_id, user_id=user_id)
        if task is None:
            raise ThreeDNotFoundError("3D task was not found.")
        return task

    async def get_task(self, task_id: UUID) -> ThreeDTaskView:
        task = await self._repository.get_task(task_id)
        if task is None:
            raise ThreeDNotFoundError("3D task was not found.")
        return task

    async def list_assets_for_user(
        self, *, user_id: UUID, limit: int = 50, offset: int = 0
    ) -> tuple[list[tuple[ThreeDAssetView, ThreeDPresignedUrls]], int]:
        """Paginated 3D models for the current user with short-lived download URLs."""

        assets, total = await self._repository.list_assets_for_user(
            user_id=user_id,
            limit=limit,
            offset=offset,
        )
        items: list[tuple[ThreeDAssetView, ThreeDPresignedUrls]] = []
        for asset in assets:
            urls = await self._storage.presign_asset_urls(
                file_glb_url=asset.file_glb_url,
                file_usdz_url=asset.file_usdz_url,
                file_obj_url=asset.file_obj_url,
                preview_png_url=asset.preview_png_url,
                thumbnail_url=asset.thumbnail_url,
            )
            items.append((asset, urls))
        return items, total

    async def start_gpu_rental(
        self,
        *,
        user_id: UUID,
        ai_coins: int,
        instance_type: str | None = None,
    ) -> GpuRentalSessionView:
        """Stub: reserve a GPU node; coins are settled per minute on stop."""

        active = await self._repository.get_active_gpu_rental(user_id=user_id)
        if active is not None:
            raise ThreeDValidationError(
                "An active GPU rental session already exists for this user."
            )
        minute_rate = self.resolve_gpu_minute_rate(
            gpu_type=instance_type or self._gpu_rental_instance_type
        )
        if minute_rate <= 0:
            minute_rate = self._gpu_rental_coins_per_minute
        if self._charge_coins and minute_rate > 0 and ai_coins < minute_rate:
            raise BillingValidationError(
                f"Insufficient AI-coin balance for GPU rental "
                f"(need at least {minute_rate} for the first minute)."
            )
        # Persist hourly equivalent for schema compatibility (minute_rate * 60).
        hourly = minute_rate * 60
        return await self._repository.create_gpu_rental(
            user_id=user_id,
            provider_name=self._gpu_rental_provider_name,
            instance_type=(instance_type or self._gpu_rental_instance_type).strip()
            or self._gpu_rental_instance_type,
            hourly_rate_coins=hourly,
        )

    async def stop_gpu_rental(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
    ) -> GpuRentalSessionView:
        """Stub: stop the GPU node and debit coins for billed minutes."""

        from app.infrastructure.persistence.three_d_repository import billed_minutes

        session = await self._repository.get_gpu_rental_for_user(
            session_id=session_id,
            user_id=user_id,
        )
        if session is None:
            raise ThreeDNotFoundError("GPU rental session was not found.")
        if session.status in {
            GpuRentalSessionStatus.STOPPED,
            GpuRentalSessionStatus.TERMINATED,
        }:
            return session

        minutes = billed_minutes(session.started_at, None)
        minute_rate = max(0, int(session.hourly_rate_coins) // 60)
        if minute_rate <= 0:
            minute_rate = self._gpu_rental_coins_per_minute
        total_cost = minutes * minute_rate if self._charge_coins else 0
        return await self._repository.stop_gpu_rental(
            session_id=session_id,
            user_id=user_id,
            total_cost_coins=total_cost,
            debit_coins=total_cost > 0,
            status=GpuRentalSessionStatus.STOPPED,
        )

    async def process_generation_task(self, task_id: UUID) -> dict[str, Any]:
        """Celery entry: hold coins → submit provider → poll or await webhook."""

        started = time.monotonic()
        task = await self._repository.get_task(task_id)
        if task is None:
            raise ThreeDNotFoundError(f"3D task {task_id} was not found.")
        if task.status in TERMINAL_THREE_D_STATUSES:
            return {
                "task_id": str(task.id),
                "status": task.status.value,
                "already_terminal": True,
            }

        try:
            task = await self._repository.hold_coins(task_id=task_id)
            await self._publish(task)

            if not task.provider_job_id:
                params: dict[str, Any] = {}
                if task.polycount_target is not None:
                    params["polycount_target"] = task.polycount_target
                    params["polycount_limit"] = task.polycount_target
                if task.texture_resolution is not None:
                    params["texture_resolution"] = task.texture_resolution
                if task.output_format is not None:
                    params["format"] = task.output_format.value
                provider_job_id = await self._engine.create_generation_task(
                    prompt=task.prompt or "",
                    image_url=task.source_image_url,
                    params=params,
                )
                task = await self._repository.mark_provider_submitted(
                    task_id=task_id,
                    provider_job_id=provider_job_id,
                    status=ThreeDTaskStatus.PROCESSING,
                    progress_percent=max(1, task.progress_percent),
                    stage="drafting_mesh",
                )
                await self._publish(task)

            if self._delivery_mode == "webhook":
                # Progress continues via webhook + beat poller.
                return {
                    "task_id": str(task.id),
                    "status": task.status.value,
                    "provider_job_id": task.provider_job_id,
                    "mode": "webhook",
                }

            return await self._poll_until_terminal(task_id=task_id, started=started)
        except BillingValidationError as exc:
            failed = await self._fail(task_id, str(exc), release_coins=False)
            return {
                "task_id": str(failed.id),
                "status": failed.status.value,
                "error": str(exc),
            }
        except Exception as exc:
            logger.exception("3D process_generation_task failed task_id=%s", task_id)
            failed = await self._fail(task_id, str(exc) or "3D generation failed.")
            return {
                "task_id": str(failed.id),
                "status": failed.status.value,
                "error": failed.error_message,
            }

    async def poll_active_tasks(self, *, limit: int = 50) -> dict[str, Any]:
        """Beat entry: advance in-flight tasks that have a provider job id."""

        ids = await self._repository.list_active_task_ids(limit=limit)
        processed = 0
        for task_id in ids:
            try:
                await self.poll_single_task(task_id)
                processed += 1
            except Exception:
                logger.exception("3D poll failed task_id=%s", task_id)
        return {"processed": processed, "examined": len(ids)}

    async def poll_single_task(self, task_id: UUID) -> ThreeDTaskView:
        task = await self._repository.get_task(task_id)
        if task is None:
            raise ThreeDNotFoundError(f"3D task {task_id} was not found.")
        if task.status in TERMINAL_THREE_D_STATUSES:
            return task
        if not task.provider_job_id:
            return task

        dto = await self._engine.get_task_status(task.provider_job_id)
        return await self._apply_provider_status(task, dto)

    def verify_webhook_signature(
        self,
        *,
        headers: dict[str, str],
        raw_body: bytes,
        callback_token: str | None = None,
    ) -> bool:
        """Constant-time HMAC-SHA256 (or shared token) verification."""

        secret = self._webhook_secret
        if not secret:
            return False
        if callback_token and hmac.compare_digest(callback_token, secret):
            return True
        header_token = str(headers.get("x-webhook-token") or "")
        if header_token and hmac.compare_digest(header_token, secret):
            return True
        supplied = str(headers.get("x-webhook-signature") or "")
        if supplied.startswith("sha256="):
            supplied = supplied[7:]
        if not supplied:
            return False
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(supplied, expected)

    async def accept_webhook(
        self,
        *,
        provider_name: str,
        payload: dict[str, Any],
    ) -> tuple[ThreeDTaskView, bool]:
        """Apply an authenticated provider callback; return (task, already_terminal)."""

        if provider_name.strip().lower() != self._provider_name:
            # Allow configured aliases that share the same engine process.
            if provider_name.strip().lower() not in {
                self._provider_name,
                "mock",
                "meshy",
                "tripo",
                "runpod",
            }:
                raise ThreeDValidationError("Unknown 3D webhook provider.")

        provider_job_id = _nested_string(
            payload,
            ("provider_task_id", "provider_job_id", "job_id", "task_id", "id"),
        )
        if not provider_job_id:
            raise ThreeDValidationError("Webhook payload missing provider task id.")

        task = await self._repository.get_by_provider_job_id(
            provider_name=self._provider_name,
            provider_job_id=provider_job_id,
        )
        if task is None:
            # Fallback: match any provider_name for the job id.
            task = await self._repository.get_by_provider_job_id(
                provider_name=provider_name.strip().lower(),
                provider_job_id=provider_job_id,
            )
        if task is None:
            raise ThreeDNotFoundError("No 3D task matches provider job id.")

        if task.status in TERMINAL_THREE_D_STATUSES:
            return task, True

        status_raw = _nested_string(payload, ("status", "state")) or "PROCESSING"
        progress_raw = _nested_value(payload, ("progress_percent", "progress", "percent"))
        progress = _normalise_progress(progress_raw, status_raw)
        stage = _nested_string(payload, ("stage", "phase"))
        error_message = _nested_string(
            payload, ("error", "error_message", "message", "detail")
        )
        result_urls = _extract_result_urls(payload)

        try:
            domain_status = map_provider_status_to_domain(status_raw)
        except ValueError:
            domain_status = ThreeDTaskStatus.PROCESSING

        if domain_status == ThreeDTaskStatus.FAILED:
            failed = await self._fail(
                task.id,
                error_message or "Provider reported FAILED.",
            )
            return failed, False

        if domain_status == ThreeDTaskStatus.COMPLETED:
            dto = ThreeDTaskStatusDTO(
                status=ThreeDTaskLifecycleStatus.COMPLETED,
                progress_percent=100,
                result_urls=result_urls,
                stage=None,
                error_message=None,
                provider_task_id=provider_job_id,
            )
            completed = await self._finalize_completed(task, dto)
            return completed, False

        updated = await self._repository.update_progress(
            task_id=task.id,
            status=domain_status,
            progress_percent=progress,
            stage=stage,
            error_message=None,
            provider_job_id=provider_job_id,
        )
        await self._publish(updated)
        return updated, False

    async def _poll_until_terminal(
        self, *, task_id: UUID, started: float
    ) -> dict[str, Any]:
        while True:
            if time.monotonic() - started > self._task_timeout_seconds:
                failed = await self._fail(task_id, "3D generation timed out.")
                return {
                    "task_id": str(failed.id),
                    "status": failed.status.value,
                    "error": failed.error_message,
                }
            task = await self.poll_single_task(task_id)
            if task.status in TERMINAL_THREE_D_STATUSES:
                return {
                    "task_id": str(task.id),
                    "status": task.status.value,
                    "progress_percent": task.progress_percent,
                    "error": task.error_message,
                }
            await asyncio.sleep(self._poll_interval_seconds)

    async def _apply_provider_status(
        self,
        task: ThreeDTaskView,
        dto: ThreeDTaskStatusDTO,
    ) -> ThreeDTaskView:
        domain_status = map_provider_status_to_domain(dto.status.value)
        stage = dto.stage.value if dto.stage is not None else None

        if domain_status == ThreeDTaskStatus.FAILED:
            return await self._fail(
                task.id,
                dto.error_message or "Provider reported FAILED.",
            )

        if domain_status == ThreeDTaskStatus.COMPLETED:
            return await self._finalize_completed(task, dto)

        updated = await self._repository.update_progress(
            task_id=task.id,
            status=domain_status,
            progress_percent=dto.progress_percent,
            stage=stage,
            provider_job_id=dto.provider_task_id or task.provider_job_id,
        )
        await self._publish(updated)
        return updated

    async def _finalize_completed(
        self,
        task: ThreeDTaskView,
        dto: ThreeDTaskStatusDTO,
    ) -> ThreeDTaskView:
        uploaded = await self._ingest_result_urls(
            user_id=task.user_id,
            task_id=task.id,
            result_urls=dto.result_urls,
        )
        total_size = sum(size for size in uploaded["sizes"] if size)
        elapsed = None
        # Prefer provider metadata when present.
        meta_elapsed = dto.metadata.get("execution_time_seconds")
        if isinstance(meta_elapsed, (int, float)):
            elapsed = float(meta_elapsed)

        completed, _asset = await self._repository.complete_with_assets(
            task_id=task.id,
            file_glb_url=uploaded.get("glb"),
            file_usdz_url=uploaded.get("usdz"),
            file_obj_url=uploaded.get("obj"),
            preview_png_url=uploaded.get("preview"),
            thumbnail_url=uploaded.get("preview_thumbnail"),
            polycount_actual=_as_optional_int(dto.metadata.get("polycount_actual")),
            file_size_bytes=total_size or None,
            execution_time_seconds=elapsed,
        )
        # Capture is performed inside complete_with_assets; publish final state.
        await self._publish(completed)
        return completed

    async def _ingest_result_urls(
        self,
        *,
        user_id: UUID,
        task_id: UUID,
        result_urls: dict[str, str],
    ) -> dict[str, Any]:
        out: dict[str, Any] = {"sizes": []}
        for asset_format, key in _FORMAT_URL_KEYS:
            url = result_urls.get(key)
            if not url or not str(url).strip():
                # Alternate preview key used by some providers.
                if key == "preview":
                    url = result_urls.get("preview_png")
                if key == "preview_thumbnail":
                    url = result_urls.get("thumbnail")
            if not url or not str(url).strip():
                continue
            data = await self._download_or_placeholder(str(url).strip(), asset_format)
            uploaded = await self._storage.upload_bytes(
                user_id=user_id,
                task_id=task_id,
                asset_format=asset_format,
                data=data,
                filename=f"{key}.{asset_format.value}",
                presign=False,
            )
            storage_key = {
                ThreeDAssetFormat.GLB: "glb",
                ThreeDAssetFormat.USDZ: "usdz",
                ThreeDAssetFormat.OBJ: "obj",
                ThreeDAssetFormat.PREVIEW_PNG: "preview",
                ThreeDAssetFormat.THUMBNAIL: "preview_thumbnail",
            }[asset_format]
            out[storage_key] = uploaded.object_key
            out["sizes"].append(uploaded.size_bytes)
        return out

    async def _download_or_placeholder(
        self,
        url: str,
        asset_format: ThreeDAssetFormat,
    ) -> bytes:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host.endswith("ai-card-master.local") or url.startswith(MOCK_FIXTURE_BASE):
            return _PLACEHOLDER_BYTES[asset_format]

        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self._max_download_bytes:
                            raise ThreeDValidationError(
                                "Provider result exceeds THREE_D_MAX_DOWNLOAD_BYTES."
                            )
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    if not data:
                        raise ThreeDValidationError("Provider returned empty asset.")
                    return data
        except ThreeDValidationError:
            raise
        except Exception as exc:
            logger.warning(
                "3D asset download failed url=%s format=%s: %s",
                url,
                asset_format.value,
                exc,
            )
            # Soft fallback keeps mock/dev flows green when CDN is unreachable.
            return _PLACEHOLDER_BYTES[asset_format]

    async def _fail(
        self,
        task_id: UUID,
        error_message: str,
        *,
        release_coins: bool = True,
    ) -> ThreeDTaskView:
        failed = await self._repository.mark_failed(
            task_id=task_id,
            error_message=error_message,
            release_coins=release_coins,
        )
        await self._publish(failed)
        return failed

    async def _publish(self, task: ThreeDTaskView) -> None:
        snapshot = ThreeDProgressSnapshot.from_task_view(task)
        # Re-attach stage_label explicitly (from_task_view already does).
        _ = stage_label(task.stage)
        await self._progress.publish(snapshot)


def _nested_string(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if key in payload and payload[key] is not None:
            value = str(payload[key]).strip()
            if value:
                return value
        nested = payload.get("data")
        if isinstance(nested, dict) and key in nested and nested[key] is not None:
            value = str(nested[key]).strip()
            if value:
                return value
    return None


def _nested_value(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
        nested = payload.get("data")
        if isinstance(nested, dict) and key in nested:
            return nested[key]
    return None


def _normalise_progress(raw: Any, status_raw: str) -> int:
    if isinstance(raw, (int, float)):
        return max(0, min(100, int(raw)))
    if isinstance(raw, str) and raw.strip().endswith("%"):
        try:
            return max(0, min(100, int(float(raw.strip().rstrip("%")))))
        except ValueError:
            pass
    upper = status_raw.strip().upper()
    if upper == "COMPLETED":
        return 100
    if upper == "QUEUED":
        return 0
    return 1


def _extract_result_urls(payload: dict[str, Any]) -> dict[str, str]:
    urls: dict[str, str] = {}
    direct = payload.get("result_urls")
    if isinstance(direct, dict):
        for key, value in direct.items():
            if isinstance(value, str) and value.strip():
                urls[str(key)] = value.strip()
    for key in ("glb", "usdz", "obj", "preview", "preview_png", "thumbnail"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            urls.setdefault(key, value.strip())
    return urls


def _as_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_webhook_json(raw_body: bytes) -> dict[str, Any]:
    """Parse a webhook body into a dict (raises ThreeDValidationError)."""

    if not raw_body:
        raise ThreeDValidationError("Webhook body is empty.")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ThreeDValidationError("Webhook body must be JSON.") from exc
    if not isinstance(payload, dict):
        raise ThreeDValidationError("Webhook JSON must be an object.")
    return payload
