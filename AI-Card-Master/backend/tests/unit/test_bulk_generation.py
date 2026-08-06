"""Unit tests for Bulk Generation domain and application service."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.application.bulk_generation_service import (
    BulkGenerationNotFoundError,
    BulkGenerationService,
    BulkGenerationValidationError,
)
from app.domain.bulk_generation import (
    BulkBatchStatus,
    BulkBatchView,
    BulkItemStatus,
    BulkItemView,
    BulkNotifyChannel,
    build_batch_ready_telegram_message,
    extract_products_from_zip,
    parse_notify_channels,
    resolve_batch_terminal_status,
)
from app.domain.generation import (
    GenerationEngineMode,
    GenerationJobStatus,
    GenerationPostProcessingMode,
)
from app.services.billing_service import BillingValidationError

# 1x1 transparent PNG
_MIN_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def _zip_bytes(*names: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, _MIN_PNG)
    return buffer.getvalue()


class _FakeTelegram:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, *, chat_id: int, text: str) -> bool:
        self.messages.append((chat_id, text))
        return True


class _FakePush:
    def __init__(self) -> None:
        self.payloads: list[tuple[UUID, str]] = []

    async def send(self, *, user_id: UUID, payload) -> bool:
        self.payloads.append((user_id, payload.title))
        return True


class _FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def upload_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        presign: bool = True,
    ) -> object:
        self.objects[object_key] = data
        return object()

    async def download_bytes(self, *, object_key: str, max_bytes: int) -> bytes:
        data = self.objects[object_key]
        if len(data) > max_bytes:
            raise ValueError("too large")
        return data


class _FakeJobFactory:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.fail_keys: set[str] = set()

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
        if idempotency_key in self.fail_keys:
            raise BillingValidationError("Insufficient AI-coin balance.")
        job_id = uuid4()
        self.created.append(idempotency_key)
        return job_id


class _FakeBulkRepo:
    def __init__(self) -> None:
        self.batches: dict[UUID, BulkBatchView] = {}
        self.items: dict[UUID, list[BulkItemView]] = {}
        self.telegram_ids: dict[UUID, int] = {}
        self.job_statuses: dict[UUID, GenerationJobStatus] = {}
        self.idempotency: dict[tuple[UUID, str], UUID] = {}

    async def find_idempotent_batch(
        self, *, user_id: UUID, idempotency_key: str
    ) -> BulkBatchView | None:
        batch_id = self.idempotency.get((user_id, idempotency_key))
        if batch_id is None:
            return None
        batch = self.batches.get(batch_id)
        return self._with_items(batch) if batch is not None else None

    async def create_batch(
        self,
        *,
        user_id: UUID,
        idempotency_key: str | None,
        product_category: str | None,
        engine_mode: GenerationEngineMode,
        post_processing_mode: GenerationPostProcessingMode,
        apply_text_overlays: bool,
        source_zip_object_key: str,
        notify_telegram: bool,
        notify_push: bool,
    ) -> BulkBatchView:
        now = datetime.now(UTC)
        batch = BulkBatchView(
            id=uuid4(),
            user_id=user_id,
            status=BulkBatchStatus.QUEUED,
            product_category=product_category,
            engine_mode=engine_mode.value,
            post_processing_mode=post_processing_mode.value,
            apply_text_overlays=apply_text_overlays,
            source_zip_object_key=source_zip_object_key,
            total_items=0,
            completed_items=0,
            failed_items=0,
            skipped_items=0,
            notify_telegram=notify_telegram,
            notify_push=notify_push,
            telegram_notified_at=None,
            push_notified_at=None,
            error_message=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
            items=(),
        )
        self.batches[batch.id] = batch
        self.items[batch.id] = []
        if idempotency_key:
            self.idempotency[(user_id, idempotency_key)] = batch.id
        return batch

    async def get_batch_for_user(
        self, *, user_id: UUID, batch_id: UUID, include_items: bool = True
    ) -> BulkBatchView | None:
        batch = self.batches.get(batch_id)
        if batch is None or batch.user_id != user_id:
            return None
        return self._with_items(batch) if include_items else batch

    async def get_batch(
        self, *, batch_id: UUID, include_items: bool = True
    ) -> BulkBatchView | None:
        batch = self.batches.get(batch_id)
        if batch is None:
            return None
        return self._with_items(batch) if include_items else batch

    def _with_items(self, batch: BulkBatchView) -> BulkBatchView:
        items = tuple(self.items.get(batch.id, []))
        return BulkBatchView(
            id=batch.id,
            user_id=batch.user_id,
            status=batch.status,
            product_category=batch.product_category,
            engine_mode=batch.engine_mode,
            post_processing_mode=batch.post_processing_mode,
            apply_text_overlays=batch.apply_text_overlays,
            source_zip_object_key=batch.source_zip_object_key,
            total_items=batch.total_items,
            completed_items=batch.completed_items,
            failed_items=batch.failed_items,
            skipped_items=batch.skipped_items,
            notify_telegram=batch.notify_telegram,
            notify_push=batch.notify_push,
            telegram_notified_at=batch.telegram_notified_at,
            push_notified_at=batch.push_notified_at,
            error_message=batch.error_message,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
            completed_at=batch.completed_at,
            items=items,
        )

    async def mark_batch_status(
        self,
        *,
        batch_id: UUID,
        status: BulkBatchStatus,
        error_message: str | None = None,
        total_items: int | None = None,
        completed_at: datetime | None = None,
    ) -> BulkBatchView:
        batch = self.batches[batch_id]
        updated = BulkBatchView(
            id=batch.id,
            user_id=batch.user_id,
            status=status,
            product_category=batch.product_category,
            engine_mode=batch.engine_mode,
            post_processing_mode=batch.post_processing_mode,
            apply_text_overlays=batch.apply_text_overlays,
            source_zip_object_key=batch.source_zip_object_key,
            total_items=total_items if total_items is not None else batch.total_items,
            completed_items=batch.completed_items,
            failed_items=batch.failed_items,
            skipped_items=batch.skipped_items,
            notify_telegram=batch.notify_telegram,
            notify_push=batch.notify_push,
            telegram_notified_at=batch.telegram_notified_at,
            push_notified_at=batch.push_notified_at,
            error_message=error_message if error_message is not None else batch.error_message,
            created_at=batch.created_at,
            updated_at=datetime.now(UTC),
            completed_at=completed_at if completed_at is not None else batch.completed_at,
            items=(),
        )
        self.batches[batch_id] = updated
        return self._with_items(updated)

    async def replace_pending_items(
        self,
        *,
        batch_id: UUID,
        items: tuple[tuple[int, str, str], ...],
    ) -> tuple[BulkItemView, ...]:
        now = datetime.now(UTC)
        created: list[BulkItemView] = []
        for position, product_key, source_path in items:
            item = BulkItemView(
                id=uuid4(),
                batch_id=batch_id,
                position=position,
                product_key=product_key,
                source_path=source_path,
                status=BulkItemStatus.PENDING,
                input_object_key=None,
                generation_job_id=None,
                error_message=None,
                created_at=now,
                updated_at=now,
            )
            created.append(item)
        self.items[batch_id] = created
        batch = self.batches[batch_id]
        self.batches[batch_id] = BulkBatchView(
            id=batch.id,
            user_id=batch.user_id,
            status=batch.status,
            product_category=batch.product_category,
            engine_mode=batch.engine_mode,
            post_processing_mode=batch.post_processing_mode,
            apply_text_overlays=batch.apply_text_overlays,
            source_zip_object_key=batch.source_zip_object_key,
            total_items=len(items),
            completed_items=0,
            failed_items=0,
            skipped_items=0,
            notify_telegram=batch.notify_telegram,
            notify_push=batch.notify_push,
            telegram_notified_at=batch.telegram_notified_at,
            push_notified_at=batch.push_notified_at,
            error_message=batch.error_message,
            created_at=batch.created_at,
            updated_at=now,
            completed_at=batch.completed_at,
            items=(),
        )
        return tuple(created)

    async def mark_item_input(
        self,
        *,
        item_id: UUID,
        input_object_key: str,
        status: BulkItemStatus = BulkItemStatus.QUEUED,
    ) -> BulkItemView:
        return self._update_item(
            item_id,
            input_object_key=input_object_key,
            status=status,
        )

    async def mark_item_job(
        self,
        *,
        item_id: UUID,
        generation_job_id: UUID,
        status: BulkItemStatus = BulkItemStatus.QUEUED,
    ) -> BulkItemView:
        self.job_statuses[generation_job_id] = GenerationJobStatus.QUEUED
        return self._update_item(
            item_id,
            generation_job_id=generation_job_id,
            status=status,
        )

    async def mark_item_failed(
        self,
        *,
        item_id: UUID,
        error_message: str,
        status: BulkItemStatus = BulkItemStatus.FAILED,
    ) -> BulkItemView:
        return self._update_item(
            item_id,
            error_message=error_message,
            status=status,
        )

    def _update_item(self, item_id: UUID, **kwargs) -> BulkItemView:
        for batch_id, items in self.items.items():
            for index, item in enumerate(items):
                if item.id != item_id:
                    continue
                updated = BulkItemView(
                    id=item.id,
                    batch_id=item.batch_id,
                    position=item.position,
                    product_key=item.product_key,
                    source_path=item.source_path,
                    status=kwargs.get("status", item.status),
                    input_object_key=kwargs.get(
                        "input_object_key", item.input_object_key
                    ),
                    generation_job_id=kwargs.get(
                        "generation_job_id", item.generation_job_id
                    ),
                    error_message=kwargs.get("error_message", item.error_message),
                    created_at=item.created_at,
                    updated_at=datetime.now(UTC),
                )
                items[index] = updated
                return updated
        raise LookupError(item_id)

    async def list_active_batch_ids(self, *, limit: int) -> tuple[UUID, ...]:
        active = [
            batch.id
            for batch in self.batches.values()
            if batch.status
            in (
                BulkBatchStatus.QUEUED,
                BulkBatchStatus.UNPACKING,
                BulkBatchStatus.RUNNING,
            )
        ]
        return tuple(active[:limit])

    async def sync_item_statuses_from_jobs(self, *, batch_id: UUID) -> BulkBatchView:
        items = self.items[batch_id]
        completed = failed = skipped = 0
        updated_items: list[BulkItemView] = []
        for item in items:
            if item.status is BulkItemStatus.SKIPPED:
                skipped += 1
                updated_items.append(item)
                continue
            if item.generation_job_id is None:
                if item.status is BulkItemStatus.FAILED:
                    failed += 1
                updated_items.append(item)
                continue
            job_status = self.job_statuses.get(
                item.generation_job_id, GenerationJobStatus.QUEUED
            )
            if job_status is GenerationJobStatus.COMPLETED:
                status = BulkItemStatus.COMPLETED
                completed += 1
            elif job_status is GenerationJobStatus.FAILED:
                status = BulkItemStatus.FAILED
                failed += 1
            else:
                status = BulkItemStatus.RUNNING
            updated_items.append(
                BulkItemView(
                    id=item.id,
                    batch_id=item.batch_id,
                    position=item.position,
                    product_key=item.product_key,
                    source_path=item.source_path,
                    status=status,
                    input_object_key=item.input_object_key,
                    generation_job_id=item.generation_job_id,
                    error_message=item.error_message,
                    created_at=item.created_at,
                    updated_at=datetime.now(UTC),
                )
            )
        self.items[batch_id] = updated_items
        batch = self.batches[batch_id]
        terminal = resolve_batch_terminal_status(
            total_items=len(updated_items),
            completed_items=completed,
            failed_items=failed,
            skipped_items=skipped,
        )
        status = terminal if terminal is not None else BulkBatchStatus.RUNNING
        updated = BulkBatchView(
            id=batch.id,
            user_id=batch.user_id,
            status=status,
            product_category=batch.product_category,
            engine_mode=batch.engine_mode,
            post_processing_mode=batch.post_processing_mode,
            apply_text_overlays=batch.apply_text_overlays,
            source_zip_object_key=batch.source_zip_object_key,
            total_items=len(updated_items),
            completed_items=completed,
            failed_items=failed,
            skipped_items=skipped,
            notify_telegram=batch.notify_telegram,
            notify_push=batch.notify_push,
            telegram_notified_at=batch.telegram_notified_at,
            push_notified_at=batch.push_notified_at,
            error_message=batch.error_message,
            created_at=batch.created_at,
            updated_at=datetime.now(UTC),
            completed_at=datetime.now(UTC) if terminal else None,
            items=(),
        )
        self.batches[batch_id] = updated
        return self._with_items(updated)

    async def mark_notified(
        self,
        *,
        batch_id: UUID,
        telegram_at: datetime | None = None,
        push_at: datetime | None = None,
    ) -> BulkBatchView:
        batch = self.batches[batch_id]
        updated = BulkBatchView(
            id=batch.id,
            user_id=batch.user_id,
            status=batch.status,
            product_category=batch.product_category,
            engine_mode=batch.engine_mode,
            post_processing_mode=batch.post_processing_mode,
            apply_text_overlays=batch.apply_text_overlays,
            source_zip_object_key=batch.source_zip_object_key,
            total_items=batch.total_items,
            completed_items=batch.completed_items,
            failed_items=batch.failed_items,
            skipped_items=batch.skipped_items,
            notify_telegram=batch.notify_telegram,
            notify_push=batch.notify_push,
            telegram_notified_at=telegram_at
            if telegram_at is not None
            else batch.telegram_notified_at,
            push_notified_at=push_at if push_at is not None else batch.push_notified_at,
            error_message=batch.error_message,
            created_at=batch.created_at,
            updated_at=datetime.now(UTC),
            completed_at=batch.completed_at,
            items=(),
        )
        self.batches[batch_id] = updated
        return self._with_items(updated)

    async def get_telegram_id(self, user_id: UUID) -> int | None:
        return self.telegram_ids.get(user_id)

    async def get_job_status(self, job_id: UUID) -> GenerationJobStatus | None:
        return self.job_statuses.get(job_id)


def _service(
    repo: _FakeBulkRepo | None = None,
    storage: _FakeStorage | None = None,
    jobs: _FakeJobFactory | None = None,
    telegram: _FakeTelegram | None = None,
    push: _FakePush | None = None,
    *,
    charge_coins: bool = True,
) -> tuple[BulkGenerationService, _FakeBulkRepo, _FakeStorage, _FakeJobFactory, _FakeTelegram, _FakePush]:
    repo = repo or _FakeBulkRepo()
    storage = storage or _FakeStorage()
    jobs = jobs or _FakeJobFactory()
    telegram = telegram or _FakeTelegram()
    push = push or _FakePush()
    service = BulkGenerationService(
        repo,
        storage=storage,
        job_factory=jobs,
        max_products=20,
        max_zip_bytes=10 * 1024 * 1024,
        max_image_bytes=1024 * 1024,
        coins_per_product=1,
        charge_coins=charge_coins,
        telegram=telegram,
        push=push,
    )
    return service, repo, storage, jobs, telegram, push


def test_extract_products_from_flat_and_folder_zip() -> None:
    payload = _zip_bytes("sku-a.png", "folder-b/main.png", "__MACOSX/._junk.png")
    products = extract_products_from_zip(
        payload, max_products=20, max_image_bytes=1024 * 1024
    )
    keys = {product.product_key for product in products}
    assert keys == {"sku-a", "folder-b"}


def test_resolve_batch_terminal_status() -> None:
    assert (
        resolve_batch_terminal_status(
            total_items=3, completed_items=3, failed_items=0, skipped_items=0
        )
        is BulkBatchStatus.COMPLETED
    )
    assert (
        resolve_batch_terminal_status(
            total_items=3, completed_items=2, failed_items=1, skipped_items=0
        )
        is BulkBatchStatus.PARTIAL
    )
    assert (
        resolve_batch_terminal_status(
            total_items=2, completed_items=0, failed_items=2, skipped_items=0
        )
        is BulkBatchStatus.FAILED
    )
    assert (
        resolve_batch_terminal_status(
            total_items=2, completed_items=1, failed_items=0, skipped_items=0
        )
        is None
    )


def test_parse_notify_channels_default_and_custom() -> None:
    assert parse_notify_channels(None) == frozenset(
        {BulkNotifyChannel.TELEGRAM, BulkNotifyChannel.PUSH}
    )
    assert parse_notify_channels("telegram") == frozenset({BulkNotifyChannel.TELEGRAM})
    with pytest.raises(ValueError):
        parse_notify_channels("sms")


@pytest.mark.asyncio
async def test_create_batch_rejects_insufficient_coins() -> None:
    service, *_ = _service()
    with pytest.raises(BillingValidationError):
        await service.create_batch_from_zip(
            user_id=uuid4(),
            subscription_status="pro",
            zip_bytes=_zip_bytes("a.png", "b.png"),
            product_category="perfume",
            engine_mode=GenerationEngineMode.STANDARD,
            post_processing_mode=GenerationPostProcessingMode.FAST,
            apply_text_overlays=False,
            notify_channels=frozenset({BulkNotifyChannel.TELEGRAM}),
            idempotency_key=None,
            ai_coins=1,
        )


@pytest.mark.asyncio
async def test_unpack_enqueues_jobs_and_notifies_on_completion() -> None:
    service, repo, storage, jobs, telegram, push = _service()
    user_id = uuid4()
    repo.telegram_ids[user_id] = 4242

    batch, created, count = await service.create_batch_from_zip(
        user_id=user_id,
        subscription_status="pro",
        zip_bytes=_zip_bytes("one.png", "two.png"),
        product_category="electronics",
        engine_mode=GenerationEngineMode.STANDARD,
        post_processing_mode=GenerationPostProcessingMode.FAST,
        apply_text_overlays=False,
        notify_channels=frozenset(
            {BulkNotifyChannel.TELEGRAM, BulkNotifyChannel.PUSH}
        ),
        idempotency_key="bulk-test-key-1",
        ai_coins=10,
    )
    assert created is True
    assert count == 2
    assert batch.source_zip_object_key in storage.objects

    running = await service.unpack_and_enqueue(
        batch_id=batch.id,
        subscription_status="pro",
    )
    assert running.status is BulkBatchStatus.RUNNING
    assert len(jobs.created) == 2
    assert running.total_items == 2

    # Simulate both child jobs completing.
    for item in repo.items[batch.id]:
        assert item.generation_job_id is not None
        repo.job_statuses[item.generation_job_id] = GenerationJobStatus.COMPLETED

    finished = await service.poll_batch_completion(batch.id)
    assert finished.status is BulkBatchStatus.COMPLETED
    assert finished.completed_items == 2
    assert telegram.messages
    assert "Массовая генерация" in telegram.messages[0][1]
    assert push.payloads
    assert finished.telegram_notified_at is not None
    assert finished.push_notified_at is not None


@pytest.mark.asyncio
async def test_get_batch_not_found() -> None:
    service, *_ = _service()
    with pytest.raises(BulkGenerationNotFoundError):
        await service.get_batch_for_user(user_id=uuid4(), batch_id=uuid4())


@pytest.mark.asyncio
async def test_empty_zip_validation() -> None:
    service, *_ = _service()
    with pytest.raises(BulkGenerationValidationError):
        await service.create_batch_from_zip(
            user_id=uuid4(),
            subscription_status="free",
            zip_bytes=b"",
            product_category=None,
            engine_mode=GenerationEngineMode.STANDARD,
            post_processing_mode=GenerationPostProcessingMode.FAST,
            apply_text_overlays=False,
            notify_channels=frozenset({BulkNotifyChannel.PUSH}),
            idempotency_key=None,
            ai_coins=100,
        )


def test_telegram_copy_mentions_preset() -> None:
    now = datetime.now(UTC)
    batch = BulkBatchView(
        id=uuid4(),
        user_id=uuid4(),
        status=BulkBatchStatus.COMPLETED,
        product_category="Luxury Loft",
        engine_mode="standard",
        post_processing_mode="fast",
        apply_text_overlays=False,
        source_zip_object_key="bulk-uploads/x.zip",
        total_items=12,
        completed_items=12,
        failed_items=0,
        skipped_items=0,
        notify_telegram=True,
        notify_push=True,
        telegram_notified_at=None,
        push_notified_at=None,
        error_message=None,
        created_at=now,
        updated_at=now,
        completed_at=now,
    )
    message = build_batch_ready_telegram_message(batch)
    assert "Luxury Loft" in message
    assert "12/12" in message
