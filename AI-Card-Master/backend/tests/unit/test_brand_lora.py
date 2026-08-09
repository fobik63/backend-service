"""Unit tests for Custom Brand LoRA domain and application service."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.application.brand_lora_service import (
    BrandLoraForbiddenError,
    BrandLoraNotFoundError,
    BrandLoraService,
)
from app.domain.brand_lora import (
    BrandLoraReferenceView,
    BrandLoraStatus,
    BrandLoraView,
    BrandStyleFilter,
    LoraTrainingPollResult,
    LoraTrainingStartResult,
    apply_brand_filter_to_prompt,
    apply_brand_filter_to_style,
    build_trigger_word,
    normalize_brand_name,
    synthesize_brand_style_prompt,
    validate_reference_batch_count,
    validate_reference_image,
)
from app.services.billing_service import BillingValidationError
from app.services.series_generator import SeriesTask

_MIN_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


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


class _FakeTrainer:
    name = "fake"

    def __init__(self) -> None:
        self.started: list[str] = []
        self.poll_status = "succeeded"
        self.fail_start = False

    async def start_training(
        self,
        *,
        trigger_word: str,
        brand_name: str,
        notes: str | None,
        reference_object_keys: tuple[str, ...],
        dataset_zip_bytes: bytes | None = None,
    ) -> LoraTrainingStartResult:
        _ = (brand_name, notes, reference_object_keys, dataset_zip_bytes)
        if self.fail_start:
            raise RuntimeError("trainer down")
        training_id = f"train-{trigger_word}"
        self.started.append(training_id)
        return LoraTrainingStartResult(training_id=training_id, status="starting")

    async def poll_training(self, *, training_id: str) -> LoraTrainingPollResult:
        return LoraTrainingPollResult(
            training_id=training_id,
            status=self.poll_status,
            progress=100 if self.poll_status == "succeeded" else 40,
            weights_url="https://example.com/weights.safetensors"
            if self.poll_status == "succeeded"
            else None,
            version_id="v1" if self.poll_status == "succeeded" else None,
            error_message="boom" if self.poll_status == "failed" else None,
            brand_style_prompt="luxury brand dna" if self.poll_status == "succeeded" else None,
        )


class _FakeRepo:
    def __init__(self) -> None:
        self.profiles: dict[UUID, BrandLoraView] = {}
        self.balances: dict[UUID, int] = {}
        self.refunds: list[tuple[UUID, int]] = []

    def seed_balance(self, user_id: UUID, coins: int) -> None:
        self.balances[user_id] = coins

    async def create_profile(
        self,
        *,
        user_id: UUID,
        name: str,
        trigger_word: str,
        notes: str | None,
        coins_charged: int,
        references: tuple[tuple[str, str, int], ...],
    ) -> BrandLoraView:
        if coins_charged > 0:
            await self.debit_coins(user_id=user_id, amount=coins_charged)
        now = datetime.now(UTC)
        profile_id = uuid4()
        refs = tuple(
            BrandLoraReferenceView(
                id=uuid4(),
                profile_id=profile_id,
                position=index,
                object_key=object_key,
                mime_type=mime,
                size_bytes=size,
                created_at=now,
            )
            for index, (object_key, mime, size) in enumerate(references, start=1)
        )
        view = BrandLoraView(
            id=profile_id,
            user_id=user_id,
            name=name,
            trigger_word=trigger_word,
            status=BrandLoraStatus.QUEUED,
            is_active=False,
            brand_style_prompt=None,
            lora_weights_url=None,
            provider_training_id=None,
            provider_version_id=None,
            lora_scale=0.85,
            reference_count=len(references),
            coins_charged=coins_charged,
            error_message=None,
            training_progress=0,
            notes=notes,
            created_at=now,
            updated_at=now,
            trained_at=None,
            references=refs,
        )
        self.profiles[profile_id] = view
        return view

    async def get_for_user(
        self, *, user_id: UUID, profile_id: UUID, include_references: bool = False
    ) -> BrandLoraView | None:
        profile = self.profiles.get(profile_id)
        if profile is None or profile.user_id != user_id:
            return None
        return profile

    async def get(
        self, *, profile_id: UUID, include_references: bool = True
    ) -> BrandLoraView | None:
        return self.profiles.get(profile_id)

    async def list_for_user(
        self, *, user_id: UUID, limit: int = 50
    ) -> tuple[BrandLoraView, ...]:
        items = [
            p
            for p in self.profiles.values()
            if p.user_id == user_id and p.status != BrandLoraStatus.ARCHIVED
        ]
        return tuple(sorted(items, key=lambda p: p.created_at, reverse=True)[:limit])

    async def get_active_filter(self, *, user_id: UUID) -> BrandStyleFilter | None:
        for profile in self.profiles.values():
            if (
                profile.user_id == user_id
                and profile.is_active
                and profile.status == BrandLoraStatus.READY
                and profile.brand_style_prompt
            ):
                return BrandStyleFilter(
                    profile_id=profile.id,
                    trigger_word=profile.trigger_word,
                    brand_style_prompt=profile.brand_style_prompt,
                    lora_weights_url=profile.lora_weights_url,
                    lora_scale=profile.lora_scale,
                )
        return None

    def _replace(self, profile_id: UUID, **kwargs) -> BrandLoraView:
        current = self.profiles[profile_id]
        data = {
            "id": current.id,
            "user_id": current.user_id,
            "name": current.name,
            "trigger_word": current.trigger_word,
            "status": current.status,
            "is_active": current.is_active,
            "brand_style_prompt": current.brand_style_prompt,
            "lora_weights_url": current.lora_weights_url,
            "provider_training_id": current.provider_training_id,
            "provider_version_id": current.provider_version_id,
            "lora_scale": current.lora_scale,
            "reference_count": current.reference_count,
            "coins_charged": current.coins_charged,
            "error_message": current.error_message,
            "training_progress": current.training_progress,
            "notes": current.notes,
            "created_at": current.created_at,
            "updated_at": datetime.now(UTC),
            "trained_at": current.trained_at,
            "references": current.references,
        }
        data.update(kwargs)
        view = BrandLoraView(**data)
        self.profiles[profile_id] = view
        return view

    async def mark_training_started(
        self,
        *,
        profile_id: UUID,
        provider_training_id: str,
        brand_style_prompt: str,
        status: BrandLoraStatus = BrandLoraStatus.TRAINING,
        progress: int = 5,
    ) -> BrandLoraView:
        return self._replace(
            profile_id,
            provider_training_id=provider_training_id,
            brand_style_prompt=brand_style_prompt,
            status=status,
            training_progress=progress,
        )

    async def mark_progress(
        self,
        *,
        profile_id: UUID,
        status: BrandLoraStatus,
        progress: int,
        error_message: str | None = None,
    ) -> BrandLoraView:
        return self._replace(
            profile_id,
            status=status,
            training_progress=progress,
            error_message=error_message,
        )

    async def mark_ready(
        self,
        *,
        profile_id: UUID,
        brand_style_prompt: str,
        lora_weights_url: str | None,
        provider_version_id: str | None,
        activate: bool = True,
    ) -> BrandLoraView:
        current = self.profiles[profile_id]
        if activate:
            for other_id, other in list(self.profiles.items()):
                if other.user_id == current.user_id and other.is_active:
                    self._replace(other_id, is_active=False)
        return self._replace(
            profile_id,
            brand_style_prompt=brand_style_prompt,
            lora_weights_url=lora_weights_url,
            provider_version_id=provider_version_id,
            status=BrandLoraStatus.READY,
            training_progress=100,
            is_active=activate,
            trained_at=datetime.now(UTC),
            error_message=None,
        )

    async def mark_failed(
        self, *, profile_id: UUID, error_message: str
    ) -> BrandLoraView:
        return self._replace(
            profile_id,
            status=BrandLoraStatus.FAILED,
            training_progress=100,
            is_active=False,
            error_message=error_message,
        )

    async def set_active(
        self, *, user_id: UUID, profile_id: UUID, active: bool
    ) -> BrandLoraView:
        profile = self.profiles.get(profile_id)
        if profile is None or profile.user_id != user_id:
            raise LookupError("Brand LoRA profile was not found.")
        if profile.status != BrandLoraStatus.READY:
            raise ValueError("Only ready Brand LoRA profiles can be activated.")
        if active:
            for other_id, other in list(self.profiles.items()):
                if other.user_id == user_id and other.is_active:
                    self._replace(other_id, is_active=False)
        return self._replace(profile_id, is_active=active)

    async def archive(self, *, user_id: UUID, profile_id: UUID) -> BrandLoraView:
        profile = self.profiles.get(profile_id)
        if profile is None or profile.user_id != user_id:
            raise LookupError("Brand LoRA profile was not found.")
        return self._replace(
            profile_id, status=BrandLoraStatus.ARCHIVED, is_active=False
        )

    async def list_active_training_ids(self, *, limit: int) -> tuple[UUID, ...]:
        ids = [
            p.id
            for p in self.profiles.values()
            if p.status in {BrandLoraStatus.QUEUED, BrandLoraStatus.TRAINING}
        ]
        return tuple(ids[:limit])

    async def debit_coins(self, *, user_id: UUID, amount: int) -> int:
        balance = self.balances.get(user_id, 0)
        if balance < amount:
            raise BillingValidationError("Insufficient AI-coin balance")
        self.balances[user_id] = balance - amount
        return self.balances[user_id]

    async def refund_coins(self, *, user_id: UUID, amount: int) -> int:
        self.refunds.append((user_id, amount))
        self.balances[user_id] = self.balances.get(user_id, 0) + amount
        return self.balances[user_id]


def _service(
    repo: _FakeRepo,
    trainer: _FakeTrainer | None = None,
    *,
    min_references: int = 2,
    max_references: int = 5,
    cost: int = 10,
) -> BrandLoraService:
    return BrandLoraService(
        repo,
        storage=_FakeStorage(),
        trainer=trainer or _FakeTrainer(),
        min_references=min_references,
        max_references=max_references,
        max_image_bytes=1024 * 1024,
        training_cost_coins=cost,
        charge_coins=True,
        auto_activate_on_ready=True,
    )


def test_normalize_and_trigger() -> None:
    assert normalize_brand_name("  Acme Brand  ") == "Acme Brand"
    assert build_trigger_word("Acme Brand").startswith("brnd")
    with pytest.raises(ValueError):
        normalize_brand_name("x")


def test_reference_validation() -> None:
    validate_reference_batch_count(20, min_images=20, max_images=30)
    with pytest.raises(ValueError):
        validate_reference_batch_count(5, min_images=20, max_images=30)
    mime, ext = validate_reference_image(_MIN_PNG, max_bytes=1024)
    assert mime == "image/png"
    assert ext == ".png"


def test_apply_brand_filter_to_series() -> None:
    brand = BrandStyleFilter(
        profile_id=uuid4(),
        trigger_word="brndacme",
        brand_style_prompt="matte luxury palette",
        lora_weights_url=None,
        lora_scale=0.8,
    )
    task = SeriesTask(slide_key="cover", selected_style="studio", user_text="hero shot")
    patched_style = apply_brand_filter_to_style(task.selected_style, brand)
    patched_prompt = apply_brand_filter_to_prompt(task.user_text, brand)
    assert "brndacme" in patched_style
    assert "Brand LoRA" in patched_prompt
    assert patched_style.endswith("matte luxury palette")


@pytest.mark.asyncio
async def test_create_training_happy_path() -> None:
    repo = _FakeRepo()
    user_id = uuid4()
    repo.seed_balance(user_id, 100)
    service = _service(repo)
    profile = await service.create_training(
        user_id=user_id,
        subscription_status="Pro",
        brand_name="Nordic Home",
        notes="cool scandi",
        images=(_MIN_PNG, _MIN_PNG),
        ai_coins=100,
    )
    assert profile.status == BrandLoraStatus.QUEUED
    assert profile.reference_count == 2
    assert repo.balances[user_id] == 90


@pytest.mark.asyncio
async def test_create_training_tariff_gate() -> None:
    repo = _FakeRepo()
    service = _service(repo)
    with pytest.raises(BrandLoraForbiddenError):
        await service.create_training(
            user_id=uuid4(),
            subscription_status="Free",
            brand_name="Nordic Home",
            notes=None,
            images=(_MIN_PNG, _MIN_PNG),
            ai_coins=100,
        )


@pytest.mark.asyncio
async def test_create_training_insufficient_coins() -> None:
    repo = _FakeRepo()
    user_id = uuid4()
    repo.seed_balance(user_id, 1)
    service = _service(repo, cost=50)
    with pytest.raises(BillingValidationError):
        await service.create_training(
            user_id=user_id,
            subscription_status="Pro",
            brand_name="Nordic Home",
            notes=None,
            images=(_MIN_PNG, _MIN_PNG),
            ai_coins=1,
        )


@pytest.mark.asyncio
async def test_training_pipeline_ready_and_active_filter() -> None:
    repo = _FakeRepo()
    trainer = _FakeTrainer()
    user_id = uuid4()
    repo.seed_balance(user_id, 100)
    service = _service(repo, trainer)
    profile = await service.create_training(
        user_id=user_id,
        subscription_status="Year",
        brand_name="Lumen Cosmetics",
        notes=None,
        images=(_MIN_PNG, _MIN_PNG, _MIN_PNG),
        ai_coins=100,
    )
    started = await service.start_training_job(profile_id=profile.id)
    assert started.status == BrandLoraStatus.TRAINING
    assert started.provider_training_id
    ready = await service.poll_training_job(profile_id=profile.id)
    assert ready.status == BrandLoraStatus.READY
    assert ready.is_active is True
    active = await service.get_active_filter(user_id=user_id)
    assert active is not None
    assert active.trigger_word == ready.trigger_word


@pytest.mark.asyncio
async def test_training_failure_refunds_coins() -> None:
    repo = _FakeRepo()
    trainer = _FakeTrainer()
    trainer.fail_start = True
    user_id = uuid4()
    repo.seed_balance(user_id, 50)
    service = _service(repo, trainer, cost=10)
    profile = await service.create_training(
        user_id=user_id,
        subscription_status="Pro",
        brand_name="Fail Brand",
        notes=None,
        images=(_MIN_PNG, _MIN_PNG),
        ai_coins=50,
    )
    assert repo.balances[user_id] == 40
    failed = await service.start_training_job(profile_id=profile.id)
    assert failed.status == BrandLoraStatus.FAILED
    assert repo.balances[user_id] == 50
    assert repo.refunds == [(user_id, 10)]


@pytest.mark.asyncio
async def test_activate_archive_and_style_prompt() -> None:
    repo = _FakeRepo()
    user_id = uuid4()
    repo.seed_balance(user_id, 100)
    service = _service(repo)
    profile = await service.create_training(
        user_id=user_id,
        subscription_status="Pro",
        brand_name="Archive Me",
        notes=None,
        images=(_MIN_PNG, _MIN_PNG),
        ai_coins=100,
    )
    with pytest.raises(BrandLoraNotFoundError):
        await service.get_for_user(user_id=uuid4(), profile_id=profile.id)
    archived = await service.archive(user_id=user_id, profile_id=profile.id)
    assert archived.status == BrandLoraStatus.ARCHIVED
    prompt = synthesize_brand_style_prompt(
        brand_name="Acme", trigger_word="brndacme", notes="gold"
    )
    assert "Acme" in prompt and "gold" in prompt
