from __future__ import annotations

import io
from typing import Any
from uuid import UUID, uuid4

import pytest
from PIL import Image, ImageDraw

import app.application.generation_service as generation_module
from app.application.generation_service import GenerationApplicationService
from app.domain.generation import (
    AttemptWorkItem,
    GenerationJobStatus,
    GenerationWorkItem,
    MarketplaceTextContent,
    OutboxEventType,
    ProviderSubmission,
    ProviderWebhookEvent,
    SlideStatus,
    SlideWorkItem,
)


def _png(color: tuple[int, int, int], *, product: bool = False) -> bytes:
    image = Image.new("RGB", (96, 96), color)
    if product:
        ImageDraw.Draw(image).rectangle((30, 20, 66, 80), fill=(210, 25, 35))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def upload(self, *, object_key: str, data: bytes, content_type: str) -> None:
        self.objects[object_key] = data

    async def download(self, object_key: str, *, max_bytes: int) -> bytes:
        payload = self.objects[object_key]
        assert len(payload) <= max_bytes
        return payload

    async def presign(self, object_key: str) -> str:
        return f"https://storage.test/{object_key}"


class FakeRepository:
    def __init__(self, work: GenerationWorkItem) -> None:
        self.work = work
        self.attempts: dict[UUID, AttemptWorkItem] = {}
        self.attempt_by_ref: dict[str, UUID] = {}
        self.attempted: dict[UUID, set[str]] = {}
        self.outbox: dict[str, tuple[OutboxEventType, UUID, dict[str, object]]] = {}
        self.webhooks: dict[UUID, dict[str, object]] = {}
        self.processed_webhooks: set[UUID] = set()
        self.completed_marketplace_text: MarketplaceTextContent | None = None
        self.failed = 0

    async def get_work_item(self, job_id: UUID) -> GenerationWorkItem | None:
        return self.work if self.work.id == job_id else None

    async def set_job_status(
        self,
        job_id: UUID,
        status: GenerationJobStatus,
        *,
        progress: int | None = None,
        provider_used: str | None = None,
        warning: str | None = None,
    ) -> None:
        self.work = self.work.model_copy(update={"status": status})

    async def begin_attempt(
        self,
        *,
        slide_id: UUID,
        provider_name: str,
        reply_ref: str,
    ) -> AttemptWorkItem:
        slide = self._slide(slide_id)
        number = len(self.attempted.setdefault(slide_id, set())) + 1
        self.attempted[slide_id].add(provider_name)
        attempt = AttemptWorkItem(
            id=uuid4(),
            slide_id=slide_id,
            job_id=self.work.id,
            provider_name=provider_name,
            attempt_number=number,
            reply_ref=reply_ref,
            slide_status=SlideStatus.SUBMITTING,
        )
        self.attempts[attempt.id] = attempt
        self.attempt_by_ref[reply_ref] = attempt.id
        self._replace_slide(
            slide.model_copy(
                update={
                    "status": SlideStatus.SUBMITTING,
                    "provider_used": provider_name,
                    "attempts": number,
                }
            )
        )
        return attempt

    async def mark_attempt_submitted(
        self,
        attempt_id: UUID,
        submission: ProviderSubmission,
    ) -> None:
        attempt = self.attempts[attempt_id].model_copy(
            update={
                "external_job_id": submission.external_job_id,
                "slide_status": SlideStatus.WAITING_WEBHOOK,
            }
        )
        self.attempts[attempt_id] = attempt
        slide = self._slide(attempt.slide_id)
        self._replace_slide(
            slide.model_copy(update={"status": SlideStatus.WAITING_WEBHOOK})
        )

    async def mark_attempt_failed(
        self,
        attempt_id: UUID,
        message: str,
        *,
        abandoned: bool,
    ) -> None:
        self.attempts[attempt_id] = self.attempts[attempt_id].model_copy(
            update={"abandoned": abandoned}
        )

    async def get_attempt_by_reply_ref(self, reply_ref: str) -> AttemptWorkItem | None:
        attempt_id = self.attempt_by_ref.get(reply_ref)
        if attempt_id is None:
            return None
        attempt = self.attempts[attempt_id]
        return attempt.model_copy(
            update={"slide_status": self._slide(attempt.slide_id).status}
        )

    async def get_attempted_providers(self, slide_id: UUID) -> frozenset[str]:
        return frozenset(self.attempted.get(slide_id, set()))

    async def list_stalled_attempts(self, **_: Any) -> tuple[AttemptWorkItem, ...]:
        return ()

    async def fail_expired_jobs(self, **_: Any) -> tuple[UUID, ...]:
        return ()

    async def apply_webhook_progress(
        self,
        attempt_id: UUID,
        event: ProviderWebhookEvent,
    ) -> None:
        attempt = self.attempts[attempt_id]
        status = (
            SlideStatus.PROCESSING
            if event.is_terminal_success
            else SlideStatus.WAITING_WEBHOOK
        )
        self.attempts[attempt_id] = attempt.model_copy(update={"slide_status": status})
        self._replace_slide(
            self._slide(attempt.slide_id).model_copy(update={"status": status})
        )

    async def set_slide_result(
        self,
        *,
        slide_id: UUID,
        provider_name: str,
        object_key: str,
        mime_type: str,
        warning: str | None = None,
    ) -> None:
        slide = self._slide(slide_id)
        self._replace_slide(
            slide.model_copy(
                update={
                    "status": SlideStatus.COMPLETED,
                    "provider_used": provider_name,
                    "result_object_key": object_key,
                    "result_mime_type": mime_type,
                }
            )
        )

    async def fail_job(self, job_id: UUID, error: Any) -> None:
        self.failed += 1
        self.work = self.work.model_copy(update={"status": GenerationJobStatus.FAILED})

    async def complete_job(self, *args: Any, **kwargs: Any) -> None:
        self.completed_marketplace_text = kwargs.get("marketplace_text")
        self.work = self.work.model_copy(
            update={
                "status": GenerationJobStatus.COMPLETED,
                "marketplace_text": self.completed_marketplace_text,
            }
        )

    async def add_outbox(
        self,
        *,
        event_type: OutboxEventType,
        aggregate_id: UUID,
        deduplication_key: str,
        payload: dict[str, object],
    ) -> None:
        self.outbox.setdefault(
            deduplication_key,
            (event_type, aggregate_id, payload),
        )

    async def get_webhook_payload(
        self, webhook_event_id: UUID
    ) -> dict[str, object] | None:
        return self.webhooks.get(webhook_event_id)

    async def mark_webhook_processed(self, webhook_event_id: UUID) -> None:
        self.processed_webhooks.add(webhook_event_id)

    async def refund_coin_once(self, job_id: UUID) -> None:
        return None

    def _slide(self, slide_id: UUID) -> SlideWorkItem:
        return next(slide for slide in self.work.slides if slide.id == slide_id)

    def _replace_slide(self, replacement: SlideWorkItem) -> None:
        self.work = self.work.model_copy(
            update={
                "slides": tuple(
                    replacement if slide.id == replacement.id else slide
                    for slide in self.work.slides
                )
            }
        )


class AsyncProvider:
    def __init__(self, name: str, *, fail_submit: bool = False) -> None:
        self.name = name
        self.callback_token = "test-webhook-token-with-enough-entropy"
        self.fail_submit = fail_submit
        self.downloads = 0
        self.background = _png((100, 170, 230))

    async def submit(self, **kwargs: Any) -> ProviderSubmission:
        if self.fail_submit:
            raise ConnectionError(f"{self.name} is unavailable")
        return ProviderSubmission(
            provider=self.name,
            external_job_id=f"{self.name}-job",
            reply_ref=str(kwargs["reply_ref"]),
            initial_status="created",
        )

    async def download_result(self, result_url: str) -> bytes:
        self.downloads += 1
        return self.background

    async def check_once(self, *args: Any, **kwargs: Any) -> None:
        return None


class ImmediateProvider:
    name = "stable_diffusion"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, **kwargs: Any) -> bytes:
        self.calls += 1
        return _png((100, 170, 230))


class TextProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate_marketplace_text(self, **kwargs: Any) -> MarketplaceTextContent:
        self.calls += 1
        assert kwargs["images"]
        return MarketplaceTextContent(
            title="SEO заголовок для WB и Ozon с ключевыми словами",
            description=" ".join(["Продающее описание товара с LSI ключами"] * 40),
            characteristics=(
                "Показывает товар в выгодном ракурсе",
                "Подчеркивает преимущества для покупателя",
                "Подходит для карточки маркетплейса",
            ),
        )


def _work() -> GenerationWorkItem:
    job_id = uuid4()
    return GenerationWorkItem(
        id=job_id,
        user_id=uuid4(),
        status=GenerationJobStatus.QUEUED,
        input_object_key=f"inputs/{job_id}.png",
        subscription_status="Pro",
        slides=(
            SlideWorkItem(
                id=uuid4(),
                slide_key="cover",
                position=1,
                status=SlideStatus.QUEUED,
                selected_style="studio",
                prompt="premium product background",
            ),
        ),
    )


@pytest.fixture(autouse=True)
def _disable_real_circuit_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(_: str) -> None:
        return None

    monkeypatch.setattr(generation_module, "note_provider_failure", _noop)
    monkeypatch.setattr(generation_module, "note_provider_success", _noop)


@pytest.mark.asyncio
async def test_submit_uses_spare_provider_without_polling() -> None:
    work = _work()
    repository = FakeRepository(work)
    storage = FakeStorage()
    storage.objects[work.input_object_key] = _png((255, 255, 255), product=True)
    immediate = ImmediateProvider()
    primary = AsyncProvider("primary", fail_submit=True)
    secondary = AsyncProvider("secondary")
    service = GenerationApplicationService(
        repository=repository,
        storage=storage,
        async_providers=(primary, secondary),
        immediate_provider=immediate,
    )

    await service.submit_job(work.id)

    assert immediate.calls == 0
    assert repository.work.status == GenerationJobStatus.WAITING_WEBHOOK
    assert repository.work.slides[0].status == SlideStatus.WAITING_WEBHOOK
    assert repository.work.slides[0].provider_used == "secondary"


@pytest.mark.asyncio
async def test_provider_pool_falls_back_to_stable_diffusion() -> None:
    work = _work()
    repository = FakeRepository(work)
    storage = FakeStorage()
    storage.objects[work.input_object_key] = _png((255, 255, 255), product=True)
    immediate = ImmediateProvider()
    service = GenerationApplicationService(
        repository=repository,
        storage=storage,
        async_providers=(
            AsyncProvider("primary", fail_submit=True),
            AsyncProvider("secondary", fail_submit=True),
        ),
        immediate_provider=immediate,
    )

    await service.submit_job(work.id)

    assert immediate.calls == 1
    assert repository.work.slides[0].status == SlideStatus.COMPLETED
    assert repository.work.slides[0].provider_used == "stable_diffusion"
    assert f"finalize-job:{work.id}" in repository.outbox
    assert repository.failed == 0


@pytest.mark.asyncio
async def test_duplicate_webhook_does_not_download_or_store_twice() -> None:
    work = _work()
    repository = FakeRepository(work)
    storage = FakeStorage()
    storage.objects[work.input_object_key] = _png((255, 255, 255), product=True)
    provider = AsyncProvider("primary")
    service = GenerationApplicationService(
        repository=repository,
        storage=storage,
        async_providers=(provider,),
        immediate_provider=ImmediateProvider(),
    )
    await service.submit_job(work.id)
    attempt = next(iter(repository.attempts.values()))
    event = ProviderWebhookEvent(
        provider="primary",
        event_id="delivery-1",
        external_job_id=attempt.external_job_id,
        reply_ref=attempt.reply_ref,
        status="completed",
        progress=100,
        result_url="https://cdn.test/result.png",
    )
    webhook_id = uuid4()
    repository.webhooks[webhook_id] = {"normalized": event.model_dump(mode="json")}

    await service.process_webhook(webhook_id)
    await service.process_webhook(webhook_id)
    await service.finalize_job(work.id)

    assert provider.downloads == 1
    assert repository.work.slides[0].status == SlideStatus.COMPLETED
    assert repository.work.status == GenerationJobStatus.COMPLETED
    assert any(key.endswith("card_series.zip") for key in storage.objects)
    assert any(key.endswith("thumbnail.jpg") for key in storage.objects)
    assert webhook_id in repository.processed_webhooks


@pytest.mark.asyncio
async def test_finalize_generates_marketplace_text_from_completed_images() -> None:
    base_work = _work()
    work = base_work.model_copy(
        update={
            "slides": (
                base_work.slides[0].model_copy(
                    update={
                        "status": SlideStatus.COMPLETED,
                        "result_object_key": "slides/cover.png",
                        "result_mime_type": "image/png",
                    }
                ),
            )
        }
    )
    repository = FakeRepository(work)
    storage = FakeStorage()
    storage.objects["slides/cover.png"] = _png((100, 170, 230), product=True)
    text_provider = TextProvider()
    service = GenerationApplicationService(
        repository=repository,
        storage=storage,
        async_providers=(),
        immediate_provider=ImmediateProvider(),
        text_provider=text_provider,
    )

    await service.finalize_job(work.id)

    assert text_provider.calls == 1
    assert repository.work.marketplace_text is not None
    assert repository.work.marketplace_text.description
