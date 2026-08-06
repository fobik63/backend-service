"""Application use cases for Smart Variant Sync (1 photo → N color jobs)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.application.ports.smart_variant import (
    FabricRecolorPort,
    SmartVariantPersistencePort,
    VariantPushNotifierPort,
)
from app.domain.generation import (
    GenerationEngineMode,
    GenerationPostProcessingMode,
)
from app.domain.smart_variant import (
    ColorSpec,
    VariantItemStatus,
    VariantNotifyChannel,
    VariantSyncStatus,
    VariantSyncView,
    build_color_overlay_texts,
    build_sync_ready_push_payload,
    build_sync_ready_telegram_message,
    parse_color_specs,
    validate_source_image,
)
from app.services.billing_service import BillingValidationError


class TelegramUserNotifierPort(Protocol):
    """Duck-typed Telegram sender for sync-ready messages."""

    async def send_message(self, *, chat_id: int, text: str) -> bool:
        """Return True when Telegram accepted the message."""

        raise NotImplementedError


class ObjectStoragePort(Protocol):
    """Minimal S3 port used by smart variant create / recolor flows."""

    async def upload_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        presign: bool = True,
    ) -> object: ...

    async def download_bytes(self, *, object_key: str, max_bytes: int) -> bytes: ...


class GenerationJobFactoryPort(Protocol):
    """Creates a durable single-product generation job for one color variant."""

    async def create_for_variant_item(
        self,
        *,
        user_id: UUID,
        subscription_status: str,
        engine_mode: GenerationEngineMode,
        post_processing_mode: GenerationPostProcessingMode,
        input_object_key: str,
        product_category: str | None,
        apply_text_overlays: bool,
        overlay_texts: dict[str, str],
        idempotency_key: str,
    ) -> UUID:
        """Return the created (or idempotently replayed) generation job id."""


class SmartVariantError(Exception):
    """Base Smart Variant Sync workflow failure."""


class SmartVariantValidationError(SmartVariantError):
    """Request or color list is invalid."""


class SmartVariantNotFoundError(SmartVariantError):
    """Sync job was not found for the user."""


class SmartVariantService:
    """Coordinate source upload, AI recolor, child jobs, and notifications."""

    def __init__(
        self,
        repository: SmartVariantPersistencePort,
        *,
        storage: ObjectStoragePort,
        recolor: FabricRecolorPort,
        job_factory: GenerationJobFactoryPort,
        max_colors: int,
        max_image_bytes: int,
        coins_per_color: int,
        charge_coins: bool,
        telegram: TelegramUserNotifierPort | None = None,
        push: VariantPushNotifierPort | None = None,
    ) -> None:
        if max_colors <= 0:
            raise SmartVariantValidationError("max_colors must be positive.")
        if max_image_bytes <= 0:
            raise SmartVariantValidationError("size limits must be positive.")
        if coins_per_color <= 0:
            raise SmartVariantValidationError("coins_per_color must be positive.")
        self._repository = repository
        self._storage = storage
        self._recolor = recolor
        self._job_factory = job_factory
        self._max_colors = max_colors
        self._max_image_bytes = max_image_bytes
        self._coins_per_color = coins_per_color
        self._charge_coins = charge_coins
        self._telegram = telegram
        self._push = push

    @property
    def max_colors(self) -> int:
        return self._max_colors

    @property
    def max_image_bytes(self) -> int:
        return self._max_image_bytes

    def estimate_coin_cost(self, color_count: int) -> int:
        """Coins required to enqueue ``color_count`` child jobs."""

        if not self._charge_coins:
            return 0
        return max(0, color_count) * self._coins_per_color

    async def create_sync(
        self,
        *,
        user_id: UUID,
        subscription_status: str,
        image_bytes: bytes,
        colors_raw: str,
        product_category: str | None,
        engine_mode: GenerationEngineMode,
        post_processing_mode: GenerationPostProcessingMode,
        apply_text_overlays: bool,
        notify_channels: frozenset[VariantNotifyChannel],
        idempotency_key: str | None,
        ai_coins: int,
    ) -> tuple[VariantSyncView, bool]:
        """Upload source photo, persist queued sync, return (sync, created)."""

        _ = subscription_status
        if idempotency_key:
            existing = await self._repository.find_idempotent_sync(
                user_id=user_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                return existing, False

        try:
            mime_type, extension = validate_source_image(
                image_bytes,
                max_bytes=self._max_image_bytes,
            )
            colors = parse_color_specs(colors_raw, max_colors=self._max_colors)
        except ValueError as exc:
            raise SmartVariantValidationError(str(exc)) from exc

        required_coins = self.estimate_coin_cost(len(colors))
        if self._charge_coins and ai_coins < required_coins:
            raise BillingValidationError(
                f"Insufficient AI-coin balance for {len(colors)} color variants "
                f"(need {required_coins})."
            )

        source_key = f"variant-uploads/{user_id}/{uuid4().hex}{extension}"
        await self._storage.upload_bytes(
            object_key=source_key,
            data=image_bytes,
            content_type=mime_type,
            presign=False,
        )

        sync = await self._repository.create_sync(
            user_id=user_id,
            idempotency_key=idempotency_key,
            product_category=product_category,
            engine_mode=engine_mode,
            post_processing_mode=post_processing_mode,
            apply_text_overlays=apply_text_overlays,
            source_image_object_key=source_key,
            source_mime_type=mime_type,
            colors=colors,
            notify_telegram=VariantNotifyChannel.TELEGRAM in notify_channels,
            notify_push=VariantNotifyChannel.PUSH in notify_channels,
        )
        return sync, True

    async def get_sync_for_user(
        self, *, user_id: UUID, sync_id: UUID
    ) -> VariantSyncView:
        sync = await self._repository.get_sync_for_user(
            user_id=user_id,
            sync_id=sync_id,
            include_items=True,
        )
        if sync is None:
            raise SmartVariantNotFoundError("Smart variant sync not found.")
        return sync

    async def recolor_and_enqueue(
        self,
        *,
        sync_id: UUID,
        subscription_status: str,
    ) -> VariantSyncView:
        """Recolor fabric per target color and enqueue generation jobs."""

        sync = await self._repository.get_sync(sync_id=sync_id, include_items=True)
        if sync is None:
            raise SmartVariantNotFoundError("Smart variant sync not found.")
        if sync.status in (
            VariantSyncStatus.RUNNING,
            VariantSyncStatus.COMPLETED,
            VariantSyncStatus.PARTIAL,
            VariantSyncStatus.FAILED,
        ):
            return sync

        await self._repository.mark_sync_status(
            sync_id=sync_id,
            status=VariantSyncStatus.RECOLORING,
        )

        try:
            source_bytes = await self._storage.download_bytes(
                object_key=sync.source_image_object_key,
                max_bytes=self._max_image_bytes,
            )
        except Exception as exc:
            return await self._repository.mark_sync_status(
                sync_id=sync_id,
                status=VariantSyncStatus.FAILED,
                error_message=str(exc)[:2000],
                completed_at=datetime.now(UTC),
            )

        engine_mode = GenerationEngineMode(sync.engine_mode)
        post_mode = GenerationPostProcessingMode(sync.post_processing_mode)
        ext = _extension_from_mime(sync.source_mime_type)

        for item in sync.items:
            if item.generation_job_id is not None:
                continue
            if item.status in (
                VariantItemStatus.COMPLETED,
                VariantItemStatus.FAILED,
                VariantItemStatus.SKIPPED,
            ):
                continue
            color = ColorSpec(name=item.color_name, hex_code=item.color_hex)
            try:
                await self._repository.mark_item_recoloring(item_id=item.id)
                recolored = await self._recolor.recolor_fabric(
                    source_image=source_bytes,
                    color=color,
                    product_category=sync.product_category,
                )
                if not recolored:
                    raise RuntimeError("Recolor engine returned empty image.")
                recolored_key = (
                    f"generation-inputs/{sync.user_id}/"
                    f"variant-{sync_id.hex}-{item.position:02d}-{color.slug}{ext}"
                )
                await self._storage.upload_bytes(
                    object_key=recolored_key,
                    data=recolored,
                    content_type=sync.source_mime_type,
                    presign=False,
                )
                await self._repository.mark_item_recolored(
                    item_id=item.id,
                    recolored_object_key=recolored_key,
                    status=VariantItemStatus.QUEUED,
                )
                overlays = (
                    build_color_overlay_texts(color)
                    if sync.apply_text_overlays
                    else {}
                )
                job_id = await self._job_factory.create_for_variant_item(
                    user_id=sync.user_id,
                    subscription_status=subscription_status,
                    engine_mode=engine_mode,
                    post_processing_mode=post_mode,
                    input_object_key=recolored_key,
                    product_category=sync.product_category,
                    apply_text_overlays=sync.apply_text_overlays,
                    overlay_texts=overlays,
                    idempotency_key=f"variant:{sync_id}:{item.position}",
                )
                await self._repository.mark_item_job(
                    item_id=item.id,
                    generation_job_id=job_id,
                    status=VariantItemStatus.QUEUED,
                )
            except BillingValidationError as exc:
                await self._repository.mark_item_failed(
                    item_id=item.id,
                    error_message=str(exc),
                    status=VariantItemStatus.FAILED,
                )
            except Exception as exc:
                await self._repository.mark_item_failed(
                    item_id=item.id,
                    error_message=str(exc)[:2000],
                    status=VariantItemStatus.FAILED,
                )

        synced = await self._repository.sync_item_statuses_from_jobs(sync_id=sync_id)
        if synced.status in (
            VariantSyncStatus.COMPLETED,
            VariantSyncStatus.PARTIAL,
            VariantSyncStatus.FAILED,
        ):
            return await self._notify_if_needed(synced)

        return await self._repository.mark_sync_status(
            sync_id=sync_id,
            status=VariantSyncStatus.RUNNING,
            total_items=len(sync.items),
        )

    async def poll_sync_completion(self, sync_id: UUID) -> VariantSyncView:
        """Refresh child job statuses and notify when the sync is terminal."""

        sync = await self._repository.get_sync(sync_id=sync_id, include_items=True)
        if sync is None:
            raise SmartVariantNotFoundError("Smart variant sync not found.")
        if sync.status in (
            VariantSyncStatus.COMPLETED,
            VariantSyncStatus.PARTIAL,
            VariantSyncStatus.FAILED,
        ):
            return await self._notify_if_needed(sync)

        synced = await self._repository.sync_item_statuses_from_jobs(sync_id=sync_id)
        return await self._notify_if_needed(synced)

    async def poll_active_syncs(self, *, limit: int = 50) -> dict[str, int]:
        """Beat-friendly sweep over recoloring/running syncs."""

        ids = await self._repository.list_active_sync_ids(limit=limit)
        notified = 0
        terminal = 0
        for sync_id in ids:
            sync = await self.poll_sync_completion(sync_id)
            if sync.status in (
                VariantSyncStatus.COMPLETED,
                VariantSyncStatus.PARTIAL,
                VariantSyncStatus.FAILED,
            ):
                terminal += 1
                if (
                    sync.telegram_notified_at is not None
                    or sync.push_notified_at is not None
                ):
                    notified += 1
        return {
            "scanned": len(ids),
            "terminal": terminal,
            "notified_syncs": notified,
        }

    async def _notify_if_needed(self, sync: VariantSyncView) -> VariantSyncView:
        if sync.status not in (
            VariantSyncStatus.COMPLETED,
            VariantSyncStatus.PARTIAL,
            VariantSyncStatus.FAILED,
        ):
            return sync

        telegram_at = sync.telegram_notified_at
        push_at = sync.push_notified_at
        now = datetime.now(UTC)

        if (
            sync.notify_telegram
            and telegram_at is None
            and self._telegram is not None
        ):
            chat_id = await self._repository.get_telegram_id(sync.user_id)
            if chat_id:
                sent = await self._telegram.send_message(
                    chat_id=chat_id,
                    text=build_sync_ready_telegram_message(sync),
                )
                if sent:
                    telegram_at = now

        if sync.notify_push and push_at is None and self._push is not None:
            sent = await self._push.send(
                user_id=sync.user_id,
                payload=build_sync_ready_push_payload(sync),
            )
            if sent:
                push_at = now

        if (
            telegram_at != sync.telegram_notified_at
            or push_at != sync.push_notified_at
        ):
            return await self._repository.mark_notified(
                sync_id=sync.id,
                telegram_at=telegram_at,
                push_at=push_at,
            )
        return sync


def _extension_from_mime(mime_type: str) -> str:
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }
    return mapping.get(mime_type, ".jpg")
