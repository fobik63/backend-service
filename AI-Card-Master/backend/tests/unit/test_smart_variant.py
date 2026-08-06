"""Unit tests for Smart Variant Sync domain and application service."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.application.smart_variant_service import (
    SmartVariantNotFoundError,
    SmartVariantService,
    SmartVariantValidationError,
)
from app.domain.generation import (
    GenerationEngineMode,
    GenerationJobStatus,
    GenerationPostProcessingMode,
)
from app.domain.smart_variant import (
    ColorSpec,
    VariantItemStatus,
    VariantItemView,
    VariantNotifyChannel,
    VariantSyncStatus,
    VariantSyncView,
    build_color_overlay_texts,
    build_recolor_prompt,
    build_sync_ready_telegram_message,
    parse_color_specs,
    parse_notify_channels,
    resolve_sync_terminal_status,
    validate_source_image,
)
from app.services.billing_service import BillingValidationError

_MIN_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


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


class _FakeRecolor:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_colors: set[str] = set()

    async def recolor_fabric(
        self,
        *,
        source_image: bytes,
        color: ColorSpec,
        product_category: str | None,
    ) -> bytes:
        self.calls.append(color.slug)
        if color.slug in self.fail_colors:
            raise RuntimeError("recolor failed")
        return b"recolored-" + source_image


class _FakeJobFactory:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.overlays: list[dict[str, str]] = []
        self.fail_keys: set[str] = set()

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
        if idempotency_key in self.fail_keys:
            raise BillingValidationError("Insufficient AI-coin balance.")
        self.created.append(idempotency_key)
        self.overlays.append(overlay_texts)
        return uuid4()


class _FakeRepo:
    def __init__(self) -> None:
        self.syncs: dict[UUID, VariantSyncView] = {}
        self.items: dict[UUID, list[VariantItemView]] = {}
        self.telegram_ids: dict[UUID, int] = {}
        self.job_statuses: dict[UUID, GenerationJobStatus] = {}
        self.idempotency: dict[tuple[UUID, str], UUID] = {}

    def _with_items(self, sync: VariantSyncView) -> VariantSyncView:
        items = tuple(self.items.get(sync.id, []))
        return VariantSyncView(
            id=sync.id,
            user_id=sync.user_id,
            status=sync.status,
            product_category=sync.product_category,
            engine_mode=sync.engine_mode,
            post_processing_mode=sync.post_processing_mode,
            apply_text_overlays=sync.apply_text_overlays,
            source_image_object_key=sync.source_image_object_key,
            source_mime_type=sync.source_mime_type,
            total_items=sync.total_items,
            completed_items=sync.completed_items,
            failed_items=sync.failed_items,
            skipped_items=sync.skipped_items,
            notify_telegram=sync.notify_telegram,
            notify_push=sync.notify_push,
            telegram_notified_at=sync.telegram_notified_at,
            push_notified_at=sync.push_notified_at,
            error_message=sync.error_message,
            created_at=sync.created_at,
            updated_at=sync.updated_at,
            completed_at=sync.completed_at,
            items=items,
        )

    def _store(self, sync: VariantSyncView) -> VariantSyncView:
        self.syncs[sync.id] = sync
        return self._with_items(sync)

    async def find_idempotent_sync(
        self, *, user_id: UUID, idempotency_key: str
    ) -> VariantSyncView | None:
        sync_id = self.idempotency.get((user_id, idempotency_key))
        if sync_id is None:
            return None
        sync = self.syncs.get(sync_id)
        return self._with_items(sync) if sync is not None else None

    async def create_sync(
        self,
        *,
        user_id: UUID,
        idempotency_key: str | None,
        product_category: str | None,
        engine_mode: GenerationEngineMode,
        post_processing_mode: GenerationPostProcessingMode,
        apply_text_overlays: bool,
        source_image_object_key: str,
        source_mime_type: str,
        colors: tuple[ColorSpec, ...],
        notify_telegram: bool,
        notify_push: bool,
    ) -> VariantSyncView:
        now = datetime.now(UTC)
        sync_id = uuid4()
        items = [
            VariantItemView(
                id=uuid4(),
                sync_id=sync_id,
                position=index,
                color_name=color.name,
                color_hex=color.normalize_hex(),
                color_slug=color.slug,
                status=VariantItemStatus.PENDING,
                recolored_object_key=None,
                generation_job_id=None,
                error_message=None,
                created_at=now,
                updated_at=now,
            )
            for index, color in enumerate(colors, start=1)
        ]
        sync = VariantSyncView(
            id=sync_id,
            user_id=user_id,
            status=VariantSyncStatus.QUEUED,
            product_category=product_category,
            engine_mode=engine_mode.value,
            post_processing_mode=post_processing_mode.value,
            apply_text_overlays=apply_text_overlays,
            source_image_object_key=source_image_object_key,
            source_mime_type=source_mime_type,
            total_items=len(colors),
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
        self.syncs[sync.id] = sync
        self.items[sync.id] = items
        if idempotency_key:
            self.idempotency[(user_id, idempotency_key)] = sync.id
        return self._with_items(sync)

    async def get_sync_for_user(
        self, *, user_id: UUID, sync_id: UUID, include_items: bool = True
    ) -> VariantSyncView | None:
        sync = self.syncs.get(sync_id)
        if sync is None or sync.user_id != user_id:
            return None
        return self._with_items(sync) if include_items else sync

    async def get_sync(
        self, *, sync_id: UUID, include_items: bool = True
    ) -> VariantSyncView | None:
        sync = self.syncs.get(sync_id)
        if sync is None:
            return None
        return self._with_items(sync) if include_items else sync

    async def mark_sync_status(
        self,
        *,
        sync_id: UUID,
        status: VariantSyncStatus,
        error_message: str | None = None,
        total_items: int | None = None,
        completed_at: datetime | None = None,
    ) -> VariantSyncView:
        sync = self.syncs[sync_id]
        updated = VariantSyncView(
            id=sync.id,
            user_id=sync.user_id,
            status=status,
            product_category=sync.product_category,
            engine_mode=sync.engine_mode,
            post_processing_mode=sync.post_processing_mode,
            apply_text_overlays=sync.apply_text_overlays,
            source_image_object_key=sync.source_image_object_key,
            source_mime_type=sync.source_mime_type,
            total_items=total_items if total_items is not None else sync.total_items,
            completed_items=sync.completed_items,
            failed_items=sync.failed_items,
            skipped_items=sync.skipped_items,
            notify_telegram=sync.notify_telegram,
            notify_push=sync.notify_push,
            telegram_notified_at=sync.telegram_notified_at,
            push_notified_at=sync.push_notified_at,
            error_message=error_message if error_message is not None else sync.error_message,
            created_at=sync.created_at,
            updated_at=datetime.now(UTC),
            completed_at=completed_at if completed_at is not None else sync.completed_at,
            items=(),
        )
        return self._store(updated)

    def _replace_item(self, item: VariantItemView) -> VariantItemView:
        rows = self.items[item.sync_id]
        self.items[item.sync_id] = [
            item if row.id == item.id else row for row in rows
        ]
        return item

    async def mark_item_recoloring(self, *, item_id: UUID) -> VariantItemView:
        for rows in self.items.values():
            for row in rows:
                if row.id == item_id:
                    updated = VariantItemView(
                        id=row.id,
                        sync_id=row.sync_id,
                        position=row.position,
                        color_name=row.color_name,
                        color_hex=row.color_hex,
                        color_slug=row.color_slug,
                        status=VariantItemStatus.RECOLORING,
                        recolored_object_key=row.recolored_object_key,
                        generation_job_id=row.generation_job_id,
                        error_message=row.error_message,
                        created_at=row.created_at,
                        updated_at=datetime.now(UTC),
                    )
                    return self._replace_item(updated)
        raise LookupError(item_id)

    async def mark_item_recolored(
        self,
        *,
        item_id: UUID,
        recolored_object_key: str,
        status: VariantItemStatus = VariantItemStatus.QUEUED,
    ) -> VariantItemView:
        for rows in self.items.values():
            for row in rows:
                if row.id == item_id:
                    updated = VariantItemView(
                        id=row.id,
                        sync_id=row.sync_id,
                        position=row.position,
                        color_name=row.color_name,
                        color_hex=row.color_hex,
                        color_slug=row.color_slug,
                        status=status,
                        recolored_object_key=recolored_object_key,
                        generation_job_id=row.generation_job_id,
                        error_message=row.error_message,
                        created_at=row.created_at,
                        updated_at=datetime.now(UTC),
                    )
                    return self._replace_item(updated)
        raise LookupError(item_id)

    async def mark_item_job(
        self,
        *,
        item_id: UUID,
        generation_job_id: UUID,
        status: VariantItemStatus = VariantItemStatus.QUEUED,
    ) -> VariantItemView:
        for rows in self.items.values():
            for row in rows:
                if row.id == item_id:
                    updated = VariantItemView(
                        id=row.id,
                        sync_id=row.sync_id,
                        position=row.position,
                        color_name=row.color_name,
                        color_hex=row.color_hex,
                        color_slug=row.color_slug,
                        status=status,
                        recolored_object_key=row.recolored_object_key,
                        generation_job_id=generation_job_id,
                        error_message=row.error_message,
                        created_at=row.created_at,
                        updated_at=datetime.now(UTC),
                    )
                    self.job_statuses[generation_job_id] = GenerationJobStatus.QUEUED
                    return self._replace_item(updated)
        raise LookupError(item_id)

    async def mark_item_failed(
        self,
        *,
        item_id: UUID,
        error_message: str,
        status: VariantItemStatus = VariantItemStatus.FAILED,
    ) -> VariantItemView:
        for rows in self.items.values():
            for row in rows:
                if row.id == item_id:
                    updated = VariantItemView(
                        id=row.id,
                        sync_id=row.sync_id,
                        position=row.position,
                        color_name=row.color_name,
                        color_hex=row.color_hex,
                        color_slug=row.color_slug,
                        status=status,
                        recolored_object_key=row.recolored_object_key,
                        generation_job_id=row.generation_job_id,
                        error_message=error_message,
                        created_at=row.created_at,
                        updated_at=datetime.now(UTC),
                    )
                    return self._replace_item(updated)
        raise LookupError(item_id)

    async def list_active_sync_ids(self, *, limit: int) -> tuple[UUID, ...]:
        active = [
            sync.id
            for sync in self.syncs.values()
            if sync.status
            in (
                VariantSyncStatus.QUEUED,
                VariantSyncStatus.RECOLORING,
                VariantSyncStatus.RUNNING,
            )
        ]
        return tuple(active[:limit])

    async def sync_item_statuses_from_jobs(self, *, sync_id: UUID) -> VariantSyncView:
        sync = self.syncs[sync_id]
        items = self.items[sync_id]
        completed = 0
        failed = 0
        skipped = 0
        updated_items: list[VariantItemView] = []
        for item in items:
            if item.status is VariantItemStatus.SKIPPED:
                skipped += 1
                updated_items.append(item)
                continue
            if item.generation_job_id is None:
                if item.status is VariantItemStatus.FAILED:
                    failed += 1
                updated_items.append(item)
                continue
            job_status = self.job_statuses.get(
                item.generation_job_id, GenerationJobStatus.QUEUED
            )
            if job_status is GenerationJobStatus.COMPLETED:
                mapped = VariantItemStatus.COMPLETED
                completed += 1
            elif job_status is GenerationJobStatus.FAILED:
                mapped = VariantItemStatus.FAILED
                failed += 1
            else:
                mapped = VariantItemStatus.QUEUED
            updated_items.append(
                VariantItemView(
                    id=item.id,
                    sync_id=item.sync_id,
                    position=item.position,
                    color_name=item.color_name,
                    color_hex=item.color_hex,
                    color_slug=item.color_slug,
                    status=mapped,
                    recolored_object_key=item.recolored_object_key,
                    generation_job_id=item.generation_job_id,
                    error_message=item.error_message,
                    created_at=item.created_at,
                    updated_at=datetime.now(UTC),
                )
            )
        self.items[sync_id] = updated_items
        terminal = resolve_sync_terminal_status(
            total_items=sync.total_items,
            completed_items=completed,
            failed_items=failed,
            skipped_items=skipped,
        )
        status = terminal if terminal is not None else VariantSyncStatus.RUNNING
        updated = VariantSyncView(
            id=sync.id,
            user_id=sync.user_id,
            status=status,
            product_category=sync.product_category,
            engine_mode=sync.engine_mode,
            post_processing_mode=sync.post_processing_mode,
            apply_text_overlays=sync.apply_text_overlays,
            source_image_object_key=sync.source_image_object_key,
            source_mime_type=sync.source_mime_type,
            total_items=sync.total_items,
            completed_items=completed,
            failed_items=failed,
            skipped_items=skipped,
            notify_telegram=sync.notify_telegram,
            notify_push=sync.notify_push,
            telegram_notified_at=sync.telegram_notified_at,
            push_notified_at=sync.push_notified_at,
            error_message=sync.error_message,
            created_at=sync.created_at,
            updated_at=datetime.now(UTC),
            completed_at=datetime.now(UTC) if terminal is not None else None,
            items=(),
        )
        return self._store(updated)

    async def mark_notified(
        self,
        *,
        sync_id: UUID,
        telegram_at: datetime | None = None,
        push_at: datetime | None = None,
    ) -> VariantSyncView:
        sync = self.syncs[sync_id]
        updated = VariantSyncView(
            id=sync.id,
            user_id=sync.user_id,
            status=sync.status,
            product_category=sync.product_category,
            engine_mode=sync.engine_mode,
            post_processing_mode=sync.post_processing_mode,
            apply_text_overlays=sync.apply_text_overlays,
            source_image_object_key=sync.source_image_object_key,
            source_mime_type=sync.source_mime_type,
            total_items=sync.total_items,
            completed_items=sync.completed_items,
            failed_items=sync.failed_items,
            skipped_items=sync.skipped_items,
            notify_telegram=sync.notify_telegram,
            notify_push=sync.notify_push,
            telegram_notified_at=telegram_at,
            push_notified_at=push_at,
            error_message=sync.error_message,
            created_at=sync.created_at,
            updated_at=datetime.now(UTC),
            completed_at=sync.completed_at,
            items=(),
        )
        return self._store(updated)

    async def get_telegram_id(self, user_id: UUID) -> int | None:
        return self.telegram_ids.get(user_id)

    async def get_job_status(self, job_id: UUID) -> GenerationJobStatus | None:
        return self.job_statuses.get(job_id)


def _build_service(
    *,
    repo: _FakeRepo | None = None,
    storage: _FakeStorage | None = None,
    recolor: _FakeRecolor | None = None,
    jobs: _FakeJobFactory | None = None,
    telegram: _FakeTelegram | None = None,
    push: _FakePush | None = None,
    charge_coins: bool = True,
) -> tuple[SmartVariantService, _FakeRepo, _FakeStorage, _FakeRecolor, _FakeJobFactory]:
    repo = repo or _FakeRepo()
    storage = storage or _FakeStorage()
    recolor = recolor or _FakeRecolor()
    jobs = jobs or _FakeJobFactory()
    service = SmartVariantService(
        repo,
        storage=storage,
        recolor=recolor,
        job_factory=jobs,
        max_colors=5,
        max_image_bytes=1024 * 1024,
        coins_per_color=1,
        charge_coins=charge_coins,
        telegram=telegram,
        push=push,
    )
    return service, repo, storage, recolor, jobs


def test_parse_color_specs_json_and_csv() -> None:
    colors = parse_color_specs(
        '[{"name":"Black","hex":"#111111"},{"name":"Red","hex":"#c41e3a"}]',
        max_colors=5,
    )
    assert len(colors) == 2
    assert colors[0].normalize_hex() == "#111111"
    assert colors[1].name == "Red"

    csv_colors = parse_color_specs("Black,navy,#FF0000", max_colors=5)
    assert len(csv_colors) == 3
    assert csv_colors[2].normalize_hex() == "#FF0000"


def test_parse_color_specs_rejects_duplicates_and_overflow() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        parse_color_specs("Black,black", max_colors=5)
    with pytest.raises(ValueError, match="At most"):
        parse_color_specs("a,b,c", max_colors=2)


def test_recolor_prompt_and_overlays_preserve_texture_intent() -> None:
    color = ColorSpec(name="Burgundy", hex_code="#800020")
    prompt = build_recolor_prompt(color, product_category="одежда")
    assert "Burgundy" in prompt
    assert "texture" in prompt.lower()
    assert "shadow" in prompt.lower()
    overlays = build_color_overlay_texts(color)
    assert "cover" in overlays
    assert "Burgundy" in overlays["cover"]


def test_resolve_terminal_and_notify_channels() -> None:
    assert (
        resolve_sync_terminal_status(
            total_items=3, completed_items=3, failed_items=0, skipped_items=0
        )
        is VariantSyncStatus.COMPLETED
    )
    assert (
        resolve_sync_terminal_status(
            total_items=3, completed_items=1, failed_items=2, skipped_items=0
        )
        is VariantSyncStatus.PARTIAL
    )
    assert parse_notify_channels(None) == frozenset(
        {VariantNotifyChannel.TELEGRAM, VariantNotifyChannel.PUSH}
    )


def test_validate_source_image() -> None:
    mime, ext = validate_source_image(_MIN_PNG, max_bytes=1024)
    assert mime == "image/png"
    assert ext == ".png"
    with pytest.raises(ValueError, match="empty"):
        validate_source_image(b"", max_bytes=1024)


@pytest.mark.asyncio
async def test_create_sync_uploads_and_is_idempotent() -> None:
    service, repo, storage, _, _ = _build_service()
    user_id = uuid4()
    sync, created = await service.create_sync(
        user_id=user_id,
        subscription_status="pro",
        image_bytes=_MIN_PNG,
        colors_raw='[{"name":"Black","hex":"#111111"},{"name":"Red","hex":"#FF0000"}]',
        product_category="одежда",
        engine_mode=GenerationEngineMode.STANDARD,
        post_processing_mode=GenerationPostProcessingMode.FAST,
        apply_text_overlays=True,
        notify_channels=frozenset(
            {VariantNotifyChannel.TELEGRAM, VariantNotifyChannel.PUSH}
        ),
        idempotency_key="variant-key-1",
        ai_coins=10,
    )
    assert created is True
    assert sync.total_items == 2
    assert len(sync.items) == 2
    assert any(storage.objects)

    again, created_again = await service.create_sync(
        user_id=user_id,
        subscription_status="pro",
        image_bytes=_MIN_PNG,
        colors_raw="Black,Red",
        product_category="одежда",
        engine_mode=GenerationEngineMode.STANDARD,
        post_processing_mode=GenerationPostProcessingMode.FAST,
        apply_text_overlays=True,
        notify_channels=frozenset({VariantNotifyChannel.PUSH}),
        idempotency_key="variant-key-1",
        ai_coins=10,
    )
    assert created_again is False
    assert again.id == sync.id


@pytest.mark.asyncio
async def test_create_sync_rejects_insufficient_coins() -> None:
    service, _, _, _, _ = _build_service()
    with pytest.raises(BillingValidationError):
        await service.create_sync(
            user_id=uuid4(),
            subscription_status="pro",
            image_bytes=_MIN_PNG,
            colors_raw="Black,Red,Navy",
            product_category=None,
            engine_mode=GenerationEngineMode.STANDARD,
            post_processing_mode=GenerationPostProcessingMode.FAST,
            apply_text_overlays=False,
            notify_channels=frozenset({VariantNotifyChannel.PUSH}),
            idempotency_key=None,
            ai_coins=1,
        )


@pytest.mark.asyncio
async def test_recolor_and_enqueue_creates_jobs_with_overlays() -> None:
    telegram = _FakeTelegram()
    push = _FakePush()
    service, repo, storage, recolor, jobs = _build_service(
        telegram=telegram, push=push
    )
    user_id = uuid4()
    repo.telegram_ids[user_id] = 42
    sync, _ = await service.create_sync(
        user_id=user_id,
        subscription_status="pro",
        image_bytes=_MIN_PNG,
        colors_raw='[{"name":"Black","hex":"#111111"},{"name":"Red","hex":"#FF0000"}]',
        product_category="одежда",
        engine_mode=GenerationEngineMode.STANDARD,
        post_processing_mode=GenerationPostProcessingMode.FAST,
        apply_text_overlays=True,
        notify_channels=frozenset(
            {VariantNotifyChannel.TELEGRAM, VariantNotifyChannel.PUSH}
        ),
        idempotency_key=None,
        ai_coins=10,
    )
    result = await service.recolor_and_enqueue(
        sync_id=sync.id,
        subscription_status="pro",
    )
    assert result.status is VariantSyncStatus.RUNNING
    assert len(recolor.calls) == 2
    assert len(jobs.created) == 2
    assert all(jobs.overlays)
    assert any("Цвет:" in overlay.get("cover", "") for overlay in jobs.overlays)
    assert any(key.startswith("generation-inputs/") for key in storage.objects)

    # Mark child jobs completed and poll → notify
    for item in repo.items[sync.id]:
        assert item.generation_job_id is not None
        repo.job_statuses[item.generation_job_id] = GenerationJobStatus.COMPLETED
    finished = await service.poll_sync_completion(sync.id)
    assert finished.status is VariantSyncStatus.COMPLETED
    assert finished.telegram_notified_at is not None
    assert finished.push_notified_at is not None
    assert telegram.messages
    assert "Smart Variant Sync" in telegram.messages[0][1]
    assert push.payloads


@pytest.mark.asyncio
async def test_recolor_failure_marks_item_failed_partial() -> None:
    recolor = _FakeRecolor()
    recolor.fail_colors.add("red-ff0000")
    service, repo, _, _, jobs = _build_service(recolor=recolor)
    sync, _ = await service.create_sync(
        user_id=uuid4(),
        subscription_status="pro",
        image_bytes=_MIN_PNG,
        colors_raw='[{"name":"Black","hex":"#111111"},{"name":"Red","hex":"#FF0000"}]',
        product_category=None,
        engine_mode=GenerationEngineMode.STANDARD,
        post_processing_mode=GenerationPostProcessingMode.FAST,
        apply_text_overlays=False,
        notify_channels=frozenset({VariantNotifyChannel.PUSH}),
        idempotency_key=None,
        ai_coins=10,
    )
    result = await service.recolor_and_enqueue(
        sync_id=sync.id,
        subscription_status="pro",
    )
    assert len(jobs.created) == 1
    failed = [item for item in repo.items[sync.id] if item.status is VariantItemStatus.FAILED]
    assert len(failed) == 1
    for item in repo.items[sync.id]:
        if item.generation_job_id is not None:
            repo.job_statuses[item.generation_job_id] = GenerationJobStatus.COMPLETED
    finished = await service.poll_sync_completion(sync.id)
    assert finished.status is VariantSyncStatus.PARTIAL


@pytest.mark.asyncio
async def test_get_sync_not_found() -> None:
    service, _, _, _, _ = _build_service()
    with pytest.raises(SmartVariantNotFoundError):
        await service.get_sync_for_user(user_id=uuid4(), sync_id=uuid4())


def test_telegram_message_builder() -> None:
    now = datetime.now(UTC)
    sync = VariantSyncView(
        id=uuid4(),
        user_id=uuid4(),
        status=VariantSyncStatus.COMPLETED,
        product_category="одежда",
        engine_mode="standard",
        post_processing_mode="fast",
        apply_text_overlays=True,
        source_image_object_key="k",
        source_mime_type="image/png",
        total_items=5,
        completed_items=5,
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
    message = build_sync_ready_telegram_message(sync)
    assert "5/5" in message


@pytest.mark.asyncio
async def test_create_sync_validation_error_on_bad_image() -> None:
    service, _, _, _, _ = _build_service()
    with pytest.raises(SmartVariantValidationError):
        await service.create_sync(
            user_id=uuid4(),
            subscription_status="pro",
            image_bytes=b"not-an-image",
            colors_raw="Black",
            product_category=None,
            engine_mode=GenerationEngineMode.STANDARD,
            post_processing_mode=GenerationPostProcessingMode.FAST,
            apply_text_overlays=False,
            notify_channels=frozenset({VariantNotifyChannel.PUSH}),
            idempotency_key=None,
            ai_coins=10,
        )
