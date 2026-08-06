"""Use cases for intelligent niche visual audit (Brand Dominant filter → Rising Stars)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from app.application.ports.visual_audit import (
    RisingStarVisionPort,
    VisualAuditPersistencePort,
)
from app.domain.bulk_generation import detect_image_mime
from app.domain.visual_audit import (
    NicheCardSignal,
    NicheFilterReport,
    RisingStarVisionDissection,
    VisualAuditEnqueueRequest,
    VisualAuditFilterConfig,
    VisualAuditJobStatus,
    VisualAuditJobView,
    build_generator_trigger_config,
    dump_filter_report,
    dump_generator_config,
    filter_niche_top_cards,
    redis_visual_audit_key,
)
from app.infrastructure.redis import (
    RedisUnavailableError,
    cache_json,
    get_cached_json,
)

logger = logging.getLogger(__name__)


class ObjectStoragePort(Protocol):
    """Minimal S3 port for Rising Star image download."""

    async def download_bytes(self, *, object_key: str, max_bytes: int) -> bytes: ...


class VisualAuditError(Exception):
    """Base visual-audit workflow failure."""


class VisualAuditValidationError(VisualAuditError):
    """Invalid request payload."""


class VisualAuditNotFoundError(VisualAuditError):
    """Job was not found for the user."""


class VisualAuditService:
    """Coordinate filter → Rising Star Vision → generator JSON via Celery."""

    def __init__(
        self,
        repository: VisualAuditPersistencePort,
        *,
        storage: ObjectStoragePort,
        model_name: str,
        max_image_bytes: int,
        redis_stage_ttl_seconds: int,
        default_filter_config: VisualAuditFilterConfig | None = None,
        vision: RisingStarVisionPort | None = None,
    ) -> None:
        if not model_name.strip():
            raise VisualAuditValidationError("model_name must not be empty.")
        if max_image_bytes <= 0:
            raise VisualAuditValidationError("max_image_bytes must be positive.")
        if redis_stage_ttl_seconds <= 0:
            raise VisualAuditValidationError(
                "redis_stage_ttl_seconds must be positive."
            )
        self._repository = repository
        self._storage = storage
        self._vision = vision
        self._model_name = model_name.strip()
        self._max_image_bytes = max_image_bytes
        self._redis_stage_ttl_seconds = redis_stage_ttl_seconds
        self._default_filter_config = default_filter_config or VisualAuditFilterConfig()

    def _require_vision(self) -> RisingStarVisionPort:
        if self._vision is None:
            raise VisualAuditError(
                "Claude Vision client is not configured for this process."
            )
        return self._vision

    def preview_filter(
        self, request: VisualAuditEnqueueRequest
    ) -> NicheFilterReport:
        """Synchronous survivor-bias filter without Claude spend."""

        config = request.filter_config or self._default_filter_config
        return filter_niche_top_cards(
            niche_key=request.niche_key,
            marketplace=request.marketplace,
            cards=list(request.cards),
            config=config,
        )

    async def enqueue_audit(
        self,
        *,
        user_id: UUID,
        request: VisualAuditEnqueueRequest,
        idempotency_key: str | None = None,
    ) -> tuple[VisualAuditJobView, bool]:
        """Create a queued audit job; caller publishes Celery task.

        Returns (job, idempotent_replay).
        """

        if idempotency_key:
            existing = await self._repository.find_idempotent_job(
                user_id=user_id,
                idempotency_key=idempotency_key.strip(),
            )
            if existing is not None:
                return existing, True

        if not request.cards:
            raise VisualAuditValidationError("At least one niche card is required.")

        config = request.filter_config or self._default_filter_config
        # Validate classification early so bad payloads fail before queue.
        filter_niche_top_cards(
            niche_key=request.niche_key,
            marketplace=request.marketplace,
            cards=list(request.cards),
            config=config,
        )

        job = await self._repository.create_job(
            user_id=user_id,
            niche_key=request.niche_key.strip(),
            marketplace=request.marketplace.strip().lower(),
            cards_payload=[card.model_dump(mode="json") for card in request.cards],
            filter_config=config.model_dump(mode="json"),
            model_name=self._model_name,
            idempotency_key=idempotency_key.strip() if idempotency_key else None,
        )
        return job, False

    async def attach_celery_task(
        self, *, job_id: UUID, celery_task_id: str
    ) -> VisualAuditJobView:
        return await self._repository.mark_status(
            job_id=job_id,
            status=VisualAuditJobStatus.QUEUED,
            celery_task_id=celery_task_id,
        )

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> VisualAuditJobView:
        job = await self._repository.get_job_for_user(user_id=user_id, job_id=job_id)
        if job is None:
            raise VisualAuditNotFoundError("Visual audit job not found.")
        return job

    async def run_visual_audit(self, *, job_id: UUID) -> VisualAuditJobView:
        """Execute filter → Rising Star Vision → generator config (Celery worker)."""

        job = await self._repository.get_job(job_id=job_id)
        if job is None:
            raise VisualAuditNotFoundError("Visual audit job not found.")
        if job.status == VisualAuditJobStatus.COMPLETED and job.generator_config:
            return job
        if job.status == VisualAuditJobStatus.FAILED:
            raise VisualAuditError(
                job.error_message or "Visual audit job previously failed."
            )

        try:
            await self._repository.mark_status(
                job_id=job_id,
                status=VisualAuditJobStatus.FILTERING,
            )

            job = await self._repository.get_job(job_id=job_id)
            if job is None:
                raise VisualAuditNotFoundError("Visual audit job not found.")

            cards = [
                NicheCardSignal.model_validate(item) for item in job.cards_payload
            ]
            filter_config = VisualAuditFilterConfig.model_validate(job.filter_config)

            report = filter_niche_top_cards(
                niche_key=job.niche_key,
                marketplace=job.marketplace,
                cards=cards,
                config=filter_config,
            )
            report_payload = dump_filter_report(report)
            await self._write_stage_cache(job_id, "filter", report_payload)
            await self._repository.save_filter_report(
                job_id=job_id,
                filter_report=report_payload,
            )

            dissections: list[RisingStarVisionDissection] = []
            total_in = 0
            total_out = 0

            if report.vision_queue:
                await self._repository.mark_status(
                    job_id=job_id,
                    status=VisualAuditJobStatus.VISION_RUNNING,
                )
                vision = self._require_vision()
                for card in report.vision_queue:
                    images = await self._load_images(tuple(card.image_object_keys))
                    if not images:
                        logger.warning(
                            "Rising Star sku=%s has no usable images; skipped",
                            card.sku,
                        )
                        continue
                    dissection, in_tok, out_tok = await vision.dissect_rising_star_visuals(
                        sku=card.sku,
                        title=card.title,
                        product_category=card.product_category,
                        sales_growth_ratio=card.sales_growth_ratio,
                        review_velocity_per_day=card.review_velocity_per_day,
                        review_count=card.review_count,
                        images=images,
                        user_id=job.user_id,
                        job_id=job_id,
                    )
                    # Force SKU integrity even if the model drifts.
                    if dissection.sku != card.sku:
                        dissection = RisingStarVisionDissection(
                            **{
                                **dissection.model_dump(),
                                "sku": card.sku,
                            }
                        )
                    dissections.append(dissection)
                    total_in += in_tok
                    total_out += out_tok

            await self._repository.mark_status(
                job_id=job_id,
                status=VisualAuditJobStatus.AGGREGATING,
            )
            generator_config = build_generator_trigger_config(
                filter_report=report,
                dissections=dissections,
                model_name=job.model_name,
            )
            vision_payload = [item.model_dump(mode="json") for item in dissections]
            config_payload = dump_generator_config(generator_config)
            await self._write_stage_cache(job_id, "vision", {"items": vision_payload})
            await self._write_stage_cache(job_id, "generator", config_payload)

            return await self._repository.save_final_result(
                job_id=job_id,
                vision_dissections=vision_payload,
                generator_config=config_payload,
                input_tokens_delta=total_in,
                output_tokens_delta=total_out,
            )
        except VisualAuditError:
            raise
        except Exception as exc:
            logger.exception("Visual audit failed for job_id=%s", job_id)
            await self._repository.mark_status(
                job_id=job_id,
                status=VisualAuditJobStatus.FAILED,
                error_message=str(exc)[:1000],
                completed_at=datetime.now(UTC),
            )
            raise VisualAuditError(str(exc)) from exc

    async def _load_images(
        self, object_keys: tuple[str, ...]
    ) -> tuple[tuple[bytes, str], ...]:
        loaded: list[tuple[bytes, str]] = []
        for key in object_keys:
            data = await self._storage.download_bytes(
                object_key=key,
                max_bytes=self._max_image_bytes,
            )
            detected = detect_image_mime(data)
            if detected is None:
                logger.warning("Skipping unsupported image object_key=%s", key)
                continue
            mime_type, _ext = detected
            loaded.append((data, mime_type))
        return tuple(loaded)

    async def _write_stage_cache(
        self, job_id: UUID, stage: str, payload: dict[str, Any]
    ) -> None:
        try:
            await cache_json(
                redis_visual_audit_key(job_id, stage),
                payload,
                self._redis_stage_ttl_seconds,
            )
        except RedisUnavailableError:
            logger.warning(
                "Redis unavailable; skipped visual-audit cache job_id=%s stage=%s",
                job_id,
                stage,
            )

    async def _read_stage_cache(
        self, job_id: UUID, stage: str
    ) -> dict[str, Any] | None:
        try:
            return await get_cached_json(redis_visual_audit_key(job_id, stage))
        except RedisUnavailableError:
            return None
