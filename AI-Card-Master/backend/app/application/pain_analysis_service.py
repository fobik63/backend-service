"""Use cases for competitor negative-review pain analysis."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.application.ports.pain_analysis import (
    PainAnalysisClaudePort,
    PainAnalysisPersistencePort,
)
from app.domain.pain_analysis import (
    PainAnalysisJobStatus,
    PainAnalysisJobView,
    PainAnalysisRequest,
    PainAnalysisResult,
    build_filter_preview_payload,
    dump_pain_analysis_result,
    filter_and_preview_pains,
    merge_with_deterministic_fallback,
    redis_pain_analysis_key,
)
from app.infrastructure.redis import (
    RedisUnavailableError,
    cache_json,
    get_cached_json,
)

logger = logging.getLogger(__name__)


class PainAnalysisError(Exception):
    """Base pain-analysis workflow failure."""


class PainAnalysisValidationError(PainAnalysisError):
    """Invalid request payload."""


class PainAnalysisNotFoundError(PainAnalysisError):
    """Job was not found for the user."""


class PainAnalysisService:
    """Coordinate junk filter → Claude pain-closing content."""

    def __init__(
        self,
        repository: PainAnalysisPersistencePort,
        *,
        model_name: str,
        redis_stage_ttl_seconds: int,
        analyzer: PainAnalysisClaudePort | None = None,
    ) -> None:
        if not model_name.strip():
            raise PainAnalysisValidationError("model_name must not be empty.")
        if redis_stage_ttl_seconds <= 0:
            raise PainAnalysisValidationError(
                "redis_stage_ttl_seconds must be positive."
            )
        self._repository = repository
        self._analyzer = analyzer
        self._model_name = model_name.strip()
        self._redis_stage_ttl_seconds = redis_stage_ttl_seconds

    def preview_filter(self, request: PainAnalysisRequest) -> PainAnalysisResult:
        """Synchronous junk filter + template content without Claude spend."""

        return filter_and_preview_pains(request)

    async def enqueue_analysis(
        self,
        *,
        user_id: UUID,
        request: PainAnalysisRequest,
        idempotency_key: str | None = None,
    ) -> tuple[PainAnalysisJobView, bool]:
        """Create a queued job; caller publishes Celery task.

        Returns (job, idempotent_replay).
        """

        if idempotency_key:
            existing = await self._repository.find_idempotent_job(
                user_id=user_id,
                idempotency_key=idempotency_key.strip(),
            )
            if existing is not None:
                return existing, True

        # Validate early via deterministic path.
        filter_and_preview_pains(request)

        job = await self._repository.create_job(
            user_id=user_id,
            product_name=request.product_name,
            platform=request.platform,
            request_payload=request.model_dump(mode="json"),
            model_name=self._model_name,
            idempotency_key=idempotency_key.strip() if idempotency_key else None,
        )
        return job, False

    async def attach_celery_task(
        self, *, job_id: UUID, celery_task_id: str
    ) -> PainAnalysisJobView:
        return await self._repository.mark_status(
            job_id=job_id,
            status=PainAnalysisJobStatus.QUEUED,
            celery_task_id=celery_task_id,
        )

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> PainAnalysisJobView:
        job = await self._repository.get_job_for_user(user_id=user_id, job_id=job_id)
        if job is None:
            raise PainAnalysisNotFoundError("Pain analysis job not found.")
        return job

    async def run_analysis(self, *, job_id: UUID) -> PainAnalysisJobView:
        """Execute filter → optional Claude analysis → pain-closing content."""

        job = await self._repository.get_job(job_id=job_id)
        if job is None:
            raise PainAnalysisNotFoundError("Pain analysis job not found.")
        if job.status == PainAnalysisJobStatus.COMPLETED and job.analysis_result:
            return job
        if job.status == PainAnalysisJobStatus.FAILED:
            raise PainAnalysisError(
                job.error_message or "Pain analysis job previously failed."
            )

        try:
            await self._repository.mark_status(
                job_id=job_id,
                status=PainAnalysisJobStatus.FILTERING,
            )

            job = await self._repository.get_job(job_id=job_id)
            if job is None:
                raise PainAnalysisNotFoundError("Pain analysis job not found.")

            request = PainAnalysisRequest.model_validate(job.request_payload)
            preview = filter_and_preview_pains(request)
            preview_payload = build_filter_preview_payload(preview)
            await self._write_stage_cache(job_id, "filter", preview_payload)
            await self._repository.save_filter_preview(
                job_id=job_id,
                filter_preview=preview_payload,
            )

            claude_result: PainAnalysisResult | None = None
            total_in = 0
            total_out = 0

            if self._analyzer is not None:
                await self._repository.mark_status(
                    job_id=job_id,
                    status=PainAnalysisJobStatus.ANALYZING,
                )
                claude_result, total_in, total_out = (
                    await self._analyzer.analyze_competitor_pains(
                        request=request,
                        user_id=job.user_id,
                        job_id=job_id,
                    )
                )
            else:
                logger.warning(
                    "Pain analysis job_id=%s: Claude unavailable; "
                    "using deterministic filter/content.",
                    job_id,
                )

            result = merge_with_deterministic_fallback(
                request=request,
                claude_result=claude_result,
            )
            result_payload = dump_pain_analysis_result(result)
            await self._write_stage_cache(job_id, "result", result_payload)

            return await self._repository.save_final_result(
                job_id=job_id,
                analysis_result=result_payload,
                input_tokens_delta=total_in,
                output_tokens_delta=total_out,
            )
        except PainAnalysisError:
            raise
        except Exception as exc:
            logger.exception("Pain analysis failed for job_id=%s", job_id)
            await self._repository.mark_status(
                job_id=job_id,
                status=PainAnalysisJobStatus.FAILED,
                error_message=str(exc)[:1000],
                completed_at=datetime.now(UTC),
            )
            raise PainAnalysisError(str(exc)) from exc

    async def _write_stage_cache(
        self, job_id: UUID, stage: str, payload: dict[str, Any]
    ) -> None:
        try:
            await cache_json(
                redis_pain_analysis_key(job_id, stage),
                payload,
                self._redis_stage_ttl_seconds,
            )
        except RedisUnavailableError:
            logger.warning(
                "Redis unavailable; skipped pain-analysis cache job_id=%s stage=%s",
                job_id,
                stage,
            )

    async def _read_stage_cache(
        self, job_id: UUID, stage: str
    ) -> dict[str, Any] | None:
        try:
            return await get_cached_json(redis_pain_analysis_key(job_id, stage))
        except RedisUnavailableError:
            return None
