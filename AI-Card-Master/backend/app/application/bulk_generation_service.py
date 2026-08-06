"""Application use cases for Bulk Generation (ZIP → N jobs → notify)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.application.ports.bulk_generation import (
    BulkGenerationPersistencePort,
    PushNotifierPort,
)
from app.domain.bulk_generation import (
    BulkBatchStatus,
    BulkBatchView,
    BulkItemStatus,
    BulkNotifyChannel,
    build_batch_ready_push_payload,
    build_batch_ready_telegram_message,
    extract_products_from_zip,
)
from app.domain.generation import (
    GenerationEngineMode,
    GenerationPostProcessingMode,
)
from app.services.billing_service import BillingValidationError


class TelegramUserNotifierPort(Protocol):
    """Duck-typed Telegram sender for batch-ready messages."""

    async def send_message(self, *, chat_id: int, text: str) -> bool:
        """Return True when Telegram accepted the message."""

        raise NotImplementedError


class ObjectStoragePort(Protocol):
    """Minimal S3 port used by bulk unpack / create flows."""

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
    """Creates a durable single-product generation job for one bulk item."""

    async def create_for_bulk_item(
        self,
        *,
        user_id: UUID,
        subscription_status: str,
        engine_mode: GenerationEngineMode,
        post_processing_mode: GenerationPostProcessingMode,
        input_object_key: str,
        product_category: str | None,
        apply_text_overlays: bool,
        idempotency_key: str,
    ) -> UUID:
        """Return the created (or idempotently replayed) generation job id."""


class BulkGenerationError(Exception):
    """Base bulk generation workflow failure."""


class BulkGenerationValidationError(BulkGenerationError):
    """Request or archive contents are invalid."""


class BulkGenerationNotFoundError(BulkGenerationError):
    """Batch was not found for the user."""


class BulkGenerationService:
    """Coordinate ZIP upload, background unpack, child jobs, and notifications."""

    def __init__(
        self,
        repository: BulkGenerationPersistencePort,
        *,
        storage: ObjectStoragePort,
        job_factory: GenerationJobFactoryPort,
        max_products: int,
        max_zip_bytes: int,
        max_image_bytes: int,
        coins_per_product: int,
        charge_coins: bool,
        telegram: TelegramUserNotifierPort | None = None,
        push: PushNotifierPort | None = None,
    ) -> None:
        if max_products <= 0:
            raise BulkGenerationValidationError("max_products must be positive.")
        if max_zip_bytes <= 0 or max_image_bytes <= 0:
            raise BulkGenerationValidationError("size limits must be positive.")
        if coins_per_product <= 0:
            raise BulkGenerationValidationError("coins_per_product must be positive.")
        self._repository = repository
        self._storage = storage
        self._job_factory = job_factory
        self._max_products = max_products
        self._max_zip_bytes = max_zip_bytes
        self._max_image_bytes = max_image_bytes
        self._coins_per_product = coins_per_product
        self._charge_coins = charge_coins
        self._telegram = telegram
        self._push = push

    @property
    def max_products(self) -> int:
        return self._max_products

    @property
    def max_zip_bytes(self) -> int:
        return self._max_zip_bytes

    def estimate_coin_cost(self, product_count: int) -> int:
        """Coins required to enqueue ``product_count`` child jobs."""

        if not self._charge_coins:
            return 0
        return max(0, product_count) * self._coins_per_product

    async def create_batch_from_zip(
        self,
        *,
        user_id: UUID,
        subscription_status: str,
        zip_bytes: bytes,
        product_category: str | None,
        engine_mode: GenerationEngineMode,
        post_processing_mode: GenerationPostProcessingMode,
        apply_text_overlays: bool,
        notify_channels: frozenset[BulkNotifyChannel],
        idempotency_key: str | None,
        ai_coins: int,
    ) -> tuple[BulkBatchView, bool, int]:
        """Upload ZIP, persist queued batch, return (batch, created, product_count)."""

        _ = subscription_status  # validated by API; used when enqueueing jobs
        if idempotency_key:
            existing = await self._repository.find_idempotent_batch(
                user_id=user_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                return existing, False, existing.total_items

        if len(zip_bytes) == 0:
            raise BulkGenerationValidationError("Uploaded ZIP is empty.")
        if len(zip_bytes) > self._max_zip_bytes:
            raise BulkGenerationValidationError(
                f"ZIP exceeds the {self._max_zip_bytes}-byte upload limit."
            )

        try:
            products = extract_products_from_zip(
                zip_bytes,
                max_products=self._max_products,
                max_image_bytes=self._max_image_bytes,
            )
        except ValueError as exc:
            raise BulkGenerationValidationError(str(exc)) from exc

        product_count = len(products)
        required_coins = self.estimate_coin_cost(product_count)
        if self._charge_coins and ai_coins < required_coins:
            raise BillingValidationError(
                f"Insufficient AI-coin balance for {product_count} products "
                f"(need {required_coins})."
            )

        zip_key = f"bulk-uploads/{user_id}/{uuid4().hex}.zip"
        await self._storage.upload_bytes(
            object_key=zip_key,
            data=zip_bytes,
            content_type="application/zip",
            presign=False,
        )

        batch = await self._repository.create_batch(
            user_id=user_id,
            idempotency_key=idempotency_key,
            product_category=product_category,
            engine_mode=engine_mode,
            post_processing_mode=post_processing_mode,
            apply_text_overlays=apply_text_overlays,
            source_zip_object_key=zip_key,
            notify_telegram=BulkNotifyChannel.TELEGRAM in notify_channels,
            notify_push=BulkNotifyChannel.PUSH in notify_channels,
        )
        return batch, True, product_count

    async def get_batch_for_user(
        self, *, user_id: UUID, batch_id: UUID
    ) -> BulkBatchView:
        batch = await self._repository.get_batch_for_user(
            user_id=user_id,
            batch_id=batch_id,
            include_items=True,
        )
        if batch is None:
            raise BulkGenerationNotFoundError("Bulk generation batch not found.")
        return batch

    async def unpack_and_enqueue(
        self,
        *,
        batch_id: UUID,
        subscription_status: str,
    ) -> BulkBatchView:
        """Download ZIP, create child generation jobs, mark batch running."""

        batch = await self._repository.get_batch(batch_id=batch_id, include_items=True)
        if batch is None:
            raise BulkGenerationNotFoundError("Bulk generation batch not found.")
        if batch.status in (
            BulkBatchStatus.RUNNING,
            BulkBatchStatus.COMPLETED,
            BulkBatchStatus.PARTIAL,
            BulkBatchStatus.FAILED,
        ):
            return batch

        await self._repository.mark_batch_status(
            batch_id=batch_id,
            status=BulkBatchStatus.UNPACKING,
        )

        try:
            zip_bytes = await self._storage.download_bytes(
                object_key=batch.source_zip_object_key,
                max_bytes=self._max_zip_bytes,
            )
            products = extract_products_from_zip(
                zip_bytes,
                max_products=self._max_products,
                max_image_bytes=self._max_image_bytes,
            )
        except Exception as exc:
            return await self._repository.mark_batch_status(
                batch_id=batch_id,
                status=BulkBatchStatus.FAILED,
                error_message=str(exc)[:2000],
                completed_at=datetime.now(UTC),
            )

        item_specs = tuple(
            (index, product.product_key, product.source_path)
            for index, product in enumerate(products, start=1)
        )
        items = await self._repository.replace_pending_items(
            batch_id=batch_id,
            items=item_specs,
        )

        engine_mode = GenerationEngineMode(batch.engine_mode)
        post_mode = GenerationPostProcessingMode(batch.post_processing_mode)

        for item, product in zip(items, products, strict=True):
            input_key = (
                f"generation-inputs/{batch.user_id}/"
                f"bulk-{batch_id.hex}-{item.position:02d}{product.extension}"
            )
            try:
                await self._storage.upload_bytes(
                    object_key=input_key,
                    data=product.data,
                    content_type=product.mime_type,
                    presign=False,
                )
                await self._repository.mark_item_input(
                    item_id=item.id,
                    input_object_key=input_key,
                    status=BulkItemStatus.QUEUED,
                )
                job_id = await self._job_factory.create_for_bulk_item(
                    user_id=batch.user_id,
                    subscription_status=subscription_status,
                    engine_mode=engine_mode,
                    post_processing_mode=post_mode,
                    input_object_key=input_key,
                    product_category=batch.product_category,
                    apply_text_overlays=batch.apply_text_overlays,
                    idempotency_key=f"bulk:{batch_id}:{item.position}",
                )
                await self._repository.mark_item_job(
                    item_id=item.id,
                    generation_job_id=job_id,
                    status=BulkItemStatus.QUEUED,
                )
            except BillingValidationError as exc:
                await self._repository.mark_item_failed(
                    item_id=item.id,
                    error_message=str(exc),
                    status=BulkItemStatus.FAILED,
                )
            except Exception as exc:
                await self._repository.mark_item_failed(
                    item_id=item.id,
                    error_message=str(exc)[:2000],
                    status=BulkItemStatus.FAILED,
                )

        synced = await self._repository.sync_item_statuses_from_jobs(batch_id=batch_id)
        if synced.status in (
            BulkBatchStatus.COMPLETED,
            BulkBatchStatus.PARTIAL,
            BulkBatchStatus.FAILED,
        ):
            return await self._notify_if_needed(synced)

        return await self._repository.mark_batch_status(
            batch_id=batch_id,
            status=BulkBatchStatus.RUNNING,
            total_items=len(products),
        )

    async def poll_batch_completion(self, batch_id: UUID) -> BulkBatchView:
        """Refresh child job statuses and notify when the batch is terminal."""

        batch = await self._repository.get_batch(batch_id=batch_id, include_items=True)
        if batch is None:
            raise BulkGenerationNotFoundError("Bulk generation batch not found.")
        if batch.status in (
            BulkBatchStatus.COMPLETED,
            BulkBatchStatus.PARTIAL,
            BulkBatchStatus.FAILED,
        ):
            return await self._notify_if_needed(batch)

        synced = await self._repository.sync_item_statuses_from_jobs(batch_id=batch_id)
        return await self._notify_if_needed(synced)

    async def poll_active_batches(self, *, limit: int = 50) -> dict[str, int]:
        """Beat-friendly sweep over unpacking/running batches."""

        ids = await self._repository.list_active_batch_ids(limit=limit)
        notified = 0
        terminal = 0
        for batch_id in ids:
            batch = await self.poll_batch_completion(batch_id)
            if batch.status in (
                BulkBatchStatus.COMPLETED,
                BulkBatchStatus.PARTIAL,
                BulkBatchStatus.FAILED,
            ):
                terminal += 1
                if batch.telegram_notified_at is not None or batch.push_notified_at is not None:
                    notified += 1
        return {
            "scanned": len(ids),
            "terminal": terminal,
            "notified_batches": notified,
        }

    async def _notify_if_needed(self, batch: BulkBatchView) -> BulkBatchView:
        if batch.status not in (
            BulkBatchStatus.COMPLETED,
            BulkBatchStatus.PARTIAL,
            BulkBatchStatus.FAILED,
        ):
            return batch

        telegram_at = batch.telegram_notified_at
        push_at = batch.push_notified_at
        now = datetime.now(UTC)

        if (
            batch.notify_telegram
            and telegram_at is None
            and self._telegram is not None
        ):
            chat_id = await self._repository.get_telegram_id(batch.user_id)
            if chat_id:
                sent = await self._telegram.send_message(
                    chat_id=chat_id,
                    text=build_batch_ready_telegram_message(batch),
                )
                if sent:
                    telegram_at = now

        if batch.notify_push and push_at is None and self._push is not None:
            sent = await self._push.send(
                user_id=batch.user_id,
                payload=build_batch_ready_push_payload(batch),
            )
            if sent:
                push_at = now

        if telegram_at != batch.telegram_notified_at or push_at != batch.push_notified_at:
            return await self._repository.mark_notified(
                batch_id=batch.id,
                telegram_at=telegram_at,
                push_at=push_at,
            )
        return batch
