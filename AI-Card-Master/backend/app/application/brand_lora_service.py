"""Application use cases for Custom Brand LoRA training and activation."""

from __future__ import annotations

import io
import logging
import zipfile
from typing import Protocol
from uuid import UUID, uuid4

from app.application.ports.brand_lora import (
    BrandLoraPersistencePort,
    LoraTrainingProviderPort,
)
from app.domain.brand_lora import (
    BrandLoraStatus,
    BrandLoraView,
    BrandStyleFilter,
    build_trigger_word,
    is_terminal_status,
    map_provider_status,
    normalize_brand_name,
    synthesize_brand_style_prompt,
    validate_reference_batch_count,
    validate_reference_image,
)
from app.models.enums import SubscriptionStatus
from app.services.billing_service import BillingValidationError

logger = logging.getLogger(__name__)


class ObjectStoragePort(Protocol):
    """Minimal S3 port for brand reference uploads and dataset ZIP."""

    async def upload_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        presign: bool = True,
    ) -> object: ...

    async def download_bytes(self, *, object_key: str, max_bytes: int) -> bytes: ...


class BrandLoraError(Exception):
    """Base Brand LoRA workflow failure."""


class BrandLoraValidationError(BrandLoraError):
    """Invalid brand name, references, or tariff gate."""


class BrandLoraNotFoundError(BrandLoraError):
    """Profile missing or not owned by the caller."""


class BrandLoraForbiddenError(BrandLoraError):
    """Tariff does not allow Custom LoRA training."""


class BrandLoraService:
    """Coordinate reference upload, LoRA/BrandDNA training, and activation."""

    def __init__(
        self,
        repository: BrandLoraPersistencePort,
        *,
        storage: ObjectStoragePort,
        trainer: LoraTrainingProviderPort,
        min_references: int,
        max_references: int,
        max_image_bytes: int,
        training_cost_coins: int,
        charge_coins: bool,
        auto_activate_on_ready: bool = True,
    ) -> None:
        if min_references <= 0 or max_references < min_references:
            raise BrandLoraValidationError("Invalid reference count bounds.")
        if max_image_bytes <= 0:
            raise BrandLoraValidationError("max_image_bytes must be positive.")
        if training_cost_coins < 0:
            raise BrandLoraValidationError("training_cost_coins must be >= 0.")
        self._repository = repository
        self._storage = storage
        self._trainer = trainer
        self._min_references = min_references
        self._max_references = max_references
        self._max_image_bytes = max_image_bytes
        self._training_cost_coins = training_cost_coins
        self._charge_coins = charge_coins
        self._auto_activate_on_ready = auto_activate_on_ready

    @property
    def min_references(self) -> int:
        return self._min_references

    @property
    def max_references(self) -> int:
        return self._max_references

    @property
    def max_image_bytes(self) -> int:
        return self._max_image_bytes

    @property
    def training_cost_coins(self) -> int:
        if not self._charge_coins:
            return 0
        return self._training_cost_coins

    def ensure_tariff_allowed(self, subscription_status: str) -> None:
        """Custom LoRA is gated to Pro-tier workspace owners (enterprise brands)."""

        try:
            status = SubscriptionStatus(subscription_status)
        except ValueError as exc:
            raise BrandLoraForbiddenError(
                "Custom Brand LoRA requires a Pro / HalfYear / Year subscription."
            ) from exc
        if not status.can_own_workspace():
            raise BrandLoraForbiddenError(
                "Custom Brand LoRA requires a Pro / HalfYear / Year subscription."
            )

    async def create_training(
        self,
        *,
        user_id: UUID,
        subscription_status: str,
        brand_name: str,
        notes: str | None,
        images: tuple[bytes, ...],
        ai_coins: int,
    ) -> BrandLoraView:
        """Validate refs, upload to S3, debit coins, enqueue training profile."""

        self.ensure_tariff_allowed(subscription_status)
        try:
            name = normalize_brand_name(brand_name)
            validate_reference_batch_count(
                len(images),
                min_images=self._min_references,
                max_images=self._max_references,
            )
        except ValueError as exc:
            raise BrandLoraValidationError(str(exc)) from exc

        cleaned_notes = notes.strip()[:500] if notes and notes.strip() else None
        trigger = build_trigger_word(name)
        cost = self.training_cost_coins
        if self._charge_coins and ai_coins < cost:
            raise BillingValidationError(
                f"Insufficient AI-coin balance for Brand LoRA training "
                f"(need {cost})."
            )

        validated: list[tuple[bytes, str, str]] = []
        for raw in images:
            try:
                mime, extension = validate_reference_image(
                    raw, max_bytes=self._max_image_bytes
                )
            except ValueError as exc:
                raise BrandLoraValidationError(str(exc)) from exc
            validated.append((raw, mime, extension))

        uploaded: list[tuple[str, str, int]] = []
        for index, (raw, mime, extension) in enumerate(validated, start=1):
            object_key = (
                f"brand-lora/{user_id}/{uuid4().hex}/ref_{index:02d}{extension}"
            )
            await self._storage.upload_bytes(
                object_key=object_key,
                data=raw,
                content_type=mime,
                presign=False,
            )
            uploaded.append((object_key, mime, len(raw)))

        return await self._repository.create_profile(
            user_id=user_id,
            name=name,
            trigger_word=trigger,
            notes=cleaned_notes,
            coins_charged=cost,
            references=tuple(uploaded),
        )

    async def get_for_user(
        self, *, user_id: UUID, profile_id: UUID
    ) -> BrandLoraView:
        profile = await self._repository.get_for_user(
            user_id=user_id,
            profile_id=profile_id,
            include_references=True,
        )
        if profile is None:
            raise BrandLoraNotFoundError("Brand LoRA profile was not found.")
        return profile

    async def list_for_user(self, *, user_id: UUID) -> tuple[BrandLoraView, ...]:
        return await self._repository.list_for_user(user_id=user_id)

    async def get_active_filter(self, *, user_id: UUID) -> BrandStyleFilter | None:
        return await self._repository.get_active_filter(user_id=user_id)

    async def set_active(
        self, *, user_id: UUID, profile_id: UUID, active: bool
    ) -> BrandLoraView:
        try:
            return await self._repository.set_active(
                user_id=user_id, profile_id=profile_id, active=active
            )
        except LookupError as exc:
            raise BrandLoraNotFoundError(str(exc)) from exc
        except ValueError as exc:
            raise BrandLoraValidationError(str(exc)) from exc

    async def archive(self, *, user_id: UUID, profile_id: UUID) -> BrandLoraView:
        try:
            return await self._repository.archive(
                user_id=user_id, profile_id=profile_id
            )
        except LookupError as exc:
            raise BrandLoraNotFoundError(str(exc)) from exc

    async def start_training_job(self, *, profile_id: UUID) -> BrandLoraView:
        """Worker entry: kick off provider training for a queued profile."""

        profile = await self._repository.get(
            profile_id=profile_id, include_references=True
        )
        if profile is None:
            raise BrandLoraNotFoundError("Brand LoRA profile was not found.")
        if profile.status not in {BrandLoraStatus.QUEUED, BrandLoraStatus.TRAINING}:
            return profile
        if profile.provider_training_id and profile.status == BrandLoraStatus.TRAINING:
            return profile

        brand_prompt = synthesize_brand_style_prompt(
            brand_name=profile.name,
            trigger_word=profile.trigger_word,
            notes=profile.notes,
        )
        keys = tuple(ref.object_key for ref in profile.references)
        dataset_zip = await self._build_dataset_zip(profile)
        try:
            started = await self._trainer.start_training(
                trigger_word=profile.trigger_word,
                brand_name=profile.name,
                notes=profile.notes,
                reference_object_keys=keys,
                dataset_zip_bytes=dataset_zip,
            )
        except Exception as exc:
            logger.exception("Brand LoRA training start failed profile=%s", profile_id)
            failed = await self._repository.mark_failed(
                profile_id=profile_id,
                error_message=str(exc)[:1000],
            )
            if failed.coins_charged > 0:
                await self._repository.refund_coins(
                    user_id=failed.user_id, amount=failed.coins_charged
                )
            return failed

        return await self._repository.mark_training_started(
            profile_id=profile_id,
            provider_training_id=started.training_id,
            brand_style_prompt=brand_prompt,
            status=BrandLoraStatus.TRAINING,
            progress=5,
        )

    async def poll_training_job(self, *, profile_id: UUID) -> BrandLoraView:
        """Worker entry: poll provider and transition to ready/failed."""

        profile = await self._repository.get(
            profile_id=profile_id, include_references=False
        )
        if profile is None:
            raise BrandLoraNotFoundError("Brand LoRA profile was not found.")
        if is_terminal_status(profile.status):
            return profile
        if not profile.provider_training_id:
            return await self.start_training_job(profile_id=profile_id)

        try:
            poll = await self._trainer.poll_training(
                training_id=profile.provider_training_id
            )
        except Exception as exc:
            logger.warning(
                "Brand LoRA poll error profile=%s: %s",
                profile_id,
                exc,
                exc_info=True,
            )
            return await self._repository.mark_progress(
                profile_id=profile_id,
                status=BrandLoraStatus.TRAINING,
                progress=max(profile.training_progress, 20),
                error_message=None,
            )

        mapped = map_provider_status(poll.status)
        if mapped == BrandLoraStatus.READY:
            style_prompt = (
                poll.brand_style_prompt
                or profile.brand_style_prompt
                or synthesize_brand_style_prompt(
                    brand_name=profile.name,
                    trigger_word=profile.trigger_word,
                    notes=profile.notes,
                )
            )
            return await self._repository.mark_ready(
                profile_id=profile_id,
                brand_style_prompt=style_prompt,
                lora_weights_url=poll.weights_url,
                provider_version_id=poll.version_id,
                activate=self._auto_activate_on_ready,
            )
        if mapped == BrandLoraStatus.FAILED:
            failed = await self._repository.mark_failed(
                profile_id=profile_id,
                error_message=poll.error_message or "LoRA training failed.",
            )
            if failed.coins_charged > 0:
                await self._repository.refund_coins(
                    user_id=failed.user_id, amount=failed.coins_charged
                )
            return failed
        return await self._repository.mark_progress(
            profile_id=profile_id,
            status=mapped,
            progress=poll.progress,
        )

    async def poll_active_trainings(self, *, limit: int) -> int:
        """Beat entry: advance all non-terminal training profiles."""

        ids = await self._repository.list_active_training_ids(limit=limit)
        processed = 0
        for profile_id in ids:
            profile = await self._repository.get(
                profile_id=profile_id, include_references=False
            )
            if profile is None:
                continue
            if profile.status == BrandLoraStatus.QUEUED or not profile.provider_training_id:
                await self.start_training_job(profile_id=profile_id)
            else:
                await self.poll_training_job(profile_id=profile_id)
            processed += 1
        return processed

    async def _build_dataset_zip(self, profile: BrandLoraView) -> bytes | None:
        """Pack reference images into a ZIP for providers that need a dataset."""

        if not profile.references:
            return None
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for ref in profile.references:
                try:
                    data = await self._storage.download_bytes(
                        object_key=ref.object_key,
                        max_bytes=self._max_image_bytes,
                    )
                except Exception:
                    logger.warning(
                        "Skipping missing brand ref key=%s",
                        ref.object_key,
                        exc_info=True,
                    )
                    continue
                ext = ".jpg"
                if ref.mime_type == "image/png":
                    ext = ".png"
                elif ref.mime_type == "image/webp":
                    ext = ".webp"
                stem = f"{profile.trigger_word}_{ref.position:02d}"
                archive.writestr(f"{stem}{ext}", data)
                archive.writestr(
                    f"{stem}.txt",
                    f"{profile.trigger_word}, {profile.name} brand style",
                )
        payload = buffer.getvalue()
        return payload or None
