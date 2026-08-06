"""Unit tests for parser ↔ «Глаз Бога» bridge (plan §76)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.application.eye_of_god_bridge_service import EyeOfGodBridgeService
from app.domain.eye_of_god import (
    MONEY_CONFIRMED_TRIGGER_LABEL,
    ConversionElement,
    EyeOfGodJobStatus,
    EyeOfGodJobView,
    MoneyConfirmedVisionResult,
    SalesSpikeSignal,
    build_money_confirmed_trigger_config,
    detect_sales_spike,
    money_trigger_config_json,
    wildberries_primary_image_urls,
)
from app.domain.stock_parser import ParserMarketplace
from app.domain.stock_sales import (
    DailySalesEstimate,
    SalesWindowSummary,
    StockMovementKind,
)


def _day(offset: int, units: int) -> DailySalesEstimate:
    d = date(2026, 7, 20) + timedelta(days=offset)
    return DailySalesEstimate(
        sku_id=None,
        day=d,
        stock_yesterday=100,
        stock_today=100 - units,
        raw_delta=units,
        units_sold=units,
        units_returned=0,
        units_restocked=0,
        kind=StockMovementKind.SALE,
        confidence=0.9,
        gap_hours=24.0,
        notes=(),
    )


def _summary(daily_units: list[int]) -> SalesWindowSummary:
    days = tuple(_day(i, units) for i, units in enumerate(daily_units))
    reliable = [d for d in days if d.is_reliable]
    sold = sum(d.units_sold for d in days)
    return SalesWindowSummary(
        sku_id=None,
        days=days,
        total_units_sold=sold,
        total_units_returned=0,
        total_units_restocked=0,
        reliable_day_count=len(reliable),
        skipped_day_count=0,
        avg_daily_sales=(sold / len(reliable)) if reliable else 0.0,
        last_24h=days[-1] if days else None,
    )


def test_detect_sales_spike_plus_30_percent_over_3_days() -> None:
    # baseline 7d @ 10/day, recent 3d @ 13/day → +30%
    units = [10] * 7 + [13, 13, 13]
    sku_id = uuid4()
    spike = detect_sales_spike(
        _summary(units),
        sku_id=sku_id,
        marketplace=ParserMarketplace.WILDBERRIES,
        article="12345678",
        title="Competitor hoodie",
        triggered_at=datetime(2026, 8, 7, 3, 0, tzinfo=UTC),
    )
    assert spike is not None
    assert spike.growth_ratio == pytest.approx(0.30, abs=1e-3)
    assert spike.recent_window_days == 3
    assert spike.is_money_anomaly is True


def test_no_spike_when_growth_below_threshold() -> None:
    units = [10] * 7 + [11, 11, 11]  # +10% < 30%
    spike = detect_sales_spike(
        _summary(units),
        sku_id=uuid4(),
        marketplace=ParserMarketplace.OZON,
        article="oz-1",
        triggered_at=datetime(2026, 8, 7, tzinfo=UTC),
    )
    assert spike is None


def test_no_spike_when_not_enough_history() -> None:
    spike = detect_sales_spike(
        _summary([10, 20, 30]),
        sku_id=uuid4(),
        marketplace=ParserMarketplace.WILDBERRIES,
        article="short",
        triggered_at=datetime(2026, 8, 7, tzinfo=UTC),
    )
    assert spike is None


def test_money_confirmed_trigger_json_label() -> None:
    sku_id = uuid4()
    spike = SalesSpikeSignal(
        sku_id=sku_id,
        marketplace=ParserMarketplace.WILDBERRIES,
        article="999",
        title="Star SKU",
        product_url="https://www.wildberries.ru/catalog/999/detail.aspx",
        recent_avg_daily_sales=13.0,
        baseline_avg_daily_sales=10.0,
        growth_ratio=0.3,
        recent_window_days=3,
        baseline_window_days=7,
        recent_units_sold=39,
        baseline_units_sold=70,
        reliable_recent_days=3,
        reliable_baseline_days=7,
        triggered_at=datetime(2026, 8, 7, tzinfo=UTC),
        image_urls=("https://example.com/1.webp",),
    )
    vision = MoneyConfirmedVisionResult(
        sku="999",
        conversion_elements=[
            ConversionElement(
                element_type="pain_badge",
                description="Плашка «не рвётся» на первом слайде",
                placement="top-left",
                why_it_converts="Закрывает главную боль из отзывов ниши",
            )
        ],
        new_vs_typical_patterns=["Крупный оффер гарантии вместо логотипа"],
        first_slide_hooks=["Боль → решение за 1 секунду"],
        avoid_copying=["Не копировать бренд-якоря гигантов"],
        confidence=0.88,
        reasoning_trace="Рост продаж совпал с появлением pain-badge.",
    )
    config = build_money_confirmed_trigger_config(
        spike=spike,
        vision=vision,
        model_name="claude-opus-4-7",
        analyzed_at=datetime(2026, 8, 7, 4, 0, tzinfo=UTC),
    )
    assert config.label == MONEY_CONFIRMED_TRIGGER_LABEL
    payload = money_trigger_config_json(config)
    assert "Подтвержденный деньгами триггер" in payload
    assert "pain_badge" in payload


def test_wildberries_cdn_url_shape() -> None:
    urls = wildberries_primary_image_urls(1_234_567, count=2)
    assert len(urls) == 2
    assert "/images/big/1.webp" in urls[0]
    assert "/images/big/2.webp" in urls[1]


class _FakeEyeRepo:
    def __init__(self) -> None:
        self.jobs: dict[UUID, EyeOfGodJobView] = {}

    async def create_job(
        self,
        *,
        spike: SalesSpikeSignal,
        model_name: str,
        idempotency_key: str | None = None,
    ) -> EyeOfGodJobView:
        job_id = uuid4()
        now = datetime.now(UTC)
        job = EyeOfGodJobView(
            id=job_id,
            status=EyeOfGodJobStatus.QUEUED,
            celery_task_id=None,
            sku_id=spike.sku_id,
            marketplace=spike.marketplace.value,
            article=spike.article,
            title=spike.title,
            product_url=spike.product_url,
            spike_payload=spike.model_dump(mode="json"),
            image_urls=spike.image_urls,
            vision_result=None,
            money_trigger_config=None,
            model_name=model_name,
            error_message=None,
            input_tokens=0,
            output_tokens=0,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        self.jobs[job_id] = job
        return job

    async def find_recent_job_for_sku(
        self, *, sku_id: UUID, since: datetime
    ) -> EyeOfGodJobView | None:
        return None

    async def find_idempotent_job(
        self, *, idempotency_key: str
    ) -> EyeOfGodJobView | None:
        return None

    async def get_job(self, *, job_id: UUID) -> EyeOfGodJobView | None:
        return self.jobs.get(job_id)

    async def mark_status(
        self,
        *,
        job_id: UUID,
        status: EyeOfGodJobStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> EyeOfGodJobView:
        job = self.jobs[job_id]
        updated = EyeOfGodJobView(
            id=job.id,
            status=status,
            celery_task_id=celery_task_id or job.celery_task_id,
            sku_id=job.sku_id,
            marketplace=job.marketplace,
            article=job.article,
            title=job.title,
            product_url=job.product_url,
            spike_payload=job.spike_payload,
            image_urls=job.image_urls,
            vision_result=job.vision_result,
            money_trigger_config=job.money_trigger_config,
            model_name=job.model_name,
            error_message=(
                error_message if error_message is not None else job.error_message
            ),
            input_tokens=job.input_tokens,
            output_tokens=job.output_tokens,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
            completed_at=completed_at or job.completed_at,
        )
        self.jobs[job_id] = updated
        return updated

    async def save_money_trigger_result(
        self,
        *,
        job_id: UUID,
        vision_result: dict[str, Any],
        money_trigger_config: dict[str, Any],
        image_urls: list[str] | None = None,
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> EyeOfGodJobView:
        job = self.jobs[job_id]
        updated = EyeOfGodJobView(
            id=job.id,
            status=EyeOfGodJobStatus.COMPLETED,
            celery_task_id=job.celery_task_id,
            sku_id=job.sku_id,
            marketplace=job.marketplace,
            article=job.article,
            title=job.title,
            product_url=job.product_url,
            spike_payload=job.spike_payload,
            image_urls=tuple(image_urls) if image_urls is not None else job.image_urls,
            vision_result=vision_result,
            money_trigger_config=money_trigger_config,
            model_name=job.model_name,
            error_message=None,
            input_tokens=job.input_tokens + input_tokens_delta,
            output_tokens=job.output_tokens + output_tokens_delta,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        self.jobs[job_id] = updated
        return updated


class _FakeStockRepo:
    async def list_stock_snapshots(self, **kwargs: Any) -> list[Any]:
        return []


class _FakeVision:
    model_name = "claude-opus-4-7"

    async def analyze_money_confirmed_trigger(
        self, **kwargs: Any
    ) -> tuple[MoneyConfirmedVisionResult, int, int]:
        return (
            MoneyConfirmedVisionResult(
                sku=kwargs["sku"],
                conversion_elements=[
                    ConversionElement(
                        element_type="contrast_accent",
                        description="Жёлтый CTA на тёмном фоне",
                        placement="center",
                        why_it_converts="Выделяется в слепой выдаче",
                    )
                ],
                new_vs_typical_patterns=["CTA вместо lifestyle"],
                first_slide_hooks=["Гарантия 2 года"],
                avoid_copying=[],
                confidence=0.91,
                reasoning_trace="Новый CTA совпал со спайком продаж.",
            ),
            100,
            50,
        )

    async def aclose(self) -> None:
        return None


class _FakeImages:
    async def fetch_current_images(
        self, **kwargs: Any
    ) -> tuple[tuple[bytes, str, str], ...]:
        return ((b"\xff\xd8\xff\xd9", "image/jpeg", "https://cdn.example/1.jpg"),)


@pytest.mark.asyncio
async def test_vision_pipeline_saves_money_confirmed_trigger() -> None:
    repo = _FakeEyeRepo()
    sku_id = uuid4()
    spike = SalesSpikeSignal(
        sku_id=sku_id,
        marketplace=ParserMarketplace.WILDBERRIES,
        article="555",
        title="Rising",
        product_url=None,
        recent_avg_daily_sales=20.0,
        baseline_avg_daily_sales=10.0,
        growth_ratio=1.0,
        recent_window_days=3,
        baseline_window_days=7,
        recent_units_sold=60,
        baseline_units_sold=70,
        reliable_recent_days=3,
        reliable_baseline_days=7,
        triggered_at=datetime(2026, 8, 7, tzinfo=UTC),
        image_urls=("https://cdn.example/1.jpg",),
    )
    job = await repo.create_job(spike=spike, model_name="claude-opus-4-7")
    service = EyeOfGodBridgeService(
        persistence=repo,
        stock_persistence=_FakeStockRepo(),  # type: ignore[arg-type]
        vision=_FakeVision(),
        images=_FakeImages(),
        trigger=None,
    )
    completed = await service.run_vision_pipeline(job_id=job.id)
    assert completed.status is EyeOfGodJobStatus.COMPLETED
    assert completed.money_trigger_config is not None
    assert completed.money_trigger_config["label"] == MONEY_CONFIRMED_TRIGGER_LABEL
    assert len(completed.money_trigger_config["conversion_elements"]) == 1
    assert completed.input_tokens == 100
    assert completed.output_tokens == 50
