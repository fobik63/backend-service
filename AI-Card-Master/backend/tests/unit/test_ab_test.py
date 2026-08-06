"""Unit tests for Automated A/B Testing Logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.application.ab_test_service import (
    AbTestNotFoundError,
    AbTestService,
)
from app.domain.ab_test import (
    CANONICAL_STRATEGIES,
    AbCreativeStrategy,
    AbEnqueueRequest,
    AbExperimentStatus,
    AbExperimentView,
    AbProductBrief,
    AbTestConfig,
    AbVariantHypothesis,
    AbVariantMetrics,
    AbVariantStatus,
    AbVariantView,
    build_deterministic_hypotheses,
    build_resolution_result,
    compute_ctr_pct,
    is_measurement_complete,
    measurement_window_end,
    normalize_hypotheses,
    select_winner_variant,
)


def _product(**kwargs) -> AbProductBrief:
    base = {
        "sku": "SKU-1",
        "title": "Крем для лица 50 мл",
        "niche_key": "beauty-cream",
        "marketplace": "wildberries",
        "category": "beauty",
        "key_benefits": ["увлажнение 24ч", "SPF"],
        "pain_points": ["сухая кожа", "стянутость"],
        "current_offer": "-25% сегодня",
        "nm_id": "123456",
        "campaign_id": "99",
    }
    base.update(kwargs)
    return AbProductBrief.model_validate(base)


def _variant_view(
    *,
    strategy: AbCreativeStrategy,
    position: int,
    ctr_pct: float,
    impressions: int = 1000,
    clicks: int | None = None,
    status: AbVariantStatus = AbVariantStatus.MEASURING,
    experiment_id: UUID | None = None,
) -> AbVariantView:
    eid = experiment_id or uuid4()
    computed_clicks = clicks if clicks is not None else int(impressions * ctr_pct / 100)
    now = datetime.now(UTC)
    return AbVariantView(
        id=uuid4(),
        experiment_id=eid,
        position=position,
        strategy=strategy,
        status=status,
        title=f"{strategy.value} title",
        main_image_brief="brief",
        offer_hook="offer",
        headline="headline",
        rationale="rationale",
        prompt_for_generator="prompt",
        confidence=0.7,
        ads_creative_id=f"creative-{strategy.value}",
        ads_campaign_id="99",
        marketplace_media_id=f"media-{strategy.value}",
        impressions=impressions,
        clicks=computed_clicks,
        ctr_pct=ctr_pct,
        spend=10.0,
        metrics_sampled_at=now,
        error_message=None,
        created_at=now,
        updated_at=now,
    )


def test_canonical_strategies_are_exactly_three() -> None:
    assert len(CANONICAL_STRATEGIES) == 3
    assert AbCreativeStrategy.PAIN_HOOK in CANONICAL_STRATEGIES
    assert AbCreativeStrategy.SOCIAL_PROOF in CANONICAL_STRATEGIES
    assert AbCreativeStrategy.OFFER_URGENCY in CANONICAL_STRATEGIES


def test_compute_ctr_pct() -> None:
    assert compute_ctr_pct(impressions=1000, clicks=35) == 3.5
    assert compute_ctr_pct(impressions=0, clicks=0) == 0.0


def test_deterministic_hypotheses_cover_all_strategies() -> None:
    hyps = build_deterministic_hypotheses(_product())
    assert len(hyps) == 3
    assert [h.strategy for h in hyps] == list(CANONICAL_STRATEGIES)
    assert all(h.title and h.main_image_brief for h in hyps)


def test_normalize_hypotheses_rejects_missing_strategy() -> None:
    hyps = list(build_deterministic_hypotheses(_product()))[:-1]
    with pytest.raises(ValueError, match="missing"):
        normalize_hypotheses(hyps)


def test_measurement_window_is_seven_days_by_default() -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    end = measurement_window_end(started_at=start, duration_days=7)
    assert end == start + timedelta(days=7)
    assert not is_measurement_complete(
        measurement_ends_at=end,
        now=start + timedelta(days=6),
    )
    assert is_measurement_complete(
        measurement_ends_at=end,
        now=start + timedelta(days=7),
    )


def test_select_winner_by_highest_ctr() -> None:
    eid = uuid4()
    variants = (
        _variant_view(
            strategy=AbCreativeStrategy.PAIN_HOOK,
            position=0,
            ctr_pct=2.1,
            experiment_id=eid,
        ),
        _variant_view(
            strategy=AbCreativeStrategy.SOCIAL_PROOF,
            position=1,
            ctr_pct=3.4,
            experiment_id=eid,
        ),
        _variant_view(
            strategy=AbCreativeStrategy.OFFER_URGENCY,
            position=2,
            ctr_pct=2.8,
            experiment_id=eid,
        ),
    )
    winner, notes = select_winner_variant(
        variants,
        config=AbTestConfig(min_impressions_for_decision=100),
    )
    assert winner is not None
    assert winner.strategy == AbCreativeStrategy.SOCIAL_PROOF
    assert any("Победитель" in n for n in notes)


def test_build_resolution_marks_losers() -> None:
    eid = uuid4()
    variants = (
        _variant_view(
            strategy=AbCreativeStrategy.PAIN_HOOK,
            position=0,
            ctr_pct=1.0,
            experiment_id=eid,
        ),
        _variant_view(
            strategy=AbCreativeStrategy.SOCIAL_PROOF,
            position=1,
            ctr_pct=4.0,
            experiment_id=eid,
        ),
        _variant_view(
            strategy=AbCreativeStrategy.OFFER_URGENCY,
            position=2,
            ctr_pct=2.0,
            experiment_id=eid,
        ),
    )
    result = build_resolution_result(
        variants=variants,
        config=AbTestConfig(),
        deleted_variant_ids=[variants[0].id, variants[2].id],
    )
    assert result.winner_strategy == AbCreativeStrategy.SOCIAL_PROOF
    assert set(result.loser_variant_ids) == {variants[0].id, variants[2].id}
    assert set(result.deleted_variant_ids) == {variants[0].id, variants[2].id}


class _FakeRepo:
    def __init__(self) -> None:
        self.experiments: dict[UUID, AbExperimentView] = {}

    async def create_experiment(self, **kwargs) -> AbExperimentView:
        eid = uuid4()
        now = datetime.now(UTC)
        variants = tuple(
            AbVariantView(
                id=uuid4(),
                experiment_id=eid,
                position=i,
                strategy=s,
                status=AbVariantStatus.PENDING,
                title=None,
                main_image_brief=None,
                offer_hook=None,
                headline=None,
                rationale=None,
                prompt_for_generator=None,
                confidence=None,
                ads_creative_id=None,
                ads_campaign_id=None,
                marketplace_media_id=None,
                impressions=0,
                clicks=0,
                ctr_pct=0.0,
                spend=None,
                metrics_sampled_at=None,
                error_message=None,
                created_at=now,
                updated_at=now,
            )
            for i, s in enumerate(kwargs["strategies"])
        )
        view = AbExperimentView(
            id=eid,
            user_id=kwargs["user_id"],
            status=AbExperimentStatus.QUEUED,
            celery_task_id=None,
            marketplace=kwargs["marketplace"],
            niche_key=kwargs["niche_key"],
            sku=kwargs["sku"],
            nm_id=kwargs.get("nm_id"),
            campaign_id=kwargs.get("campaign_id"),
            model_name=kwargs["model_name"],
            product_payload=kwargs["product_payload"],
            config=kwargs["config"],
            hypotheses_payload=None,
            resolution_result=None,
            winner_variant_id=None,
            measurement_started_at=None,
            measurement_ends_at=None,
            error_message=None,
            input_tokens=0,
            output_tokens=0,
            created_at=now,
            updated_at=now,
            completed_at=None,
            variants=variants,
        )
        self.experiments[eid] = view
        return view

    async def find_idempotent_experiment(self, **kwargs):
        return None

    async def get_experiment_for_user(self, *, user_id, experiment_id):
        exp = self.experiments.get(experiment_id)
        if exp is None or exp.user_id != user_id:
            return None
        return exp

    async def get_experiment(self, *, experiment_id, include_variants=True):
        return self.experiments.get(experiment_id)

    async def list_experiments_for_user(self, **kwargs):
        return tuple(self.experiments.values())

    async def list_active_measuring(self, **kwargs):
        return tuple(
            e
            for e in self.experiments.values()
            if e.status == AbExperimentStatus.MEASURING
        )

    async def list_due_for_resolution(self, **kwargs):
        return ()

    async def mark_status(self, *, experiment_id, status, **kwargs):
        exp = self.experiments[experiment_id]
        updated = AbExperimentView(
            **{
                **exp.__dict__,
                "status": status,
                "celery_task_id": kwargs.get("celery_task_id", exp.celery_task_id),
                "error_message": kwargs.get("error_message", exp.error_message),
                "completed_at": kwargs.get("completed_at", exp.completed_at),
                "measurement_started_at": kwargs.get(
                    "measurement_started_at", exp.measurement_started_at
                ),
                "measurement_ends_at": kwargs.get(
                    "measurement_ends_at", exp.measurement_ends_at
                ),
                "winner_variant_id": kwargs.get(
                    "winner_variant_id", exp.winner_variant_id
                ),
                "resolution_result": kwargs.get(
                    "resolution_result", exp.resolution_result
                ),
                "updated_at": datetime.now(UTC),
            }
        )
        self.experiments[experiment_id] = updated
        return updated

    async def save_hypotheses(self, *, experiment_id, hypotheses, **kwargs):
        return self.experiments[experiment_id]

    async def update_variant(self, **kwargs):
        raise NotImplementedError

    async def save_final_resolution(self, **kwargs):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_enqueue_creates_three_pending_slots() -> None:
    repo = _FakeRepo()
    service = AbTestService(
        repo,
        model_name="claude-test",
        redis_stage_ttl_seconds=60,
        default_config=AbTestConfig(duration_days=7),
    )
    request = AbEnqueueRequest(product=_product())
    experiment, replay = await service.enqueue_experiment(
        user_id=uuid4(),
        request=request,
    )
    assert replay is False
    assert experiment.status == AbExperimentStatus.QUEUED
    assert len(experiment.variants) == 3
    assert [v.strategy for v in experiment.variants] == list(CANONICAL_STRATEGIES)


@pytest.mark.asyncio
async def test_get_experiment_not_found() -> None:
    service = AbTestService(
        _FakeRepo(),
        model_name="claude-test",
        redis_stage_ttl_seconds=60,
    )
    with pytest.raises(AbTestNotFoundError):
        await service.get_experiment_for_user(user_id=uuid4(), experiment_id=uuid4())


def test_preview_hypotheses() -> None:
    service = AbTestService(
        _FakeRepo(),
        model_name="claude-test",
        redis_stage_ttl_seconds=60,
    )
    preview = service.preview_hypotheses(AbEnqueueRequest(product=_product()))
    assert len(preview) == 3
    assert isinstance(preview[0], AbVariantHypothesis)


def test_config_requires_three_variants() -> None:
    with pytest.raises(Exception):
        AbTestConfig(variant_count=2)


def test_variant_metrics_rejects_clicks_over_impressions() -> None:
    with pytest.raises(Exception):
        AbVariantMetrics(impressions=10, clicks=11, ctr_pct=110.0)
