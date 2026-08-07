"""Unit tests for BrandDNA analysis and prompt injection (plan §58)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.application.brand_dna_service import BrandDNAService
from app.domain.brand_dna import (
    BrandDNAContext,
    BrandDNAStatus,
    BrandDNAView,
    SuccessfulGenerationSample,
    analyze_successful_generations,
    apply_brand_dna_to_prompt,
    apply_brand_dna_to_style,
    build_claude_context,
    build_midjourney_context,
    mix_claude_system_prompt,
    mix_claude_user_prompt,
)


def _sample(
    *,
    styles: tuple[str, ...] = ("luxury loft golden hour",),
    prompts: tuple[str, ...] = (
        "soft studio lighting beige palette minimal composition product card",
    ),
    category: str | None = "home decor",
) -> SuccessfulGenerationSample:
    return SuccessfulGenerationSample(
        job_id=uuid4(),
        product_category=category,
        selected_styles=styles,
        prompts=prompts,
        completed_at=datetime.now(UTC),
    )


def test_analyze_successful_generations_extracts_signals() -> None:
    signals = analyze_successful_generations(
        (
            _sample(),
            _sample(
                styles=("luxury loft soft light",),
                prompts=("golden lighting beige palette infographic layout",),
            ),
        )
    )
    assert signals is not None
    assert signals.sample_count == 2
    assert signals.dominant_styles
    assert "luxury loft golden hour" in signals.dominant_styles or any(
        "luxury" in style for style in signals.dominant_styles
    )
    mj = build_midjourney_context(signals)
    claude = build_claude_context(signals)
    assert "brand" in mj.lower() or "palette" in mj.lower()
    assert "Preserve brand" in claude or "brand" in claude.lower()


def test_analyze_returns_none_without_samples() -> None:
    assert analyze_successful_generations(()) is None


def test_apply_brand_dna_to_midjourney_prompt_is_idempotent() -> None:
    dna = BrandDNAContext(
        id=uuid4(),
        user_id=uuid4(),
        midjourney_context="consistent seller brand identity, brand palette: beige",
        claude_context="Keep tone consistent.",
        dominant_styles=("luxury loft",),
        sample_count=3,
    )
    once = apply_brand_dna_to_prompt("product on marble table", dna)
    twice = apply_brand_dna_to_prompt(once, dna)
    assert once.count("[BrandDNA]") == 1
    assert once == twice
    styled = apply_brand_dna_to_style("minimal studio", dna)
    assert "beige" in styled or "brand" in styled.lower()


def test_mix_claude_prompts_inject_brand_dna() -> None:
    system = mix_claude_system_prompt("You are a copywriter.", "Use soft luxury tone.")
    assert "[BrandDNA Context]" in system
    assert "soft luxury tone" in system
    user = mix_claude_user_prompt("Write a title.", "Use soft luxury tone.")
    assert "[BrandDNA Context]" in user
    # Idempotent
    assert mix_claude_system_prompt(system, "Use soft luxury tone.") == system


class _FakePersistence:
    def __init__(self) -> None:
        self.row: BrandDNAView | None = None

    async def get_by_user_id(self, user_id: UUID) -> BrandDNAView | None:
        if self.row is None or self.row.user_id != user_id:
            return None
        return self.row

    async def get_active_for_user(self, user_id: UUID) -> BrandDNAView | None:
        view = await self.get_by_user_id(user_id)
        if view is None or not view.is_active:
            return None
        if view.status not in {BrandDNAStatus.READY, BrandDNAStatus.STALE}:
            return None
        return view

    async def upsert_from_signals(self, **kwargs: object) -> BrandDNAView:
        from app.domain.brand_dna import BrandDNASignals

        signals = kwargs["signals"]
        assert isinstance(signals, BrandDNASignals)
        user_id = kwargs["user_id"]
        assert isinstance(user_id, UUID)
        now = datetime.now(UTC)
        version = 1 if self.row is None else self.row.version + 1
        self.row = BrandDNAView(
            id=self.row.id if self.row else uuid4(),
            user_id=user_id,
            status=BrandDNAStatus.READY,
            is_active=True,
            midjourney_context=str(kwargs["midjourney_context"]),
            claude_context=str(kwargs["claude_context"]),
            dominant_styles=signals.dominant_styles,
            palette_keywords=signals.palette_keywords,
            lighting_mood=signals.lighting_mood,
            composition_keywords=signals.composition_keywords,
            category_hints=signals.category_hints,
            sample_count=signals.sample_count,
            source_job_ids=signals.source_job_ids,
            version=version,
            last_analyzed_at=now,
            created_at=now,
            updated_at=now,
        )
        return self.row

    async def mark_analyzing(self, user_id: UUID) -> BrandDNAView | None:
        now = datetime.now(UTC)
        if self.row is None:
            self.row = BrandDNAView(
                id=uuid4(),
                user_id=user_id,
                status=BrandDNAStatus.ANALYZING,
                is_active=True,
                midjourney_context=None,
                claude_context=None,
                dominant_styles=(),
                palette_keywords=(),
                lighting_mood=(),
                composition_keywords=(),
                category_hints=(),
                sample_count=0,
                source_job_ids=(),
                version=1,
                last_analyzed_at=None,
                created_at=now,
                updated_at=now,
            )
        else:
            prev = self.row
            self.row = BrandDNAView(
                id=prev.id,
                user_id=prev.user_id,
                status=BrandDNAStatus.ANALYZING,
                is_active=prev.is_active,
                midjourney_context=prev.midjourney_context,
                claude_context=prev.claude_context,
                dominant_styles=prev.dominant_styles,
                palette_keywords=prev.palette_keywords,
                lighting_mood=prev.lighting_mood,
                composition_keywords=prev.composition_keywords,
                category_hints=prev.category_hints,
                sample_count=prev.sample_count,
                source_job_ids=prev.source_job_ids,
                version=prev.version,
                last_analyzed_at=prev.last_analyzed_at,
                created_at=prev.created_at,
                updated_at=now,
            )
        return self.row

    async def set_active(self, *, user_id: UUID, is_active: bool) -> BrandDNAView | None:
        if self.row is None or self.row.user_id != user_id:
            return None
        prev = self.row
        self.row = BrandDNAView(
            id=prev.id,
            user_id=prev.user_id,
            status=prev.status,
            is_active=is_active,
            midjourney_context=prev.midjourney_context,
            claude_context=prev.claude_context,
            dominant_styles=prev.dominant_styles,
            palette_keywords=prev.palette_keywords,
            lighting_mood=prev.lighting_mood,
            composition_keywords=prev.composition_keywords,
            category_hints=prev.category_hints,
            sample_count=prev.sample_count,
            source_job_ids=prev.source_job_ids,
            version=prev.version,
            last_analyzed_at=prev.last_analyzed_at,
            created_at=prev.created_at,
            updated_at=datetime.now(UTC),
        )
        return self.row


class _FakeSamples:
    def __init__(self, samples: tuple[SuccessfulGenerationSample, ...]) -> None:
        self._samples = samples

    async def list_successful_samples(
        self,
        *,
        user_id: UUID,
        limit: int,
    ) -> tuple[SuccessfulGenerationSample, ...]:
        _ = user_id
        return self._samples[:limit]


@pytest.mark.asyncio
async def test_brand_dna_service_refresh_and_context() -> None:
    user_id = uuid4()
    persistence = _FakePersistence()
    service = BrandDNAService(
        persistence,
        _FakeSamples((_sample(), _sample())),
        sample_limit=10,
        min_samples=1,
        enabled=True,
    )
    view = await service.refresh_from_successful_generations(user_id=user_id)
    assert view is not None
    assert view.status is BrandDNAStatus.READY
    assert view.midjourney_context
    assert view.claude_context
    ctx = await service.get_active_context(user_id=user_id)
    assert ctx is not None
    assert "[BrandDNA]" in apply_brand_dna_to_prompt("base prompt", ctx)
