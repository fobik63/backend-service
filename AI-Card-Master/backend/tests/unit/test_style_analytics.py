"""Unit tests for style-preset tracking analytics (task 25)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.style_analytics import (
    InsightMetric,
    NicheSelectionAggregate,
    StyleSelectionAggregate,
    build_style_ai_insight,
    build_style_preset_analytics,
)


def test_cover_insight_mentions_ctr_lift() -> None:
    insight = build_style_ai_insight(
        niche_key="perfume",
        niche_title="Парфюмерия",
        slide_key="cover",
        selected_style="studio hero bottle",
        selection_count=320,
        total_selections=1500,
        rank=1,
    )

    assert insight.metric is InsightMetric.CTR
    assert "CTR" in insight.message
    assert insight.estimated_lift_percent >= 15.0
    assert 0.0 <= insight.confidence <= 1.0


def test_style_preset_analytics_json_shape() -> None:
    payload = build_style_preset_analytics(
        generated_at=datetime(2026, 8, 6, 18, 0, tzinfo=UTC),
        period_days=30,
        style_rows=[
            StyleSelectionAggregate(
                niche_key="perfume",
                slide_key="cover",
                selected_style="studio hero bottle",
                selection_count=100,
            ),
            StyleSelectionAggregate(
                niche_key="clothing",
                slide_key="lifestyle",
                selected_style="street/interior lookbook",
                selection_count=40,
            ),
        ],
        niche_rows=[
            NicheSelectionAggregate(niche_key="perfume", selection_count=100),
            NicheSelectionAggregate(niche_key="clothing", selection_count=40),
        ],
        niche_titles={"perfume": "Парфюмерия", "clothing": "Одежда"},
        top_limit=10,
    )

    assert payload.total_selections == 140
    assert payload.unique_presets == 2
    assert len(payload.top_presets) == 2
    assert payload.top_presets[0].rank == 1
    assert payload.top_presets[0].niche_key == "perfume"
    assert payload.top_presets[0].share_percent == 71.4
    assert "повышает CTR" in payload.top_presets[0].ai_insight.message
    assert len(payload.by_niche) == 2
    assert payload.by_niche[0].top_style == "studio hero bottle"
    assert len(payload.ai_recommendations) == 2
    assert payload.ai_recommendations[0].priority.value == "high"
    assert "studio hero bottle" in payload.ai_recommendations[0].message


def test_empty_tracking_returns_empty_collections() -> None:
    payload = build_style_preset_analytics(
        generated_at=datetime(2026, 8, 6, tzinfo=UTC),
        period_days=7,
        style_rows=[],
        niche_rows=[],
        niche_titles={},
    )

    assert payload.total_selections == 0
    assert payload.unique_presets == 0
    assert payload.top_presets == ()
    assert payload.by_niche == ()
    assert payload.ai_recommendations == ()
