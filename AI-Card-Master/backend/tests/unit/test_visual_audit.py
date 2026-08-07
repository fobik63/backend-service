"""Unit tests for intelligent visual audit (survivor bias + Rising Stars)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.application.visual_audit_service import (
    VisualAuditNotFoundError,
    VisualAuditService,
    VisualAuditValidationError,
)
from app.domain.visual_audit import (
    CardCohortLabel,
    GeneratorTriggerConfig,
    NicheCardSignal,
    RisingStarPainHook,
    RisingStarVisionDissection,
    VisualAuditEnqueueRequest,
    VisualAuditFilterConfig,
    VisualAuditJobStatus,
    VisualAuditJobView,
    build_generator_trigger_config,
    classify_niche_card,
    filter_niche_top_cards,
)

_MIN_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def _card(**kwargs) -> NicheCardSignal:
    base = {
        "sku": "SKU-1",
        "review_count": 200,
        "review_count_delta": 40,
        "observation_days": 7,
        "avg_daily_sales_baseline": 10.0,
        "avg_daily_sales_recent": 15.0,
        "image_object_keys": ["rising/sku1.png"],
    }
    base.update(kwargs)
    return NicheCardSignal.model_validate(base)


def test_brand_dominant_excluded_from_trigger_math() -> None:
    soft = classify_niche_card(
        _card(sku="BD-SOFT", review_count=5500, avg_daily_sales_recent=50.0),
        VisualAuditFilterConfig(),
    )
    hard = classify_niche_card(
        _card(sku="BD-HARD", review_count=9000),
        VisualAuditFilterConfig(),
    )
    assert soft.cohort == CardCohortLabel.BRAND_DOMINANT
    assert soft.exclude_from_trigger_math is True
    assert soft.rising_score == 0.0
    assert hard.cohort == CardCohortLabel.BRAND_DOMINANT
    assert hard.exclude_from_trigger_math is True


def test_rising_star_requires_moderate_reviews_and_sales_anomaly() -> None:
    star = classify_niche_card(
        _card(
            sku="RS-1",
            review_count=180,
            review_count_delta=35,
            avg_daily_sales_baseline=10.0,
            avg_daily_sales_recent=14.0,  # +40%
        ),
        VisualAuditFilterConfig(),
    )
    assert star.cohort == CardCohortLabel.RISING_STAR
    assert star.exclude_from_trigger_math is False
    assert star.sales_growth_ratio is not None
    assert star.sales_growth_ratio >= 0.30
    assert star.rising_score > 0


def test_velocity_alone_is_not_money_validated() -> None:
    card = classify_niche_card(
        _card(
            sku="VEL-1",
            review_count=220,
            review_count_delta=50,
            avg_daily_sales_baseline=10.0,
            avg_daily_sales_recent=11.0,  # +10% < 30%
        ),
        VisualAuditFilterConfig(),
    )
    assert card.cohort == CardCohortLabel.NEUTRAL
    assert card.exclude_from_trigger_math is True


def test_filter_top_n_drops_brand_giants_from_vision_queue() -> None:
    cards = [
        _card(sku="GIANT", rank=1, review_count=12000, avg_daily_sales_recent=100.0),
        _card(
            sku="STAR",
            rank=2,
            review_count=300,
            review_count_delta=40,
            avg_daily_sales_baseline=8.0,
            avg_daily_sales_recent=12.0,
            image_object_keys=["a.png"],
        ),
        _card(
            sku="FLAT",
            rank=3,
            review_count=400,
            avg_daily_sales_baseline=10.0,
            avg_daily_sales_recent=10.0,
        ),
        _card(sku="TINY", rank=4, review_count=10),
    ]
    report = filter_niche_top_cards(
        niche_key="electronics",
        marketplace="Wildberries",
        cards=cards,
        config=VisualAuditFilterConfig(top_n=50),
    )
    assert [c.sku for c in report.brand_dominant] == ["GIANT"]
    assert [c.sku for c in report.rising_stars] == ["STAR"]
    assert [c.sku for c in report.vision_queue] == ["STAR"]
    assert "GIANT" not in {c.sku for c in report.vision_queue}
    assert report.marketplace == "wildberries"


def test_generator_config_strips_brand_dominant_and_keeps_money_triggers() -> None:
    report = filter_niche_top_cards(
        niche_key="home",
        marketplace="ozon",
        cards=[
            _card(sku="GIANT", rank=1, review_count=8000),
            _card(
                sku="STAR",
                rank=2,
                review_count=250,
                review_count_delta=30,
                avg_daily_sales_baseline=5.0,
                avg_daily_sales_recent=8.0,
                image_object_keys=["s.png"],
            ),
        ],
    )
    dissection = RisingStarVisionDissection(
        sku="STAR",
        first_slide_pain_hooks=[
            RisingStarPainHook(
                pain="скрип механизма",
                visual_device="плашка Не скрипит",
                placement="top-right",
            )
        ],
        infographic_structure="product-center, 3 benefit badges right",
        contrast_accents=["orange on dark", "white offer bar"],
        offer_pattern="2 года гарантии крупным кеглем",
        blind_search_winning_moves=["высокий контраст CTA", "боль на первом экране"],
        money_validated_triggers=["Плашка боли на первом слайде", "Крупный оффер гарантии"],
        avoid_copying=["Не копировать логотип гиганта"],
        confidence=0.88,
        reasoning_trace="Контраст и боль видны сразу.",
    )
    # Poison attempt: brand giant dissection must never enter config.
    giant_poison = RisingStarVisionDissection(
        sku="GIANT",
        first_slide_pain_hooks=[
            RisingStarPainHook(
                pain="бренд",
                visual_device="логотип",
                placement="center",
            )
        ],
        infographic_structure="logo hero",
        contrast_accents=["blue"],
        offer_pattern="бренд",
        blind_search_winning_moves=["logo"],
        money_validated_triggers=["Logo trust"],
        confidence=0.99,
        reasoning_trace="brand",
    )
    config = build_generator_trigger_config(
        filter_report=report,
        dissections=[giant_poison, dissection],
        model_name="claude-opus-4-7",
    )
    assert isinstance(config, GeneratorTriggerConfig)
    assert config.survivor_bias_excluded is True
    assert config.brand_dominant_excluded_skus == ["GIANT"]
    assert config.rising_star_skus == ["STAR"]
    assert all(t.source_sku == "STAR" for t in config.money_validated_triggers)
    assert len(config.money_validated_triggers) == 2
    assert "Не копировать" in " ".join(config.generator_directives.forbidden_brand_mimicry)


class _FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {"rising/sku1.png": _MIN_PNG}

    async def download_bytes(self, *, object_key: str, max_bytes: int) -> bytes:
        data = self.objects[object_key]
        if len(data) > max_bytes:
            raise ValueError("too large")
        return data


class _FakeVision:
    model_name = "claude-opus-4-7"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def dissect_rising_star_visuals(
        self,
        *,
        sku: str,
        title: str | None,
        product_category: str | None,
        sales_growth_ratio: float | None,
        review_velocity_per_day: float,
        review_count: int,
        images: tuple[tuple[bytes, str], ...],
        user_id=None,
        job_id=None,
    ):
        self.calls.append(sku)
        assert images
        return (
            RisingStarVisionDissection(
                sku=sku,
                first_slide_pain_hooks=[
                    RisingStarPainHook(
                        pain="слабый пластик",
                        visual_device="усиленный корпус",
                        placement="left",
                    )
                ],
                infographic_structure="split layout",
                contrast_accents=["yellow badge"],
                offer_pattern="комплект 2в1",
                blind_search_winning_moves=["яркий badge"],
                money_validated_triggers=["Badge боли на первом слайде"],
                confidence=0.91,
                reasoning_trace="ok",
            ),
            120,
            60,
        )

    async def aclose(self) -> None:
        return None


class _FakeRepo:
    def __init__(self) -> None:
        self.jobs: dict[UUID, VisualAuditJobView] = {}

    async def create_job(
        self,
        *,
        user_id: UUID,
        niche_key: str,
        marketplace: str,
        cards_payload: list[dict],
        filter_config: dict,
        model_name: str,
        idempotency_key: str | None = None,
    ) -> VisualAuditJobView:
        now = datetime.now(UTC)
        job = VisualAuditJobView(
            id=uuid4(),
            user_id=user_id,
            status=VisualAuditJobStatus.QUEUED,
            celery_task_id=None,
            niche_key=niche_key,
            marketplace=marketplace,
            cards_payload=tuple(cards_payload),
            filter_config=filter_config,
            filter_report=None,
            vision_dissections=None,
            generator_config=None,
            model_name=model_name,
            error_message=None,
            input_tokens=0,
            output_tokens=0,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        self.jobs[job.id] = job
        return job

    async def find_idempotent_job(
        self, *, user_id: UUID, idempotency_key: str
    ) -> VisualAuditJobView | None:
        return None

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> VisualAuditJobView | None:
        job = self.jobs.get(job_id)
        if job is None or job.user_id != user_id:
            return None
        return job

    async def get_job(self, *, job_id: UUID) -> VisualAuditJobView | None:
        return self.jobs.get(job_id)

    async def mark_status(
        self,
        *,
        job_id: UUID,
        status: VisualAuditJobStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> VisualAuditJobView:
        job = self.jobs[job_id]
        updated = VisualAuditJobView(
            id=job.id,
            user_id=job.user_id,
            status=status,
            celery_task_id=celery_task_id or job.celery_task_id,
            niche_key=job.niche_key,
            marketplace=job.marketplace,
            cards_payload=job.cards_payload,
            filter_config=job.filter_config,
            filter_report=job.filter_report,
            vision_dissections=job.vision_dissections,
            generator_config=job.generator_config,
            model_name=job.model_name,
            error_message=error_message if error_message is not None else job.error_message,
            input_tokens=job.input_tokens,
            output_tokens=job.output_tokens,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
            completed_at=completed_at or job.completed_at,
        )
        self.jobs[job_id] = updated
        return updated

    async def save_filter_report(
        self, *, job_id: UUID, filter_report: dict
    ) -> VisualAuditJobView:
        job = self.jobs[job_id]
        updated = VisualAuditJobView(
            id=job.id,
            user_id=job.user_id,
            status=job.status,
            celery_task_id=job.celery_task_id,
            niche_key=job.niche_key,
            marketplace=job.marketplace,
            cards_payload=job.cards_payload,
            filter_config=job.filter_config,
            filter_report=filter_report,
            vision_dissections=job.vision_dissections,
            generator_config=job.generator_config,
            model_name=job.model_name,
            error_message=job.error_message,
            input_tokens=job.input_tokens,
            output_tokens=job.output_tokens,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
            completed_at=job.completed_at,
        )
        self.jobs[job_id] = updated
        return updated

    async def save_filter_checkpoint(
        self,
        *,
        job_id: UUID,
        filter_report: dict,
        next_status: VisualAuditJobStatus,
    ) -> VisualAuditJobView:
        job = self.jobs[job_id]
        updated = VisualAuditJobView(
            id=job.id,
            user_id=job.user_id,
            status=next_status,
            celery_task_id=job.celery_task_id,
            niche_key=job.niche_key,
            marketplace=job.marketplace,
            cards_payload=job.cards_payload,
            filter_config=job.filter_config,
            filter_report=filter_report,
            vision_dissections=job.vision_dissections,
            generator_config=job.generator_config,
            model_name=job.model_name,
            error_message=job.error_message,
            input_tokens=job.input_tokens,
            output_tokens=job.output_tokens,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
            completed_at=job.completed_at,
        )
        self.jobs[job_id] = updated
        return updated

    async def save_final_result(
        self,
        *,
        job_id: UUID,
        vision_dissections: list[dict],
        generator_config: dict,
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> VisualAuditJobView:
        job = self.jobs[job_id]
        updated = VisualAuditJobView(
            id=job.id,
            user_id=job.user_id,
            status=VisualAuditJobStatus.COMPLETED,
            celery_task_id=job.celery_task_id,
            niche_key=job.niche_key,
            marketplace=job.marketplace,
            cards_payload=job.cards_payload,
            filter_config=job.filter_config,
            filter_report=job.filter_report,
            vision_dissections=vision_dissections,
            generator_config=generator_config,
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


@pytest.mark.asyncio
async def test_service_runs_vision_only_on_rising_stars() -> None:
    class _NullCache:
        async def get(self, key: str):
            return None

        async def set(self, key: str, payload: dict, ttl_seconds: int) -> None:
            return None

    repo = _FakeRepo()
    vision = _FakeVision()
    service = VisualAuditService(
        repo,
        storage=_FakeStorage(),
        model_name="claude-opus-4-7",
        max_image_bytes=1_000_000,
        redis_stage_ttl_seconds=60,
        vision=vision,
        stage_cache=_NullCache(),
    )
    request = VisualAuditEnqueueRequest(
        niche_key="gadgets",
        marketplace="wb",
        cards=[
            _card(sku="GIANT", rank=1, review_count=9000),
            _card(
                sku="SKU-1",
                rank=2,
                review_count=150,
                review_count_delta=28,
                avg_daily_sales_baseline=6.0,
                avg_daily_sales_recent=10.0,
                image_object_keys=["rising/sku1.png"],
            ),
        ],
    )
    job, replay = await service.enqueue_audit(user_id=uuid4(), request=request)
    assert replay is False
    completed = await service.run_visual_audit(job_id=job.id)
    assert completed.status == VisualAuditJobStatus.COMPLETED
    assert vision.calls == ["SKU-1"]
    assert completed.generator_config is not None
    assert completed.generator_config["survivor_bias_excluded"] is True
    assert "GIANT" in completed.generator_config["brand_dominant_excluded_skus"]
    assert completed.generator_config["rising_star_skus"] == ["SKU-1"]
    assert len(completed.generator_config["money_validated_triggers"]) >= 1


@pytest.mark.asyncio
async def test_service_not_found() -> None:
    service = VisualAuditService(
        _FakeRepo(),
        storage=_FakeStorage(),
        model_name="claude-opus-4-7",
        max_image_bytes=1000,
        redis_stage_ttl_seconds=60,
    )
    with pytest.raises(VisualAuditNotFoundError):
        await service.get_job_for_user(user_id=uuid4(), job_id=uuid4())


def test_empty_model_name_rejected() -> None:
    with pytest.raises(VisualAuditValidationError):
        VisualAuditService(
            _FakeRepo(),
            storage=_FakeStorage(),
            model_name="  ",
            max_image_bytes=1000,
            redis_stage_ttl_seconds=60,
        )
