"""Unit tests for Eye of God spy dashboard aggregation + discovery parsing."""

from __future__ import annotations

from app.domain.competitor_audit import (
    ActionableBlueprint,
    CompetitorCardDeepAnalysis,
    CompetitorCardScrapeResult,
    CompetitorMarketplace,
    CompetitorSpecRow,
    MarketGapVector,
    SemanticAuditVector,
    VisualAuditVector,
)
from app.domain.eye_of_god_spy import (
    CompetitorDiscoveryHit,
    EyeOfGodSpyEnqueueRequest,
    build_eye_of_god_dashboard,
)
from app.infrastructure.competitor_audit.wb_discovery_client import _extract_products


def _blueprint(**kwargs: object) -> ActionableBlueprint:
    base = {
        "background": "Светлый loft с мягким софтбоксом слева",
        "pain_badges": ["Без парабенов", "24ч увлажнение"],
        "generator_prompt": "Собери карточку лучше конкурентов с контрастными плашками",
        "first_slide_offers": ["Эко-формула", "Быстро впитывается"],
        "avoid_copying": ["Логотип гиганта"],
    }
    base.update(kwargs)
    return ActionableBlueprint.model_validate(base)


def _analysis(article: str, **kwargs: object) -> CompetitorCardDeepAnalysis:
    payload = {
        "article": article,
        "marketplace": "wildberries",
        "title": f"Товар {article}",
        "competitor_weaknesses": ["Слабый первый слайд", "Мелкий шрифт"],
        "conversion_triggers": ["До/после", "Гарантия результата"],
        "actionable_blueprint": _blueprint(),
        "insufficient_data": False,
        "visual_audit": VisualAuditVector(
            color_palette=["#0f172a", "#f59e0b"],
            first_slide_offer_layout="Оффер слева, продукт справа",
            font_readability="Средняя",
            blind_zones=["Нет состава на первом слайде"],
        ),
        "semantic_audit": SemanticAuditVector(),
        "market_gap": MarketGapVector(),
        "confidence": 0.8,
        "reasoning_trace": "ok",
        "advice_reliability_pct": 82.0,
    }
    payload.update(kwargs)
    return CompetitorCardDeepAnalysis.model_validate(payload)


def test_eye_of_god_enqueue_request_defaults() -> None:
    req = EyeOfGodSpyEnqueueRequest(input="12345678", platform="wb")
    assert req.limit == 10
    assert req.platform == "wb"


def test_build_dashboard_aggregates_badges_triggers_keywords() -> None:
    discovery = [
        CompetitorDiscoveryHit(
            rank=1,
            article="111",
            url="https://www.wildberries.ru/catalog/111/detail.aspx",
            marketplace=CompetitorMarketplace.WILDBERRIES,
            title="Крем для рук увлажнение",
            brand="BrandA",
            price_rub=499.0,
        ),
        CompetitorDiscoveryHit(
            rank=2,
            article="222",
            url="https://www.wildberries.ru/catalog/222/detail.aspx",
            marketplace=CompetitorMarketplace.WILDBERRIES,
            title="Крем для рук питание",
            brand="BrandB",
            price_rub=590.0,
        ),
    ]
    scrapes = [
        CompetitorCardScrapeResult(
            source_url=discovery[0].url,
            marketplace=CompetitorMarketplace.WILDBERRIES,
            article="111",
            title="Крем для рук увлажнение",
            brand="BrandA",
            description="Увлажнение кожи шалфей",
            specs=[CompetitorSpecRow(name="Объём", value="75 мл")],
        ),
        CompetitorCardScrapeResult(
            source_url=discovery[1].url,
            marketplace=CompetitorMarketplace.WILDBERRIES,
            article="222",
            title="Крем для рук питание",
            brand="BrandB",
            description="Питание и увлажнение",
            specs=[CompetitorSpecRow(name="Объём", value="100 мл")],
        ),
    ]
    analyses = [
        _analysis("111"),
        _analysis(
            "222",
            conversion_triggers=["До/после", "Клинический эффект"],
            actionable_blueprint=_blueprint(
                pain_badges=["Без парабенов", "Клинический эффект"],
            ),
        ),
    ]

    dashboard = build_eye_of_god_dashboard(
        seed_article="111",
        seed_marketplace=CompetitorMarketplace.WILDBERRIES,
        seed_title="Крем для рук",
        discovery=discovery,
        scrape_cards=scrapes,
        analysis_cards=analyses,
    )

    assert dashboard.competitors_analyzed == 2
    assert len(dashboard.competitors) == 2
    assert dashboard.badge_patterns
    assert any("парабенов" in item.text.casefold() for item in dashboard.badge_patterns)
    assert dashboard.strong_triggers
    assert any("до/после" in item.text.casefold() for item in dashboard.strong_triggers)
    assert dashboard.frequent_keywords
    assert dashboard.visual_hooks
    assert dashboard.ai_recommendation
    assert dashboard.generator_prompt


def test_extract_wb_search_products() -> None:
    payload = {
        "data": {
            "products": [
                {"id": 1, "name": "A"},
                {"id": 2, "name": "B"},
            ]
        }
    }
    assert len(_extract_products(payload)) == 2
