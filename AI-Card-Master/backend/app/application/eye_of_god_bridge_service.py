"""Application bridge: stock-parser sales spike → Claude «Глаз Бога» Vision.

Parser never imports Anthropic. It only evaluates sales math and enqueues a
job via ``EyeOfGodTriggerPort``. The Celery worker fetches the current SKU
photo, runs Claude 4.7 Vision, and persists JSON labelled
«Подтвержденный деньгами триггер».
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Sequence
from uuid import UUID

from app.application.ports.eye_of_god import (
    EyeOfGodPersistencePort,
    EyeOfGodTriggerPort,
    EyeOfGodVisionPort,
    SkuCardImagePort,
)
from app.application.ports.claude_reasoning import ClaudeStageCachePort
from app.application.ports.stock_parser import StockParserPersistencePort
from app.domain.eye_of_god import (
    EyeOfGodJobStatus,
    EyeOfGodJobView,
    MoneyConfirmedVisionResult,
    SalesSpikeConfig,
    SalesSpikeSignal,
    build_money_confirmed_trigger_config,
    detect_sales_spike,
    dump_money_trigger_config,
    redis_eye_of_god_key,
)
from app.domain.stock_parser import ParserMarketplace, SkuItemView
from app.domain.stock_sales import (
    SalesWindowSummary,
    SnapshotStockPoint,
    StockSalesFilterConfig,
    snapshots_to_sales_window,
)

logger = logging.getLogger(__name__)


class _NullStageCache:
    async def get(self, key: str) -> dict[str, Any] | None:
        return None

    async def set(self, key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        return None


class EyeOfGodBridgeError(Exception):
    """Base Eye-of-God bridge failure."""


class EyeOfGodNotFoundError(EyeOfGodBridgeError):
    """Job missing for worker path."""


class EyeOfGodValidationError(EyeOfGodBridgeError):
    """Invalid configuration or empty Vision inputs."""


class EyeOfGodTransientError(EyeOfGodBridgeError):
    """Retryable upstream / I/O failure."""


class EyeOfGodBridgeService:
    """Orchestrate spike detection (parser side) and Vision analysis (worker)."""

    def __init__(
        self,
        *,
        persistence: EyeOfGodPersistencePort,
        stock_persistence: StockParserPersistencePort,
        spike_config: SalesSpikeConfig | None = None,
        sales_config: StockSalesFilterConfig | None = None,
        model_name: str = "claude-opus-4-7",
        prefer_hour_utc: int = 3,
        lookback_days: int = 21,
        vision: EyeOfGodVisionPort | None = None,
        images: SkuCardImagePort | None = None,
        trigger: EyeOfGodTriggerPort | None = None,
        max_images: int = 3,
        stage_cache: ClaudeStageCachePort | None = None,
        redis_stage_ttl_seconds: int = 86400,
    ) -> None:
        if not model_name.strip():
            raise EyeOfGodValidationError("model_name must not be empty.")
        if max_images < 1:
            raise EyeOfGodValidationError("max_images must be >= 1.")
        if redis_stage_ttl_seconds <= 0:
            raise EyeOfGodValidationError(
                "redis_stage_ttl_seconds must be positive."
            )
        self._persistence = persistence
        self._stock_persistence = stock_persistence
        self._spike_config = spike_config or SalesSpikeConfig()
        self._sales_config = sales_config or StockSalesFilterConfig()
        self._model_name = model_name.strip()
        self._prefer_hour_utc = prefer_hour_utc
        self._lookback_days = max(lookback_days, 10)
        self._vision = vision
        self._images = images
        self._trigger = trigger
        self._max_images = max_images
        self._stage_cache = stage_cache or _NullStageCache()
        self._redis_stage_ttl_seconds = redis_stage_ttl_seconds

    def _require_vision(self) -> EyeOfGodVisionPort:
        if self._vision is None:
            raise EyeOfGodBridgeError(
                "Claude Vision client is not configured for this process."
            )
        return self._vision

    def _require_images(self) -> SkuCardImagePort:
        if self._images is None:
            raise EyeOfGodBridgeError(
                "SKU image fetcher is not configured for this process."
            )
        return self._images

    async def evaluate_and_enqueue_for_sku(
        self,
        *,
        sku_item: SkuItemView,
        image_urls: Sequence[str] = (),
        as_of: datetime | None = None,
        enqueue: bool = True,
    ) -> EyeOfGodJobView | None:
        """Parser-side entry: detect +30%/3d spike and enqueue Eye of God.

        Returns the created (or cooldown-replayed) job, or ``None`` when no
        money anomaly is present.
        """

        now = as_of if as_of is not None else datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        else:
            now = now.astimezone(UTC)

        cooldown_since = now - timedelta(hours=self._spike_config.cooldown_hours)
        recent = await self._persistence.find_recent_job_for_sku(
            sku_id=sku_item.id,
            since=cooldown_since,
        )
        if recent is not None:
            logger.info(
                "Eye-of-God cooldown active sku_id=%s job_id=%s status=%s",
                sku_item.id,
                recent.id,
                recent.status.value,
            )
            return recent

        summary = await self._load_sales_window(sku_id=sku_item.id, as_of=now)
        spike = detect_sales_spike(
            summary,
            sku_id=sku_item.id,
            marketplace=sku_item.marketplace,
            article=sku_item.article,
            title=sku_item.title,
            product_url=sku_item.product_url,
            triggered_at=now,
            config=self._spike_config,
            image_urls=image_urls,
        )
        if spike is None:
            return None

        idempotency_key = (
            f"eog:{sku_item.marketplace.value}:{sku_item.article}:"
            f"{now.date().isoformat()}"
        )
        existing = await self._persistence.find_idempotent_job(
            idempotency_key=idempotency_key
        )
        if existing is not None:
            return existing

        job = await self._persistence.create_job(
            spike=spike,
            model_name=self._model_name,
            idempotency_key=idempotency_key,
        )
        logger.info(
            "Eye-of-God trigger queued job_id=%s sku=%s growth=%.0f%%",
            job.id,
            spike.article,
            spike.growth_ratio * 100,
        )
        if enqueue and self._trigger is not None:
            task_id = self._trigger.enqueue_sales_spike(job_id=job.id)
            job = await self._persistence.mark_status(
                job_id=job.id,
                status=EyeOfGodJobStatus.QUEUED,
                celery_task_id=task_id,
            )
        return job

    async def evaluate_spike_only(
        self,
        *,
        sku_item: SkuItemView,
        image_urls: Sequence[str] = (),
        as_of: datetime | None = None,
    ) -> SalesSpikeSignal | None:
        """Pure detection helper (no persistence) for tests / dry-runs."""

        now = as_of if as_of is not None else datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        else:
            now = now.astimezone(UTC)
        summary = await self._load_sales_window(sku_id=sku_item.id, as_of=now)
        return detect_sales_spike(
            summary,
            sku_id=sku_item.id,
            marketplace=sku_item.marketplace,
            article=sku_item.article,
            title=sku_item.title,
            product_url=sku_item.product_url,
            triggered_at=now,
            config=self._spike_config,
            image_urls=image_urls,
        )

    async def run_vision_pipeline(self, *, job_id: UUID) -> EyeOfGodJobView:
        """Worker path: fetch photo → Claude Vision → money-trigger JSON."""

        job = await self._persistence.get_job(job_id=job_id)
        if job is None:
            raise EyeOfGodNotFoundError(f"Eye-of-God job {job_id} not found.")

        if job.status is EyeOfGodJobStatus.COMPLETED and job.money_trigger_config:
            return job

        vision = self._require_vision()
        images_port = self._require_images()

        try:
            await self._persistence.mark_status(
                job_id=job_id,
                status=EyeOfGodJobStatus.FETCHING_IMAGE,
            )
            fetched = await images_port.fetch_current_images(
                marketplace=job.marketplace,
                article=job.article,
                product_url=job.product_url,
                preferred_urls=job.image_urls,
                max_images=self._max_images,
            )
            if not fetched:
                await self._persistence.mark_status(
                    job_id=job_id,
                    status=EyeOfGodJobStatus.FAILED,
                    error_message="No current SKU photo available for Vision.",
                    completed_at=datetime.now(UTC),
                )
                raise EyeOfGodValidationError(
                    "No current SKU photo available for Eye-of-God Vision."
                )

            await self._persistence.mark_status(
                job_id=job_id,
                status=EyeOfGodJobStatus.VISION_RUNNING,
            )

            spike = SalesSpikeSignal.model_validate(job.spike_payload)
            image_tuples = tuple((blob, mime) for blob, mime, _url in fetched)
            analyzed_urls = [url for _b, _m, url in fetched]

            cached_vision = await self._read_stage_cache(job_id, "vision")
            if cached_vision is not None:
                result = MoneyConfirmedVisionResult.model_validate(cached_vision)
                in_tok, out_tok = 0, 0
            else:
                result, in_tok, out_tok = await vision.analyze_money_confirmed_trigger(
                    sku=job.article,
                    title=job.title,
                    marketplace=job.marketplace,
                    growth_ratio=spike.growth_ratio,
                    recent_avg_daily_sales=spike.recent_avg_daily_sales,
                    baseline_avg_daily_sales=spike.baseline_avg_daily_sales,
                    recent_window_days=spike.recent_window_days,
                    images=image_tuples,
                    job_id=job_id,
                )
                if not isinstance(result, MoneyConfirmedVisionResult):
                    result = MoneyConfirmedVisionResult.model_validate(result)
                await self._write_stage_cache(
                    job_id,
                    "vision",
                    result.model_dump(mode="json"),
                )

            config = build_money_confirmed_trigger_config(
                spike=spike,
                vision=result,
                model_name=vision.model_name or self._model_name,
                analyzed_at=datetime.now(UTC),
                image_urls_analyzed=analyzed_urls,
            )
            await self._write_stage_cache(
                job_id,
                "money_trigger",
                dump_money_trigger_config(config),
            )
            return await self._persistence.save_money_trigger_result(
                job_id=job_id,
                vision_result=result.model_dump(mode="json"),
                money_trigger_config=dump_money_trigger_config(config),
                image_urls=analyzed_urls,
                input_tokens_delta=in_tok,
                output_tokens_delta=out_tok,
            )
        except EyeOfGodValidationError:
            raise
        except EyeOfGodBridgeError:
            raise
        except Exception as exc:  # noqa: BLE001 — worker isolation
            logger.exception("Eye-of-God Vision failed job_id=%s", job_id)
            await self._persistence.mark_status(
                job_id=job_id,
                status=EyeOfGodJobStatus.QUEUED,
                error_message=str(exc)[:2000],
            )
            raise EyeOfGodTransientError(str(exc)) from exc

    async def _load_sales_window(
        self,
        *,
        sku_id: UUID,
        as_of: datetime,
    ) -> SalesWindowSummary:
        rows = await self._stock_persistence.list_stock_snapshots(
            sku_id=sku_id,
            captured_from=as_of - timedelta(days=self._lookback_days),
            captured_to=as_of + timedelta(seconds=1),
            limit=5000,
        )
        points = tuple(
            SnapshotStockPoint(
                captured_at=row.captured_at,
                warehouse_id=row.warehouse_id,
                quantity=row.quantity,
            )
            for row in rows
        )
        return snapshots_to_sales_window(
            points,
            sku_id=sku_id,
            config=self._sales_config,
            prefer_hour_utc=self._prefer_hour_utc,
        )

    async def _write_stage_cache(
        self, job_id: UUID, stage: str, payload: dict[str, Any]
    ) -> None:
        try:
            await self._stage_cache.set(
                redis_eye_of_god_key(job_id, stage),
                payload,
                self._redis_stage_ttl_seconds,
            )
        except Exception:  # noqa: BLE001 — fail-open
            logger.warning(
                "Skipped eye-of-god cache job_id=%s stage=%s",
                job_id,
                stage,
                exc_info=True,
            )

    async def _read_stage_cache(
        self, job_id: UUID, stage: str
    ) -> dict[str, Any] | None:
        try:
            return await self._stage_cache.get(redis_eye_of_god_key(job_id, stage))
        except Exception:  # noqa: BLE001 — fail-open
            logger.warning(
                "Eye-of-god cache read failed job_id=%s stage=%s",
                job_id,
                stage,
                exc_info=True,
            )
            return None


class CeleryEyeOfGodTrigger:
    """Adapter: enqueue Eye-of-God Vision Celery task from the parser process."""

    def enqueue_sales_spike(self, *, job_id: UUID) -> str:
        from app.workers.eye_of_god_tasks import run_eye_of_god_vision_task

        async_result = run_eye_of_god_vision_task.delay(str(job_id))
        return str(async_result.id)


def marketplace_from_str(value: str) -> ParserMarketplace:
    return ParserMarketplace(value.strip().lower())
