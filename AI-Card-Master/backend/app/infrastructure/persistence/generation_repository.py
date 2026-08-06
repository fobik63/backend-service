"""SQLAlchemy adapter for the durable generation aggregate."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.domain.generation import (
    AttemptWorkItem,
    GenerationEngineMode,
    GenerationErrorInfo,
    GenerationJobStatus,
    GenerationPostProcessingMode,
    GenerationWorkItem,
    MarketplaceTextContent,
    OutboxEventType,
    OutboxMessage,
    ProviderSubmission,
    ProviderWebhookEvent,
    SlideStatus,
    SlideWorkItem,
)
from app.models.generation_error_log import GenerationErrorLog
from app.models.generation_job import (
    GenerationJob,
    GenerationOutbox,
    GenerationProviderAttempt,
    GenerationSlide,
    GenerationWebhookEvent,
)
from app.models.api_usage_cost import ApiUsageCost
from app.models.user import User
from app.services.billing_service import BillingValidationError
from app.services.series_generator import SeriesTask


class GenerationRepository:
    """Persistence adapter; each mutating operation commits its own transition."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_idempotent_job(
        self,
        *,
        user_id: UUID,
        idempotency_key: str | None,
    ) -> GenerationJob | None:
        """Resolve an existing create request before uploading another input."""

        if not idempotency_key:
            return None
        return await self._session.scalar(
            select(GenerationJob).where(
                GenerationJob.user_id == user_id,
                GenerationJob.idempotency_key == idempotency_key,
            )
        )

    async def create_job(
        self,
        *,
        user_id: UUID,
        idempotency_key: str | None,
        subscription_status: str,
        engine_mode: GenerationEngineMode,
        post_processing_mode: GenerationPostProcessingMode,
        input_object_key: str,
        product_category: str | None,
        apply_text_overlays: bool,
        overlay_texts: Mapping[str, str],
        slide_tasks: Sequence[SeriesTask],
    ) -> tuple[GenerationJob, bool]:
        """Atomically debit, create the aggregate, and add its outbox command."""

        if idempotency_key:
            existing = await self._session.scalar(
                select(GenerationJob).where(
                    GenerationJob.user_id == user_id,
                    GenerationJob.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return existing, False

        settings = get_settings()
        generation_cost = _generation_cost_for_mode(post_processing_mode)
        try:
            user = await self._session.get(User, user_id, with_for_update=True)
            if user is None:
                raise LookupError("Generation user was not found.")
            if settings.generation_charge_coins:
                if user.ai_coins < generation_cost:
                    raise BillingValidationError("Insufficient AI-coin balance.")
                user.ai_coins -= generation_cost

            now = datetime.now(UTC)
            job = GenerationJob(
                user_id=user_id,
                idempotency_key=idempotency_key,
                status=GenerationJobStatus.QUEUED.value,
                progress=0,
                product_category=product_category,
                subscription_status=subscription_status,
                engine_mode=engine_mode.value,
                post_processing_mode=post_processing_mode.value,
                input_object_key=input_object_key,
                apply_text_overlays=apply_text_overlays,
                overlay_texts=dict(overlay_texts) or None,
                coin_charged=settings.generation_charge_coins,
                coins_charged=generation_cost if settings.generation_charge_coins else 0,
                deadline_at=now
                + timedelta(seconds=settings.generation_job_timeout_seconds),
            )
            self._session.add(job)
            await self._session.flush()

            for position, task in enumerate(slide_tasks, start=1):
                self._session.add(
                    GenerationSlide(
                        job_id=job.id,
                        slide_key=task.slide_key,
                        position=position,
                        status=SlideStatus.QUEUED.value,
                        progress=0,
                        selected_style=task.selected_style,
                        prompt_used=task.user_text,
                    )
                )

            self._session.add(
                GenerationOutbox(
                    event_type=OutboxEventType.SUBMIT_JOB.value,
                    aggregate_id=job.id,
                    deduplication_key=f"submit-job:{job.id}",
                    payload={"job_id": str(job.id)},
                )
            )
            await self._session.commit()
            await self._session.refresh(job)
            return job, True
        except IntegrityError:
            await self._session.rollback()
            if idempotency_key:
                existing = await self._session.scalar(
                    select(GenerationJob).where(
                        GenerationJob.user_id == user_id,
                        GenerationJob.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    return existing, False
            raise
        except Exception:
            await self._session.rollback()
            raise

    async def get_job_for_user(
        self, job_id: UUID, user_id: UUID
    ) -> GenerationJob | None:
        """Load a job and slides while enforcing ownership."""

        return await self._session.scalar(
            select(GenerationJob)
            .where(GenerationJob.id == job_id, GenerationJob.user_id == user_id)
            .options(selectinload(GenerationJob.slides))
        )

    async def list_generation_history_for_user(
        self,
        *,
        user_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[GenerationJob, ...]:
        """Return newest generations for the personal cabinet history."""

        jobs = await self._session.scalars(
            select(GenerationJob)
            .where(GenerationJob.user_id == user_id)
            .order_by(GenerationJob.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return tuple(jobs)

    async def get_work_item(self, job_id: UUID) -> GenerationWorkItem | None:
        job = await self._session.scalar(
            select(GenerationJob)
            .where(GenerationJob.id == job_id)
            .options(
                selectinload(GenerationJob.slides).selectinload(
                    GenerationSlide.attempts
                )
            )
        )
        if job is None:
            return None
        return GenerationWorkItem(
            id=job.id,
            user_id=job.user_id,
            status=GenerationJobStatus(job.status),
            input_object_key=job.input_object_key,
            product_category=job.product_category,
            subscription_status=job.subscription_status,
            engine_mode=GenerationEngineMode(job.engine_mode),
            post_processing_mode=GenerationPostProcessingMode(job.post_processing_mode),
            apply_text_overlays=job.apply_text_overlays,
            overlay_texts=dict(job.overlay_texts or {}),
            marketplace_text=(
                MarketplaceTextContent.model_validate(job.marketplace_text)
                if job.marketplace_text
                else None
            ),
            slides=tuple(
                SlideWorkItem(
                    id=slide.id,
                    slide_key=slide.slide_key,
                    position=slide.position,
                    status=SlideStatus(slide.status),
                    selected_style=slide.selected_style,
                    prompt=slide.prompt_used,
                    provider_used=slide.provider_used,
                    result_object_key=slide.result_object_key,
                    result_mime_type=slide.result_mime_type,
                    attempts=len(slide.attempts),
                )
                for slide in job.slides
            ),
        )

    async def set_job_status(
        self,
        job_id: UUID,
        status: GenerationJobStatus,
        *,
        progress: int | None = None,
        provider_used: str | None = None,
        warning: str | None = None,
    ) -> None:
        job = await self._session.get(GenerationJob, job_id, with_for_update=True)
        if job is None:
            return
        job.status = status.value
        if progress is not None:
            job.progress = max(job.progress, max(0, min(progress, 100)))
        if provider_used is not None:
            job.provider_used = provider_used
        if warning is not None:
            job.warning = warning[:500]
        job.heartbeat_at = datetime.now(UTC)
        await self._session.commit()

    async def begin_attempt(
        self,
        *,
        slide_id: UUID,
        provider_name: str,
        reply_ref: str,
    ) -> AttemptWorkItem:
        slide = await self._session.scalar(
            select(GenerationSlide)
            .where(GenerationSlide.id == slide_id)
            .options(selectinload(GenerationSlide.attempts))
            .with_for_update()
        )
        if slide is None:
            raise LookupError("Generation slide was not found.")
        attempt = GenerationProviderAttempt(
            slide_id=slide.id,
            provider_name=provider_name,
            attempt_number=len(slide.attempts) + 1,
            reply_ref=reply_ref,
            status="submitting",
        )
        slide.status = SlideStatus.SUBMITTING.value
        slide.provider_used = provider_name
        self._session.add(attempt)
        await self._session.commit()
        await self._session.refresh(attempt)
        return self._attempt_to_work_item(attempt, slide)

    async def mark_attempt_submitted(
        self,
        attempt_id: UUID,
        submission: ProviderSubmission,
    ) -> None:
        attempt = await self._session.get(
            GenerationProviderAttempt,
            attempt_id,
            with_for_update=True,
        )
        if attempt is None:
            return
        attempt.external_job_id = submission.external_job_id
        attempt.status = submission.initial_status
        slide = await self._session.get(GenerationSlide, attempt.slide_id)
        if slide is not None:
            slide.status = SlideStatus.WAITING_WEBHOOK.value
            slide.progress = max(slide.progress, 5)
            await self._record_midjourney_cost(
                slide=slide,
                provider_name=submission.provider,
                external_job_id=submission.external_job_id,
            )
        await self._session.commit()

    async def mark_attempt_failed(
        self,
        attempt_id: UUID,
        message: str,
        *,
        abandoned: bool,
    ) -> None:
        attempt = await self._session.get(
            GenerationProviderAttempt,
            attempt_id,
            with_for_update=True,
        )
        if attempt is None:
            return
        attempt.status = "failed"
        attempt.error_message = message[:2000]
        attempt.abandoned = abandoned
        attempt.completed_at = datetime.now(UTC)
        await self._session.commit()

    async def get_attempt_by_reply_ref(self, reply_ref: str) -> AttemptWorkItem | None:
        row = await self._session.execute(
            select(GenerationProviderAttempt, GenerationSlide)
            .join(
                GenerationSlide,
                GenerationProviderAttempt.slide_id == GenerationSlide.id,
            )
            .where(GenerationProviderAttempt.reply_ref == reply_ref)
        )
        pair = row.first()
        if pair is None:
            return None
        attempt, slide = pair
        return self._attempt_to_work_item(attempt, slide)

    async def get_attempted_providers(self, slide_id: UUID) -> frozenset[str]:
        providers = await self._session.scalars(
            select(GenerationProviderAttempt.provider_name).where(
                GenerationProviderAttempt.slide_id == slide_id
            )
        )
        return frozenset(providers)

    async def list_stalled_attempts(
        self,
        *,
        updated_before: datetime,
        limit: int,
    ) -> tuple[AttemptWorkItem, ...]:
        rows = await self._session.execute(
            select(GenerationProviderAttempt, GenerationSlide)
            .join(
                GenerationSlide,
                GenerationProviderAttempt.slide_id == GenerationSlide.id,
            )
            .join(GenerationJob, GenerationSlide.job_id == GenerationJob.id)
            .where(
                GenerationProviderAttempt.abandoned.is_(False),
                GenerationProviderAttempt.completed_at.is_(None),
                GenerationProviderAttempt.updated_at < updated_before,
                GenerationSlide.status == SlideStatus.WAITING_WEBHOOK.value,
                GenerationJob.status.in_(
                    (
                        GenerationJobStatus.SUBMITTING.value,
                        GenerationJobStatus.WAITING_WEBHOOK.value,
                        GenerationJobStatus.PROCESSING.value,
                    )
                ),
            )
            .order_by(GenerationProviderAttempt.updated_at)
            .limit(limit)
        )
        return tuple(
            self._attempt_to_work_item(attempt, slide) for attempt, slide in rows.all()
        )

    async def fail_expired_jobs(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[UUID, ...]:
        jobs = list(
            await self._session.scalars(
                select(GenerationJob)
                .where(
                    GenerationJob.deadline_at.is_not(None),
                    GenerationJob.deadline_at < now,
                    GenerationJob.status.in_(
                        (
                            GenerationJobStatus.QUEUED.value,
                            GenerationJobStatus.SUBMITTING.value,
                            GenerationJobStatus.WAITING_WEBHOOK.value,
                            GenerationJobStatus.PROCESSING.value,
                        )
                    ),
                )
                .order_by(GenerationJob.deadline_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for job in jobs:
            job.status = GenerationJobStatus.FAILED.value
            job.error_code = "provider_temporarily_unavailable"
            job.error_message = "Generation timed out before all providers completed."
            job.error_retryable = True
            job.completed_at = now
            unfinished = await self._session.scalars(
                select(GenerationSlide).where(
                    GenerationSlide.job_id == job.id,
                    GenerationSlide.status != SlideStatus.COMPLETED.value,
                )
            )
            for slide in unfinished:
                slide.status = SlideStatus.FAILED.value
                slide.error_code = job.error_code
                slide.error_message = job.error_message
                slide.error_retryable = True
                slide.completed_at = now
            self._session.add(
                GenerationErrorLog(
                    user_id=job.user_id,
                    source="generation_recovery",
                    error_message=job.error_message,
                    context={
                        "job_id": str(job.id),
                        "error_code": job.error_code,
                        "retryable": True,
                    },
                )
            )
            await self._refund_locked_job(job)
        await self._session.commit()
        return tuple(job.id for job in jobs)

    async def apply_webhook_progress(
        self,
        attempt_id: UUID,
        event: ProviderWebhookEvent,
    ) -> None:
        attempt = await self._session.get(
            GenerationProviderAttempt,
            attempt_id,
            with_for_update=True,
        )
        if attempt is None:
            return
        attempt.status = event.status
        attempt.progress = max(attempt.progress, event.progress)
        attempt.result_url = (
            str(event.result_url) if event.result_url is not None else None
        )
        attempt.error_message = event.error_message
        if event.is_terminal_success or event.is_terminal_failure:
            attempt.completed_at = datetime.now(UTC)
        slide = await self._session.get(GenerationSlide, attempt.slide_id)
        if slide is not None and not attempt.abandoned:
            slide.progress = max(slide.progress, event.progress)
            if event.is_terminal_success:
                slide.status = SlideStatus.PROCESSING.value
            elif event.is_terminal_failure:
                slide.status = SlideStatus.QUEUED.value
            else:
                slide.status = SlideStatus.WAITING_WEBHOOK.value
        await self._session.commit()

    async def set_slide_result(
        self,
        *,
        slide_id: UUID,
        provider_name: str,
        object_key: str,
        mime_type: str,
        warning: str | None = None,
    ) -> None:
        slide = await self._session.get(GenerationSlide, slide_id, with_for_update=True)
        if slide is None:
            raise LookupError("Generation slide was not found.")
        slide.status = SlideStatus.COMPLETED.value
        slide.progress = 100
        slide.provider_used = provider_name
        slide.result_object_key = object_key
        slide.result_mime_type = mime_type
        slide.warning = warning[:500] if warning else None
        slide.error_code = None
        slide.error_message = None
        slide.completed_at = datetime.now(UTC)

        completed = (
            int(
                await self._session.scalar(
                    select(func.count(GenerationSlide.id)).where(
                        GenerationSlide.job_id == slide.job_id,
                        GenerationSlide.status == SlideStatus.COMPLETED.value,
                        GenerationSlide.id != slide.id,
                    )
                )
                or 0
            )
            + 1
        )
        job = await self._session.get(GenerationJob, slide.job_id, with_for_update=True)
        if job is not None:
            job.progress = min(90, completed * 18)
            job.status = GenerationJobStatus.PROCESSING.value
            job.heartbeat_at = datetime.now(UTC)
        await self._session.commit()

    async def fail_job(self, job_id: UUID, error: GenerationErrorInfo) -> None:
        job = await self._session.get(GenerationJob, job_id, with_for_update=True)
        if job is None or job.status == GenerationJobStatus.COMPLETED.value:
            return
        job.status = GenerationJobStatus.FAILED.value
        job.error_code = error.code.value
        job.error_message = error.message[:2000]
        job.error_retryable = error.retryable
        job.completed_at = datetime.now(UTC)
        unfinished_slides = await self._session.scalars(
            select(GenerationSlide).where(
                GenerationSlide.job_id == job.id,
                GenerationSlide.status != SlideStatus.COMPLETED.value,
            )
        )
        for slide in unfinished_slides:
            slide.status = SlideStatus.FAILED.value
            slide.error_code = error.code.value
            slide.error_message = error.message[:2000]
            slide.error_retryable = error.retryable
            slide.completed_at = datetime.now(UTC)
        self._session.add(
            GenerationErrorLog(
                user_id=job.user_id,
                source="generation_pipeline",
                error_message=error.message,
                context={
                    "job_id": str(job.id),
                    "error_code": error.code.value,
                    "retryable": error.retryable,
                    "attempts": error.attempts,
                },
            )
        )
        await self._refund_locked_job(job)
        await self._session.commit()

    async def complete_job(
        self,
        job_id: UUID,
        *,
        archive_object_key: str,
        thumbnail_object_key: str,
        thumbnail_mime_type: str,
        thumbnail_size_bytes: int,
        marketplace_text: MarketplaceTextContent | None,
        provider_used: str,
        warning: str | None,
    ) -> None:
        job = await self._session.get(GenerationJob, job_id, with_for_update=True)
        if job is None:
            return
        job.status = GenerationJobStatus.COMPLETED.value
        job.progress = 100
        job.archive_object_key = archive_object_key
        job.thumbnail_object_key = thumbnail_object_key
        job.thumbnail_mime_type = thumbnail_mime_type
        job.thumbnail_size_bytes = thumbnail_size_bytes
        job.marketplace_text = (
            marketplace_text.model_dump(mode="json") if marketplace_text else None
        )
        job.provider_used = provider_used
        job.warning = warning[:500] if warning else None
        job.error_code = None
        job.error_message = None
        job.error_retryable = False
        job.completed_at = datetime.now(UTC)
        await self._session.commit()

    async def add_outbox(
        self,
        *,
        event_type: OutboxEventType,
        aggregate_id: UUID,
        deduplication_key: str,
        payload: Mapping[str, object],
    ) -> None:
        existing = await self._session.scalar(
            select(GenerationOutbox.id).where(
                GenerationOutbox.deduplication_key == deduplication_key
            )
        )
        if existing is not None:
            return
        self._session.add(
            GenerationOutbox(
                event_type=event_type.value,
                aggregate_id=aggregate_id,
                deduplication_key=deduplication_key,
                payload=dict(payload),
            )
        )
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()

    async def claim_outbox(self, *, limit: int) -> tuple[OutboxMessage, ...]:
        now = datetime.now(UTC)
        stale_lock = now - timedelta(minutes=5)
        result = await self._session.scalars(
            select(GenerationOutbox)
            .where(
                GenerationOutbox.available_at <= now,
                or_(
                    GenerationOutbox.status == "pending",
                    (
                        (GenerationOutbox.status == "publishing")
                        & (GenerationOutbox.locked_at < stale_lock)
                    ),
                ),
            )
            .order_by(GenerationOutbox.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        messages = list(result)
        for message in messages:
            message.status = "publishing"
            message.locked_at = now
            message.attempts += 1
        await self._session.commit()
        return tuple(
            OutboxMessage(
                id=message.id,
                event_type=OutboxEventType(message.event_type),
                aggregate_id=message.aggregate_id,
                payload=dict(message.payload),
            )
            for message in messages
        )

    async def mark_outbox_published(self, message_id: UUID) -> None:
        message = await self._session.get(GenerationOutbox, message_id)
        if message is None:
            return
        message.status = "published"
        message.processed_at = datetime.now(UTC)
        message.last_error = None
        await self._session.commit()

    async def mark_outbox_failed(self, message_id: UUID, error: str) -> None:
        message = await self._session.get(GenerationOutbox, message_id)
        if message is None:
            return
        message.status = "failed" if message.attempts >= 20 else "pending"
        message.last_error = error[:2000]
        message.locked_at = None
        message.available_at = datetime.now(UTC) + timedelta(
            seconds=min(2 ** min(message.attempts, 8), 300)
        )
        await self._session.commit()

    async def store_webhook_event(
        self,
        *,
        event: ProviderWebhookEvent,
        payload_hash: str,
        raw_payload: Mapping[str, Any],
    ) -> tuple[GenerationWebhookEvent, bool]:
        existing = await self._session.scalar(
            select(GenerationWebhookEvent).where(
                GenerationWebhookEvent.provider_name == event.provider,
                GenerationWebhookEvent.event_id == event.event_id,
            )
        )
        if existing is not None:
            return existing, True
        webhook = GenerationWebhookEvent(
            provider_name=event.provider,
            event_id=event.event_id,
            payload_hash=payload_hash,
            raw_payload={
                "normalized": event.model_dump(mode="json"),
                "provider_payload": dict(raw_payload),
            },
        )
        self._session.add(webhook)
        try:
            await self._session.flush()
            self._session.add(
                GenerationOutbox(
                    event_type=OutboxEventType.PROCESS_WEBHOOK.value,
                    aggregate_id=webhook.id,
                    deduplication_key=f"webhook:{event.provider}:{event.event_id}",
                    payload={"webhook_event_id": str(webhook.id)},
                )
            )
            await self._session.commit()
            await self._session.refresh(webhook)
            return webhook, False
        except IntegrityError:
            await self._session.rollback()
            existing = await self._session.scalar(
                select(GenerationWebhookEvent).where(
                    GenerationWebhookEvent.provider_name == event.provider,
                    GenerationWebhookEvent.event_id == event.event_id,
                )
            )
            if existing is None:
                raise
            return existing, True

    async def get_webhook_payload(
        self, webhook_event_id: UUID
    ) -> dict[str, object] | None:
        webhook = await self._session.get(GenerationWebhookEvent, webhook_event_id)
        if webhook is None:
            return None
        return dict(webhook.raw_payload)

    async def mark_webhook_processed(self, webhook_event_id: UUID) -> None:
        webhook = await self._session.get(GenerationWebhookEvent, webhook_event_id)
        if webhook is None:
            return
        webhook.processed = True
        webhook.processed_at = datetime.now(UTC)
        await self._session.commit()

    async def refund_coin_once(self, job_id: UUID) -> None:
        job = await self._session.get(GenerationJob, job_id, with_for_update=True)
        if job is None:
            return
        await self._refund_locked_job(job)
        await self._session.commit()

    async def _refund_locked_job(self, job: GenerationJob) -> None:
        if not job.coin_charged or job.coin_refunded:
            return
        user = await self._session.get(User, job.user_id, with_for_update=True)
        if user is None:
            return
        refund_amount = int(job.coins_charged or 1)
        user.ai_coins += refund_amount
        job.coin_refunded = True

    async def _record_midjourney_cost(
        self,
        *,
        slide: GenerationSlide,
        provider_name: str,
        external_job_id: str,
    ) -> None:
        normalized_provider = provider_name.strip().lower()
        if normalized_provider == "stable_diffusion":
            return

        job = await self._session.get(GenerationJob, slide.job_id)
        if job is None:
            return

        unit_cost = Decimal(str(get_settings().midjourney_generation_cost_usd))
        self._session.add(
            ApiUsageCost(
                user_id=job.user_id,
                generation_job_id=job.id,
                provider="midjourney",
                model_name=provider_name[:128],
                operation="image_generation_submit",
                units=1,
                unit_cost_usd=unit_cost,
                total_cost_usd=unit_cost,
                usage_metadata={
                    "slide_id": str(slide.id),
                    "external_job_id": external_job_id,
                    "provider_name": provider_name,
                },
            )
        )

    @staticmethod
    def _attempt_to_work_item(
        attempt: GenerationProviderAttempt,
        slide: GenerationSlide,
    ) -> AttemptWorkItem:
        return AttemptWorkItem(
            id=attempt.id,
            slide_id=attempt.slide_id,
            job_id=slide.job_id,
            provider_name=attempt.provider_name,
            attempt_number=attempt.attempt_number,
            external_job_id=attempt.external_job_id,
            reply_ref=attempt.reply_ref,
            abandoned=attempt.abandoned,
            slide_status=SlideStatus(slide.status),
        )


def _generation_cost_for_mode(mode: GenerationPostProcessingMode) -> int:
    settings = get_settings()
    if mode == GenerationPostProcessingMode.HD_FACE_FIX:
        return settings.generation_hd_face_fix_cost_coins
    return settings.generation_fast_cost_coins
