"""Use cases for Market Gap & Trend Prediction (The Oracle)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.application.ports.oracle import OracleEnrichmentPort, OraclePersistencePort
from app.domain.oracle import (
    OracleEnqueueRequest,
    OracleGapConfig,
    OracleJobStatus,
    OracleJobView,
    OracleScanReport,
    SearchQuerySignal,
    SupplyCardSignal,
    build_prediction_result,
    detect_market_gaps,
    dump_prediction_result,
    dump_scan_report,
    redis_oracle_key,
)
from app.infrastructure.redis import (
    RedisUnavailableError,
    cache_json,
    get_cached_json,
)

logger = logging.getLogger(__name__)


class OracleError(Exception):
    """Base Oracle workflow failure."""


class OracleValidationError(OracleError):
    """Invalid request payload."""


class OracleNotFoundError(OracleError):
    """Job was not found for the user."""


class OracleService:
    """Coordinate demand/supply scan → Claude enrichment → niche alerts."""

    def __init__(
        self,
        repository: OraclePersistencePort,
        *,
        model_name: str,
        redis_stage_ttl_seconds: int,
        default_gap_config: OracleGapConfig | None = None,
        enrichment: OracleEnrichmentPort | None = None,
    ) -> None:
        if not model_name.strip():
            raise OracleValidationError("model_name must not be empty.")
        if redis_stage_ttl_seconds <= 0:
            raise OracleValidationError("redis_stage_ttl_seconds must be positive.")
        self._repository = repository
        self._enrichment = enrichment
        self._model_name = model_name.strip()
        self._redis_stage_ttl_seconds = redis_stage_ttl_seconds
        self._default_gap_config = default_gap_config or OracleGapConfig()

    def preview_scan(self, request: OracleEnqueueRequest) -> OracleScanReport:
        """Synchronous demand/supply gap scan without Claude spend."""

        config = request.gap_config or self._default_gap_config
        return detect_market_gaps(
            marketplace=request.marketplace,
            niche_key=request.niche_key,
            search_queries=list(request.search_queries),
            supply_cards=list(request.supply_cards),
            config=config,
        )

    async def enqueue_prediction(
        self,
        *,
        user_id: UUID,
        request: OracleEnqueueRequest,
        idempotency_key: str | None = None,
    ) -> tuple[OracleJobView, bool]:
        """Create a queued Oracle job; caller publishes Celery task.

        Returns (job, idempotent_replay).
        """

        if idempotency_key:
            existing = await self._repository.find_idempotent_job(
                user_id=user_id,
                idempotency_key=idempotency_key.strip(),
            )
            if existing is not None:
                return existing, True

        if not request.search_queries:
            raise OracleValidationError("At least one search query is required.")

        config = request.gap_config or self._default_gap_config
        # Validate early so bad payloads fail before queue.
        detect_market_gaps(
            marketplace=request.marketplace,
            niche_key=request.niche_key,
            search_queries=list(request.search_queries),
            supply_cards=list(request.supply_cards),
            config=config,
        )

        job = await self._repository.create_job(
            user_id=user_id,
            niche_key=request.niche_key.strip(),
            marketplace=request.marketplace.strip().lower(),
            queries_payload=[q.model_dump(mode="json") for q in request.search_queries],
            supply_payload=[c.model_dump(mode="json") for c in request.supply_cards],
            gap_config=config.model_dump(mode="json"),
            model_name=self._model_name,
            idempotency_key=idempotency_key.strip() if idempotency_key else None,
        )
        return job, False

    async def attach_celery_task(
        self, *, job_id: UUID, celery_task_id: str
    ) -> OracleJobView:
        return await self._repository.mark_status(
            job_id=job_id,
            status=OracleJobStatus.QUEUED,
            celery_task_id=celery_task_id,
        )

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> OracleJobView:
        job = await self._repository.get_job_for_user(user_id=user_id, job_id=job_id)
        if job is None:
            raise OracleNotFoundError("Oracle job not found.")
        return job

    async def list_notifications(
        self, *, user_id: UUID, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Flatten niche alert messages from recent completed jobs."""

        jobs = await self._repository.list_recent_notifications(
            user_id=user_id,
            limit=max(1, min(limit, 50)),
        )
        items: list[dict[str, Any]] = []
        for job in jobs:
            messages = job.notifications or []
            for message in messages:
                items.append(
                    {
                        "job_id": str(job.id),
                        "niche_key": job.niche_key,
                        "marketplace": job.marketplace,
                        "message": message,
                        "created_at": job.completed_at.isoformat()
                        if job.completed_at
                        else job.updated_at.isoformat(),
                    }
                )
        return items

    async def run_oracle_prediction(self, *, job_id: UUID) -> OracleJobView:
        """Execute gap scan → optional Claude enrichment → niche alerts."""

        job = await self._repository.get_job(job_id=job_id)
        if job is None:
            raise OracleNotFoundError("Oracle job not found.")
        if job.status == OracleJobStatus.COMPLETED and job.prediction_result:
            return job
        if job.status == OracleJobStatus.FAILED:
            raise OracleError(
                job.error_message or "Oracle job previously failed."
            )

        try:
            await self._repository.mark_status(
                job_id=job_id,
                status=OracleJobStatus.SCANNING,
            )

            job = await self._repository.get_job(job_id=job_id)
            if job is None:
                raise OracleNotFoundError("Oracle job not found.")

            queries = [
                SearchQuerySignal.model_validate(item)
                for item in job.queries_payload
            ]
            supply = [
                SupplyCardSignal.model_validate(item)
                for item in job.supply_payload
            ]
            gap_config = OracleGapConfig.model_validate(job.gap_config)

            report = detect_market_gaps(
                marketplace=job.marketplace,
                niche_key=job.niche_key,
                search_queries=queries,
                supply_cards=supply,
                config=gap_config,
            )
            report_payload = dump_scan_report(report)
            await self._write_stage_cache(job_id, "scan", report_payload)
            await self._repository.save_scan_report(
                job_id=job_id,
                scan_report=report_payload,
            )

            enrichments = []
            total_in = 0
            total_out = 0

            if report.opportunities and self._enrichment is not None:
                await self._repository.mark_status(
                    job_id=job_id,
                    status=OracleJobStatus.ENRICHING,
                )
                enrichments, total_in, total_out = (
                    await self._enrichment.enrich_market_gaps(
                        scan_report=report,
                        user_id=job.user_id,
                        job_id=job_id,
                    )
                )
            elif report.opportunities and self._enrichment is None:
                logger.warning(
                    "Oracle job_id=%s has gaps but Claude enrichment is unavailable; "
                    "emitting deterministic notifications.",
                    job_id,
                )

            result = build_prediction_result(
                scan_report=report,
                enrichments=enrichments,
                model_name=job.model_name if enrichments else "deterministic",
            )
            result_payload = dump_prediction_result(result)
            await self._write_stage_cache(job_id, "prediction", result_payload)

            return await self._repository.save_final_result(
                job_id=job_id,
                prediction_result=result_payload,
                notifications=list(result.notifications),
                input_tokens_delta=total_in,
                output_tokens_delta=total_out,
            )
        except OracleError:
            raise
        except Exception as exc:
            logger.exception("Oracle prediction failed for job_id=%s", job_id)
            await self._repository.mark_status(
                job_id=job_id,
                status=OracleJobStatus.FAILED,
                error_message=str(exc)[:1000],
                completed_at=datetime.now(UTC),
            )
            raise OracleError(str(exc)) from exc

    async def _write_stage_cache(
        self, job_id: UUID, stage: str, payload: dict[str, Any]
    ) -> None:
        try:
            await cache_json(
                redis_oracle_key(job_id, stage),
                payload,
                self._redis_stage_ttl_seconds,
            )
        except RedisUnavailableError:
            logger.warning(
                "Redis unavailable; skipped Oracle cache job_id=%s stage=%s",
                job_id,
                stage,
            )

    async def _read_stage_cache(
        self, job_id: UUID, stage: str
    ) -> dict[str, Any] | None:
        try:
            return await get_cached_json(redis_oracle_key(job_id, stage))
        except RedisUnavailableError:
            return None
