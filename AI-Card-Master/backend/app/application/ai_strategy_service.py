"""Use cases for Strategic 'Killer' Recommendations Engine (AI Strategy)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.application.ports.ai_strategy import (
    StrategyPersistencePort,
    StrategyPlanningPort,
)
from app.domain.ai_strategy import (
    StrategyCardSnapshot,
    StrategyCompareConfig,
    StrategyCompareReport,
    StrategyEnqueueRequest,
    StrategyJobStatus,
    StrategyJobView,
    build_plan_result,
    compare_user_vs_leader,
    dump_compare_report,
    dump_plan_result,
    redis_strategy_key,
)
from app.infrastructure.redis import (
    RedisUnavailableError,
    cache_json,
    get_cached_json,
)

logger = logging.getLogger(__name__)


class StrategyError(Exception):
    """Base AI Strategy workflow failure."""


class StrategyValidationError(StrategyError):
    """Invalid request payload."""


class StrategyNotFoundError(StrategyError):
    """Job was not found for the user."""


class StrategyService:
    """Coordinate card compare → Claude killer plan."""

    def __init__(
        self,
        repository: StrategyPersistencePort,
        *,
        model_name: str,
        redis_stage_ttl_seconds: int,
        default_compare_config: StrategyCompareConfig | None = None,
        planning: StrategyPlanningPort | None = None,
    ) -> None:
        if not model_name.strip():
            raise StrategyValidationError("model_name must not be empty.")
        if redis_stage_ttl_seconds <= 0:
            raise StrategyValidationError("redis_stage_ttl_seconds must be positive.")
        self._repository = repository
        self._planning = planning
        self._model_name = model_name.strip()
        self._redis_stage_ttl_seconds = redis_stage_ttl_seconds
        self._default_compare_config = default_compare_config or StrategyCompareConfig()

    def preview_compare(self, request: StrategyEnqueueRequest) -> StrategyCompareReport:
        """Synchronous user-vs-leader comparison without Claude spend."""

        config = request.compare_config or self._default_compare_config
        return compare_user_vs_leader(
            marketplace=request.marketplace,
            niche_key=request.niche_key,
            user_card=request.user_card,
            leader_card=request.leader_card,
            config=config,
        )

    async def enqueue_plan(
        self,
        *,
        user_id: UUID,
        request: StrategyEnqueueRequest,
        idempotency_key: str | None = None,
    ) -> tuple[StrategyJobView, bool]:
        """Create a queued AI Strategy job; caller publishes Celery task.

        Returns (job, idempotent_replay).
        """

        if idempotency_key:
            existing = await self._repository.find_idempotent_job(
                user_id=user_id,
                idempotency_key=idempotency_key.strip(),
            )
            if existing is not None:
                return existing, True

        config = request.compare_config or self._default_compare_config
        # Validate early so bad payloads fail before queue.
        compare_user_vs_leader(
            marketplace=request.marketplace,
            niche_key=request.niche_key,
            user_card=request.user_card,
            leader_card=request.leader_card,
            config=config,
        )

        job = await self._repository.create_job(
            user_id=user_id,
            niche_key=request.niche_key.strip(),
            marketplace=request.marketplace.strip().lower(),
            user_card_payload=request.user_card.model_dump(mode="json"),
            leader_card_payload=request.leader_card.model_dump(mode="json"),
            compare_config=config.model_dump(mode="json"),
            model_name=self._model_name,
            idempotency_key=idempotency_key.strip() if idempotency_key else None,
        )
        return job, False

    async def attach_celery_task(
        self, *, job_id: UUID, celery_task_id: str
    ) -> StrategyJobView:
        return await self._repository.mark_status(
            job_id=job_id,
            status=StrategyJobStatus.QUEUED,
            celery_task_id=celery_task_id,
        )

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> StrategyJobView:
        job = await self._repository.get_job_for_user(user_id=user_id, job_id=job_id)
        if job is None:
            raise StrategyNotFoundError("AI Strategy job not found.")
        return job

    async def run_strategy_plan(self, *, job_id: UUID) -> StrategyJobView:
        """Execute compare → optional Claude planning → killer step plan."""

        job = await self._repository.get_job(job_id=job_id)
        if job is None:
            raise StrategyNotFoundError("AI Strategy job not found.")
        if job.status == StrategyJobStatus.COMPLETED and job.plan_result:
            return job
        if job.status == StrategyJobStatus.FAILED:
            raise StrategyError(
                job.error_message or "AI Strategy job previously failed."
            )

        try:
            await self._repository.mark_status(
                job_id=job_id,
                status=StrategyJobStatus.COMPARING,
            )

            job = await self._repository.get_job(job_id=job_id)
            if job is None:
                raise StrategyNotFoundError("AI Strategy job not found.")

            user_card = StrategyCardSnapshot.model_validate(job.user_card_payload)
            leader_card = StrategyCardSnapshot.model_validate(job.leader_card_payload)
            compare_config = StrategyCompareConfig.model_validate(job.compare_config)

            report = compare_user_vs_leader(
                marketplace=job.marketplace,
                niche_key=job.niche_key,
                user_card=user_card,
                leader_card=leader_card,
                config=compare_config,
            )
            report_payload = dump_compare_report(report)
            await self._write_stage_cache(job_id, "compare", report_payload)
            await self._repository.save_compare_report(
                job_id=job_id,
                compare_report=report_payload,
            )

            enrichments = []
            executive_summary: str | None = None
            total_in = 0
            total_out = 0

            if report.recommendations and self._planning is not None:
                await self._repository.mark_status(
                    job_id=job_id,
                    status=StrategyJobStatus.PLANNING,
                )
                enrichments, executive_summary, total_in, total_out = (
                    await self._planning.enrich_strategy_plan(
                        compare_report=report,
                        user_id=job.user_id,
                        job_id=job_id,
                    )
                )
            elif report.recommendations and self._planning is None:
                logger.warning(
                    "AI Strategy job_id=%s has deltas but Claude planning is unavailable; "
                    "emitting deterministic killer plan.",
                    job_id,
                )

            result = build_plan_result(
                compare_report=report,
                enrichments=enrichments,
                model_name=job.model_name if enrichments else "deterministic",
                executive_summary=executive_summary,
            )
            result_payload = dump_plan_result(result)
            await self._write_stage_cache(job_id, "plan", result_payload)

            return await self._repository.save_final_result(
                job_id=job_id,
                plan_result=result_payload,
                input_tokens_delta=total_in,
                output_tokens_delta=total_out,
            )
        except StrategyError:
            raise
        except Exception as exc:
            logger.exception("AI Strategy plan failed for job_id=%s", job_id)
            await self._repository.mark_status(
                job_id=job_id,
                status=StrategyJobStatus.FAILED,
                error_message=str(exc)[:1000],
                completed_at=datetime.now(UTC),
            )
            raise StrategyError(str(exc)) from exc

    async def _write_stage_cache(
        self, job_id: UUID, stage: str, payload: dict[str, Any]
    ) -> None:
        try:
            await cache_json(
                redis_strategy_key(job_id, stage),
                payload,
                self._redis_stage_ttl_seconds,
            )
        except RedisUnavailableError:
            logger.warning(
                "Redis unavailable; skipped AI Strategy cache job_id=%s stage=%s",
                job_id,
                stage,
            )

    async def _read_stage_cache(
        self, job_id: UUID, stage: str
    ) -> dict[str, Any] | None:
        try:
            return await get_cached_json(redis_strategy_key(job_id, stage))
        except RedisUnavailableError:
            return None
