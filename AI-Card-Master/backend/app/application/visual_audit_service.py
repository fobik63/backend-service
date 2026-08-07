"""Use cases for intelligent niche visual audit (Brand Dominant filter → Rising Stars)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from app.application.ports.claude_reasoning import ClaudeStageCachePort
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
from app.infrastructure.http_resilience import gather_bounded

logger = logging.getLogger(__name__)

# Cap concurrent Claude Vision calls — stability over raw throughput.
_VISION_CONCURRENCY = 2
_S3_CONCURRENCY = 4


class _NullStageCache:
    async def get(self, key: str) -> dict[str, Any] | None:
        return None

    async def set(self, key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        return None


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
        stage_cache: ClaudeStageCachePort | None = None,
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
        self._stage_cache = stage_cache or _NullStageCache()

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
        """Execute filter → Rising Star Vision → generator config (Celery worker).

        Prompt-efficiency shape (≤3 DB passes):
        1) claim FILTERING (returns hydrated job — no re-get)
        2) filter checkpoint (+ VISION_RUNNING when queue non-empty)
        3) save_final_result (COMPLETED) or FAILED on outer except
        External I/O: bounded S3 gather + bounded Claude Vision gather.
        """

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
            # Pass 1: claim work; mark_status returns full view (payload intact).
            job = await self._repository.mark_status(
                job_id=job_id,
                status=VisualAuditJobStatus.FILTERING,
            )

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

            # Pass 2: filter report + next status in one write.
            next_status = (
                VisualAuditJobStatus.VISION_RUNNING
                if report.vision_queue
                else VisualAuditJobStatus.AGGREGATING
            )
            await self._repository.save_filter_checkpoint(
                job_id=job_id,
                filter_report=report_payload,
                next_status=next_status,
            )

            dissections: list[RisingStarVisionDissection] = []
            total_in = 0
            total_out = 0

            if report.vision_queue:
                vision = self._require_vision()
                vision_results = await gather_bounded(
                    tuple(report.vision_queue),
                    lambda card: self._dissect_one_card(
                        vision=vision,
                        card=card,
                        user_id=job.user_id,
                        job_id=job_id,
                    ),
                    limit=_VISION_CONCURRENCY,
                    return_exceptions=True,
                )
                for card, result in zip(
                    report.vision_queue, vision_results, strict=True
                ):
                    if isinstance(result, BaseException):
                        logger.warning(
                            "Rising Star sku=%s vision failed: %s",
                            card.sku,
                            result,
                            exc_info=result,
                        )
                        continue
                    if result is None:
                        continue
                    dissection, in_tok, out_tok = result
                    dissections.append(dissection)
                    total_in += in_tok
                    total_out += out_tok

            generator_config = build_generator_trigger_config(
                filter_report=report,
                dissections=dissections,
                model_name=job.model_name,
            )
            vision_payload = [item.model_dump(mode="json") for item in dissections]
            config_payload = dump_generator_config(generator_config)
            await self._write_stage_cache(job_id, "vision", {"items": vision_payload})
            await self._write_stage_cache(job_id, "generator", config_payload)

            # Pass 3: final persist.
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

    async def _dissect_one_card(
        self,
        *,
        vision: RisingStarVisionPort,
        card: NicheCardSignal,
        user_id: UUID,
        job_id: UUID,
    ) -> tuple[RisingStarVisionDissection, int, int] | None:
        images = await self._load_images(tuple(card.image_object_keys))
        if not images:
            logger.warning(
                "Rising Star sku=%s has no usable images; skipped",
                card.sku,
            )
            return None
        dissection, in_tok, out_tok = await vision.dissect_rising_star_visuals(
            sku=card.sku,
            title=card.title,
            product_category=card.product_category,
            sales_growth_ratio=card.sales_growth_ratio,
            review_velocity_per_day=card.review_velocity_per_day,
            review_count=card.review_count,
            images=images,
            user_id=user_id,
            job_id=job_id,
        )
        if dissection.sku != card.sku:
            dissection = RisingStarVisionDissection(
                **{
                    **dissection.model_dump(),
                    "sku": card.sku,
                }
            )
        return dissection, in_tok, out_tok

    async def _load_images(
        self, object_keys: tuple[str, ...]
    ) -> tuple[tuple[bytes, str], ...]:
        if not object_keys:
            return ()

        async def _one(key: str) -> tuple[bytes, str] | None:
            try:
                data = await self._storage.download_bytes(
                    object_key=key,
                    max_bytes=self._max_image_bytes,
                )
            except Exception:
                logger.warning(
                    "Failed to download image object_key=%s",
                    key,
                    exc_info=True,
                )
                return None
            detected = detect_image_mime(data)
            if detected is None:
                logger.warning("Skipping unsupported image object_key=%s", key)
                return None
            mime_type, _ext = detected
            return data, mime_type

        results = await gather_bounded(
            object_keys,
            _one,
            limit=_S3_CONCURRENCY,
            return_exceptions=True,
        )
        loaded: list[tuple[bytes, str]] = []
        for key, result in zip(object_keys, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning(
                    "Skipping image object_key=%s due to error: %s",
                    key,
                    result,
                )
                continue
            if result is not None:
                loaded.append(result)
        return tuple(loaded)

    async def _write_stage_cache(
        self, job_id: UUID, stage: str, payload: dict[str, Any]
    ) -> None:
        try:
            await self._stage_cache.set(
                redis_visual_audit_key(job_id, stage),
                payload,
                self._redis_stage_ttl_seconds,
            )
        except Exception:
            logger.warning(
                "Skipped visual-audit cache job_id=%s stage=%s",
                job_id,
                stage,
                exc_info=True,
            )

    async def _read_stage_cache(
        self, job_id: UUID, stage: str
    ) -> dict[str, Any] | None:
        try:
            return await self._stage_cache.get(redis_visual_audit_key(job_id, stage))
        except Exception:
            return None
