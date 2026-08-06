"""Generation state-machine use cases independent of web and queue frameworks."""

from __future__ import annotations

import asyncio
import io
import logging
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import quote, urlencode
from uuid import UUID

from app.application.ports.image_generation import (
    AsyncImageProviderPort,
    ImmediateImageProviderPort,
)
from app.application.ports.persistence import (
    GenerationRepositoryPort,
    ObjectStoragePort,
)
from app.application.ports.text_generation import MarketplaceTextProviderPort
from app.core.config import get_settings
from app.core.webhook_security import create_reply_ref, verify_reply_ref
from app.domain.generation import (
    GenerationEngineMode,
    GenerationErrorCode,
    GenerationErrorInfo,
    GenerationJobStatus,
    GenerationPostProcessingMode,
    OutboxEventType,
    ProviderWebhookEvent,
    SlideStatus,
    SlideWorkItem,
)
from app.models.enums import SubscriptionStatus
from app.services.ai_engine import (
    AIEngineConfigurationError,
    AIEngineError,
    AIEngineModerationError,
    AIEngineRateLimitError,
    AIEngineUpstreamError,
    AIEngineValidationError,
    get_face_fix_engine,
    note_provider_failure,
    note_provider_success,
)
from app.services.image_optimizer import (
    ImageOptimizationError,
    OptimizedImage,
    create_generation_thumbnail,
    optimize_image_lossless,
)
from app.services.infographic_service import (
    InfographicServiceError,
    get_overlay_service,
)
from app.services.product_compositor import (
    ProductCompositorError,
    composite_product_on_background,
)
from app.services.model_vto import MODEL_VTO_SLIDE_KEY
from app.services.series_generator import (
    DEFAULT_SLIDE_OVERLAY_TEXTS,
    SLIDE_OVERLAY_STYLES,
)

logger = logging.getLogger(__name__)


class GenerationApplicationService:
    """Orchestrate one durable job through submit, webhook, and finalisation."""

    def __init__(
        self,
        *,
        repository: GenerationRepositoryPort,
        storage: ObjectStoragePort,
        async_providers: tuple[AsyncImageProviderPort, ...],
        immediate_provider: ImmediateImageProviderPort,
        text_provider: MarketplaceTextProviderPort | None = None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._async_providers = async_providers
        self._immediate_provider = immediate_provider
        self._text_provider = text_provider
        self._settings = get_settings()

    async def submit_job(self, job_id: UUID) -> None:
        """Submit every slide without ever waiting for an async provider result."""

        work = await self._repository.get_work_item(job_id)
        if work is None or work.status in {
            GenerationJobStatus.COMPLETED,
            GenerationJobStatus.FAILED,
        }:
            return
        await self._repository.set_job_status(
            job_id,
            GenerationJobStatus.SUBMITTING,
            progress=max(
                1, len([slide for slide in work.slides if slide.result_object_key])
            ),
        )
        try:
            product_image = await self._storage.download(
                work.input_object_key,
                max_bytes=self._settings.generation_max_upload_bytes,
            )
            for slide in work.slides:
                if slide.status == SlideStatus.COMPLETED or slide.result_object_key:
                    continue
                await self._submit_or_fallback_slide(
                    job_id=job_id,
                    slide=slide,
                    product_image=product_image,
                    subscription_status=work.subscription_status,
                    engine_mode=work.engine_mode,
                    post_processing_mode=work.post_processing_mode,
                    excluded_providers=await self._repository.get_attempted_providers(
                        slide.id
                    ),
                    apply_text_overlays=work.apply_text_overlays,
                    overlay_texts=work.overlay_texts,
                )
        except Exception as exc:
            await self._fail_job(job_id, exc)
            return

        refreshed = await self._repository.get_work_item(job_id)
        if refreshed is None or refreshed.status == GenerationJobStatus.FAILED:
            return
        if all(slide.status == SlideStatus.COMPLETED for slide in refreshed.slides):
            await self._enqueue_finalize(refreshed.id)
        else:
            await self._repository.set_job_status(
                refreshed.id,
                GenerationJobStatus.WAITING_WEBHOOK,
                progress=max(
                    5,
                    sum(
                        18
                        for slide in refreshed.slides
                        if slide.status == SlideStatus.COMPLETED
                    ),
                ),
            )

    async def process_webhook(self, webhook_event_id: UUID) -> None:
        """Apply one persisted webhook event idempotently."""

        stored = await self._repository.get_webhook_payload(webhook_event_id)
        if stored is None:
            return
        normalized = stored.get("normalized")
        if not isinstance(normalized, dict):
            await self._repository.mark_webhook_processed(webhook_event_id)
            return
        try:
            event = ProviderWebhookEvent.model_validate(normalized)
            await self._handle_provider_event(event)
        except Exception:
            logger.exception("Failed to process webhook event %s", webhook_event_id)
            raise
        else:
            await self._repository.mark_webhook_processed(webhook_event_id)

    async def finalize_job(self, job_id: UUID) -> None:
        """Package completed slides and publish the terminal result."""

        work = await self._repository.get_work_item(job_id)
        if work is None or work.status == GenerationJobStatus.COMPLETED:
            return
        if work.status == GenerationJobStatus.FAILED:
            return
        if not work.slides or any(
            slide.status != SlideStatus.COMPLETED or not slide.result_object_key
            for slide in work.slides
        ):
            return
        await self._repository.set_job_status(
            job_id,
            GenerationJobStatus.PROCESSING,
            progress=92,
        )
        try:
            images = await asyncio.gather(
                *(
                    self._storage.download(
                        slide.result_object_key or "",
                        max_bytes=self._settings.generation_max_result_bytes,
                    )
                    for slide in work.slides
                )
            )
            marketplace_text = (
                await self._text_provider.generate_marketplace_text(
                    product_category=work.product_category,
                    slides=work.slides,
                    images=tuple(images),
                )
                if self._text_provider is not None
                else work.marketplace_text
            )
            zip_bytes = await asyncio.to_thread(
                _build_archive,
                tuple(zip(work.slides, images, strict=True)),
            )
            archive_key = f"generation-results/{work.user_id}/{work.id}/card_series.zip"
            await self._storage.upload(
                object_key=archive_key,
                data=zip_bytes,
                content_type="application/zip",
            )
            thumbnail = await create_generation_thumbnail(images[0])
            thumbnail_key = (
                f"generation-previews/{work.user_id}/{work.id}/"
                f"thumbnail{thumbnail.extension}"
            )
            await self._storage.upload(
                object_key=thumbnail_key,
                data=thumbnail.image_bytes,
                content_type=thumbnail.mime_type,
            )
            providers = sorted(
                {
                    slide.provider_used
                    for slide in work.slides
                    if slide.provider_used is not None
                }
            )
            provider_used = ",".join(providers) or self._immediate_provider.name
            warning = (
                "Midjourney pool was unavailable; one or more slides used Stable Diffusion."
                if self._immediate_provider.name in providers
                and work.subscription_status in SubscriptionStatus.paid_values()
                else None
            )
            await self._repository.complete_job(
                work.id,
                archive_object_key=archive_key,
                thumbnail_object_key=thumbnail_key,
                thumbnail_mime_type=thumbnail.mime_type,
                thumbnail_size_bytes=thumbnail.size_bytes,
                marketplace_text=marketplace_text,
                provider_used=provider_used,
                warning=warning,
            )
        except Exception as exc:
            await self._fail_job(work.id, exc)

    async def recover_stalled(self) -> None:
        """Perform one status request per stale attempt and expire old jobs."""

        now = datetime.now(UTC)
        await self._repository.fail_expired_jobs(now=now, limit=100)
        cutoff = now - timedelta(
            seconds=self._settings.midjourney_callback_timeout_seconds
        )
        attempts = await self._repository.list_stalled_attempts(
            updated_before=cutoff,
            limit=100,
        )
        for attempt in attempts:
            if not attempt.external_job_id:
                continue
            provider = self._provider_by_name(attempt.provider_name)
            if provider is None:
                continue
            try:
                event = await provider.check_once(
                    attempt.external_job_id,
                    reply_ref=attempt.reply_ref,
                )
                if event is not None:
                    await self._handle_provider_event(event)
            except AIEngineError:
                await note_provider_failure(provider.name)
                logger.warning(
                    "Single recovery check failed for provider=%s job=%s",
                    provider.name,
                    attempt.external_job_id,
                    exc_info=True,
                )

    async def _handle_provider_event(self, event: ProviderWebhookEvent) -> None:
        if not verify_reply_ref(event.reply_ref):
            raise AIEngineValidationError("Webhook reply_ref signature is invalid.")
        attempt = await self._repository.get_attempt_by_reply_ref(event.reply_ref)
        if attempt is None:
            # A correctly signed late event may refer to already-retained data.
            return
        work = await self._repository.get_work_item(attempt.job_id)
        if work is None or work.status in {
            GenerationJobStatus.COMPLETED,
            GenerationJobStatus.FAILED,
        }:
            return
        if attempt.abandoned or attempt.slide_status == SlideStatus.COMPLETED:
            return
        provider = self._provider_by_name(attempt.provider_name)
        if provider is None:
            raise AIEngineConfigurationError(
                f"Webhook provider '{attempt.provider_name}' is no longer configured."
            )
        await self._repository.apply_webhook_progress(attempt.id, event)
        if not event.is_terminal_success and not event.is_terminal_failure:
            return
        if event.is_terminal_failure:
            await note_provider_failure(provider.name)
            await self._repository.mark_attempt_failed(
                attempt.id,
                event.error_message or f"Provider ended with status {event.status}.",
                abandoned=True,
            )
            slide = next(
                (item for item in work.slides if item.id == attempt.slide_id), None
            )
            if slide is None:
                return
            product_image = await self._storage.download(
                work.input_object_key,
                max_bytes=self._settings.generation_max_upload_bytes,
            )
            await self._submit_or_fallback_slide(
                job_id=work.id,
                slide=slide,
                product_image=product_image,
                subscription_status=work.subscription_status,
                engine_mode=work.engine_mode,
                post_processing_mode=work.post_processing_mode,
                excluded_providers=await self._repository.get_attempted_providers(
                    slide.id
                ),
                apply_text_overlays=work.apply_text_overlays,
                overlay_texts=work.overlay_texts,
            )
            return
        if event.result_url is None:
            raise AIEngineUpstreamError("Completed provider webhook has no result URL.")

        try:
            generated = await provider.download_result(str(event.result_url))
            product_image = await self._storage.download(
                work.input_object_key,
                max_bytes=self._settings.generation_max_upload_bytes,
            )
            slide = next(
                (item for item in work.slides if item.id == attempt.slide_id), None
            )
            if slide is None:
                return
            optimized = await self._post_process(
                product_image=product_image,
                generated_background=generated,
                slide=slide,
                apply_text_overlays=work.apply_text_overlays,
                overlay_texts=work.overlay_texts,
                post_processing_mode=work.post_processing_mode,
            )
            await self._store_slide(
                job_id=work.id,
                slide=slide,
                provider_name=provider.name,
                image=optimized,
            )
            await note_provider_success(provider.name)
            await self._maybe_enqueue_finalize(work.id)
        except Exception as exc:
            await note_provider_failure(provider.name)
            await self._repository.mark_attempt_failed(
                attempt.id,
                str(exc),
                abandoned=True,
            )
            await self._submit_or_fallback_slide(
                job_id=work.id,
                slide=next(item for item in work.slides if item.id == attempt.slide_id),
                product_image=await self._storage.download(
                    work.input_object_key,
                    max_bytes=self._settings.generation_max_upload_bytes,
                ),
                subscription_status=work.subscription_status,
                engine_mode=work.engine_mode,
                post_processing_mode=work.post_processing_mode,
                excluded_providers=await self._repository.get_attempted_providers(
                    attempt.slide_id
                ),
                apply_text_overlays=work.apply_text_overlays,
                overlay_texts=work.overlay_texts,
            )

    async def _submit_or_fallback_slide(
        self,
        *,
        job_id: UUID,
        slide: SlideWorkItem,
        product_image: bytes,
        subscription_status: str,
        engine_mode: GenerationEngineMode,
        post_processing_mode: GenerationPostProcessingMode,
        excluded_providers: frozenset[str],
        apply_text_overlays: bool,
        overlay_texts: dict[str, str],
    ) -> None:
        requested_midjourney = engine_mode in {
            GenerationEngineMode.STANDARD,
            GenerationEngineMode.PREMIUM,
        }
        callback_base = self._settings.midjourney_callback_base_url.rstrip("/")
        if requested_midjourney and callback_base:
            for provider in self._async_providers:
                if provider.name in excluded_providers:
                    continue
                attempt = None
                try:
                    reply_ref = create_reply_ref(
                        job_id=job_id,
                        slide_id=slide.id,
                        provider_name=provider.name,
                    )
                    attempt = await self._repository.begin_attempt(
                        slide_id=slide.id,
                        provider_name=provider.name,
                        reply_ref=reply_ref,
                    )
                    token = getattr(provider, "callback_token", "")
                    query = f"?{urlencode({'token': token})}" if token else ""
                    callback_url = (
                        f"{callback_base}/api/v1/webhooks/midjourney/"
                        f"{quote(provider.name, safe='')}{query}"
                    )
                    submission = await provider.submit(
                        product_image=product_image,
                        selected_style=slide.selected_style,
                        prompt=slide.prompt,
                        reply_url=callback_url,
                        reply_ref=reply_ref,
                        render_mode=_render_mode_for_slide(slide),
                        engine_mode=engine_mode,
                    )
                    await self._repository.mark_attempt_submitted(
                        attempt.id, submission
                    )
                    await note_provider_success(provider.name)
                    return
                except Exception as exc:
                    await note_provider_failure(provider.name)
                    if attempt is not None:
                        await self._repository.mark_attempt_failed(
                            attempt.id,
                            str(exc),
                            abandoned=True,
                        )
                    logger.warning(
                        "Provider submit failed provider=%s slide=%s",
                        provider.name,
                        slide.id,
                        exc_info=True,
                    )

        warning = (
            "Midjourney pool unavailable; generated with Stable Diffusion."
            if requested_midjourney
            else None
        )
        try:
            generated = await self._immediate_provider.generate(
                product_image=product_image,
                selected_style=slide.selected_style,
                prompt=slide.prompt,
            )
            optimized = await self._post_process(
                product_image=product_image,
                generated_background=generated,
                slide=slide,
                apply_text_overlays=apply_text_overlays,
                overlay_texts=overlay_texts,
                post_processing_mode=post_processing_mode,
            )
            await self._store_slide(
                job_id=job_id,
                slide=slide,
                provider_name=self._immediate_provider.name,
                image=optimized,
                warning=warning,
            )
            await self._maybe_enqueue_finalize(job_id)
        except Exception as exc:
            await self._fail_job(job_id, exc)

    async def _post_process(
        self,
        *,
        product_image: bytes,
        generated_background: bytes,
        slide: SlideWorkItem,
        apply_text_overlays: bool,
        overlay_texts: dict[str, str],
        post_processing_mode: GenerationPostProcessingMode,
    ) -> OptimizedImage:
        if _is_model_vto_slide(slide):
            final_model_bytes = await _apply_face_fix_if_requested(
                generated_background,
                post_processing_mode=post_processing_mode,
            )
            return await optimize_image_lossless(final_model_bytes)

        composited = await composite_product_on_background(
            product_image=product_image,
            background_image=generated_background,
        )
        final_bytes = composited.image_bytes
        if self._settings.smart_inpainting_edge_pass_enabled:
            inpaint_edges = getattr(self._immediate_provider, "inpaint_edges", None)
            if callable(inpaint_edges):
                try:
                    final_bytes = await inpaint_edges(
                        composited_image=composited.image_bytes,
                        edge_mask=composited.edge_mask_bytes,
                        prompt=slide.prompt,
                    )
                except AIEngineError:
                    # Local mask/shadow composition is already a complete,
                    # deterministic result. The optional neural edge pass may
                    # degrade gracefully without failing the whole job.
                    logger.warning(
                        "Optional edge inpainting failed for slide %s",
                        slide.id,
                        exc_info=True,
                    )
        if apply_text_overlays:
            text = overlay_texts.get(
                slide.slide_key
            ) or DEFAULT_SLIDE_OVERLAY_TEXTS.get(
                slide.slide_key,
                "AI-Card-Master",
            )
            style = SLIDE_OVERLAY_STYLES.get(slide.slide_key, "Bold")
            final_bytes = await get_overlay_service().overlay_text_on_image(
                product_image=final_bytes,
                text=text,
                style_name=style,
            )
        final_bytes = await _apply_face_fix_if_requested(
            final_bytes,
            post_processing_mode=post_processing_mode,
        )
        return await optimize_image_lossless(final_bytes)

    async def _store_slide(
        self,
        *,
        job_id: UUID,
        slide: SlideWorkItem,
        provider_name: str,
        image: OptimizedImage,
        warning: str | None = None,
    ) -> None:
        object_key = (
            f"generation-results/{job_id}/slides/"
            f"{slide.position:02d}_{slide.slide_key}{image.extension}"
        )
        await self._storage.upload(
            object_key=object_key,
            data=image.image_bytes,
            content_type=image.mime_type,
        )
        await self._repository.set_slide_result(
            slide_id=slide.id,
            provider_name=provider_name,
            object_key=object_key,
            mime_type=image.mime_type,
            warning=warning,
        )

    async def _maybe_enqueue_finalize(self, job_id: UUID) -> None:
        refreshed = await self._repository.get_work_item(job_id)
        if refreshed is not None and all(
            slide.status == SlideStatus.COMPLETED for slide in refreshed.slides
        ):
            await self._enqueue_finalize(job_id)

    async def _enqueue_finalize(self, job_id: UUID) -> None:
        await self._repository.add_outbox(
            event_type=OutboxEventType.FINALIZE_JOB,
            aggregate_id=job_id,
            deduplication_key=f"finalize-job:{job_id}",
            payload={"job_id": str(job_id)},
        )

    async def _fail_job(self, job_id: UUID, exc: Exception) -> None:
        error = _normalise_error(exc)
        logger.error(
            "Generation job %s failed code=%s retryable=%s",
            job_id,
            error.code,
            error.retryable,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        await self._repository.fail_job(job_id, error)

    def _provider_by_name(self, name: str) -> AsyncImageProviderPort | None:
        return next(
            (provider for provider in self._async_providers if provider.name == name),
            None,
        )


async def _apply_face_fix_if_requested(
    image_bytes: bytes,
    *,
    post_processing_mode: GenerationPostProcessingMode,
) -> bytes:
    if post_processing_mode != GenerationPostProcessingMode.HD_FACE_FIX:
        return image_bytes
    return await get_face_fix_engine().fix_if_needed(image_bytes)


def _normalise_error(exc: Exception) -> GenerationErrorInfo:
    if isinstance(exc, AIEngineValidationError):
        code, retryable = GenerationErrorCode.VALIDATION, False
        message = "The generation input or provider response was invalid."
    elif isinstance(exc, AIEngineConfigurationError):
        code, retryable = GenerationErrorCode.CONFIGURATION, True
        message = "No image generation provider is currently configured."
    elif isinstance(exc, AIEngineRateLimitError):
        code, retryable = GenerationErrorCode.RATE_LIMIT, True
        message = "All image providers are currently rate limited. Please retry later."
    elif isinstance(exc, AIEngineModerationError):
        code, retryable = GenerationErrorCode.MODERATION, False
        message = "The request was rejected by the image provider content policy."
    elif isinstance(exc, AIEngineUpstreamError):
        code, retryable = GenerationErrorCode.TRANSIENT, True
        message = "Image providers are temporarily unavailable. Please retry later."
    elif isinstance(exc, (ProductCompositorError, ImageOptimizationError)):
        code, retryable = GenerationErrorCode.PERMANENT, False
        message = "The generated image could not be processed safely."
    elif isinstance(exc, InfographicServiceError):
        code, retryable = GenerationErrorCode.PERMANENT, False
        message = "The text overlay could not be rendered."
    else:
        code, retryable = GenerationErrorCode.INTERNAL, True
        message = "Generation failed due to an internal processing error."
    return GenerationErrorInfo(
        code=code,
        message=message,
        retryable=retryable,
        attempts=0,
    )


def _is_model_vto_slide(slide: SlideWorkItem) -> bool:
    return slide.slide_key == MODEL_VTO_SLIDE_KEY


def _render_mode_for_slide(
    slide: SlideWorkItem,
) -> Literal["background_plate", "direct_vto"]:
    return "direct_vto" if _is_model_vto_slide(slide) else "background_plate"


def _build_archive(items: tuple[tuple[SlideWorkItem, bytes], ...]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for slide, image_bytes in items:
            extension = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/webp": ".webp",
            }.get(slide.result_mime_type or "", ".bin")
            archive.writestr(
                f"{slide.position:02d}_{slide.slide_key}{extension}",
                image_bytes,
            )
    return buffer.getvalue()
