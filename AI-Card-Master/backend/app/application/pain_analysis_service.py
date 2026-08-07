"""Use cases for competitor negative-review pain analysis."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.application.ports.claude_reasoning import ClaudeStageCachePort
from app.application.ports.pain_analysis import (
    PainAnalysisClaudePort,
    PainAnalysisPersistencePort,
)
from app.application.ports.token_governor import LocalLlmPort, TokenGovernorPort
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
from app.domain.semantic_filter import estimate_text_tokens
from app.domain.smart_reasoning import ReasoningTaskKind
from app.domain.text_task_classifier import TextTaskComplexity
from app.domain.token_governor import GovernorAction, GovernorRequest

logger = logging.getLogger(__name__)


class _NullStageCache:
    async def get(self, key: str) -> dict[str, Any] | None:
        return None

    async def set(self, key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        return None


class PainAnalysisError(Exception):
    """Base pain-analysis workflow failure."""


class PainAnalysisValidationError(PainAnalysisError):
    """Invalid request payload."""


class PainAnalysisNotFoundError(PainAnalysisError):
    """Job was not found for the user."""


class PainAnalysisService:
    """Coordinate junk filter → Claude/local pain-closing content."""

    def __init__(
        self,
        repository: PainAnalysisPersistencePort,
        *,
        model_name: str,
        redis_stage_ttl_seconds: int,
        analyzer: PainAnalysisClaudePort | None = None,
        stage_cache: ClaudeStageCachePort | None = None,
        token_governor: TokenGovernorPort | None = None,
        local_llm: LocalLlmPort | None = None,
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
        self._stage_cache = stage_cache or _NullStageCache()
        self._token_governor = token_governor
        self._local_llm = local_llm

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
            # Pass 1: claim FILTERING (payload on returned view).
            job = await self._repository.mark_status(
                job_id=job_id,
                status=PainAnalysisJobStatus.FILTERING,
            )

            request = PainAnalysisRequest.model_validate(job.request_payload)
            preview = filter_and_preview_pains(request)
            preview_payload = build_filter_preview_payload(preview)
            await self._write_stage_cache(job_id, "filter", preview_payload)

            claude_result: PainAnalysisResult | None = None
            total_in = 0
            total_out = 0

            use_local = await self._should_use_local(request)
            analyzer = self._pick_analyzer(use_local=use_local)

            # Pass 2: filter + ANALYZING (or filter-only) in one write.
            if analyzer is not None:
                await self._repository.save_filter_checkpoint(
                    job_id=job_id,
                    filter_preview=preview_payload,
                    next_status=PainAnalysisJobStatus.ANALYZING,
                )
                try:
                    claude_result, total_in, total_out = (
                        await analyzer.analyze_competitor_pains(
                            request=request,
                            user_id=job.user_id,
                            job_id=job_id,
                        )
                    )
                except Exception:
                    if use_local and self._analyzer is not None:
                        logger.warning(
                            "Local LLM pain analysis failed job_id=%s; "
                            "falling back to Claude.",
                            job_id,
                            exc_info=True,
                        )
                        claude_result, total_in, total_out = (
                            await self._analyzer.analyze_competitor_pains(
                                request=request,
                                user_id=job.user_id,
                                job_id=job_id,
                            )
                        )
                    else:
                        raise
            else:
                await self._repository.save_filter_preview(
                    job_id=job_id,
                    filter_preview=preview_payload,
                )
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

            # Pass 3: final persist.
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

    async def _should_use_local(self, request: PainAnalysisRequest) -> bool:
        if self._local_llm is None or not self._local_llm.available:
            return False
        if self._token_governor is None:
            return False
        text_blob = "\n".join(
            [
                request.product_name,
                request.product_specs,
                *request.raw_negative_reviews,
            ]
        )
        estimated = estimate_text_tokens(text_blob)
        decision = self._token_governor.authorize(
            GovernorRequest(
                task_kind=ReasoningTaskKind.PAIN_ANALYSIS,
                estimated_input_tokens=estimated,
                has_vision=False,
            )
        )
        if decision.action is not GovernorAction.USE_LOCAL:
            return False

        # C6: local classifier gates borderline text before Claude escalation.
        try:
            classification = await self._local_llm.classify_text_task(
                kind=ReasoningTaskKind.PAIN_ANALYSIS,
                text_blob=text_blob,
                item_count=len(request.raw_negative_reviews),
                has_vision=False,
            )
        except Exception:
            logger.info(
                "Pain local classifier failed; keeping governor USE_LOCAL",
                exc_info=True,
            )
            return True

        if classification.complexity is TextTaskComplexity.NEEDS_CLAUDE:
            logger.info(
                "Local classifier escalated pain analysis to Claude reason=%s",
                classification.reason,
            )
            return False
        return True

    def _pick_analyzer(
        self, *, use_local: bool
    ) -> PainAnalysisClaudePort | LocalLlmPort | None:
        if use_local and self._local_llm is not None and self._local_llm.available:
            logger.info(
                "Token governor routed pain analysis to local LLM model=%s",
                self._local_llm.model_name,
            )
            return self._local_llm
        return self._analyzer

    async def _write_stage_cache(
        self, job_id: UUID, stage: str, payload: dict[str, Any]
    ) -> None:
        try:
            await self._stage_cache.set(
                redis_pain_analysis_key(job_id, stage),
                payload,
                self._redis_stage_ttl_seconds,
            )
        except Exception:
            logger.warning(
                "Skipped pain-analysis cache job_id=%s stage=%s",
                job_id,
                stage,
                exc_info=True,
            )

    async def _read_stage_cache(
        self, job_id: UUID, stage: str
    ) -> dict[str, Any] | None:
        try:
            return await self._stage_cache.get(redis_pain_analysis_key(job_id, stage))
        except Exception:
            return None
