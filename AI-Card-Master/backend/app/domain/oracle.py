"""Market Gap & Trend Prediction (The Oracle).

Pipeline:
1. Ingest marketplace search-query demand signals (volume + growth).
2. Match each design/style cluster against current top-card supply.
3. When demand rises and top cards are scarce → emit a niche alert:
   «Обнаружена ниша! Сделай инфографику в стиле X, чтобы забрать трафик».
4. Optionally enrich gaps via Claude JSON Mode (style naming + action plan).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OracleJobStatus(StrEnum):
    """Lifecycle of an async Oracle prediction job."""

    QUEUED = "queued"
    SCANNING = "scanning"
    ENRICHING = "enriching"
    COMPLETED = "completed"
    FAILED = "failed"


class GapSeverity(StrEnum):
    """How urgent / large the detected market gap is."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class StrictDomainModel(BaseModel):
    """Strict Pydantic v2 base for Oracle payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)


class OracleGapConfig(StrictDomainModel):
    """Tunable thresholds for demand-vs-supply niche detection."""

    min_query_growth_ratio: float = Field(default=0.25, ge=0.0, le=10.0)
    min_recent_query_volume: int = Field(default=500, ge=1, le=10_000_000)
    max_top_cards_for_gap: int = Field(default=3, ge=0, le=50)
    min_gap_score: float = Field(default=40.0, ge=0.0, le=100.0)
    max_alerts: int = Field(default=10, ge=1, le=50)
    top_rank_ceiling: int = Field(default=50, ge=1, le=500)

    @model_validator(mode="after")
    def _validate_bands(self) -> OracleGapConfig:
        if self.max_top_cards_for_gap > self.top_rank_ceiling:
            raise ValueError(
                "max_top_cards_for_gap must be <= top_rank_ceiling."
            )
        return self


class SearchQuerySignal(StrictDomainModel):
    """One marketplace search query with demand dynamics."""

    query_text: str = Field(min_length=1, max_length=256)
    design_style: str = Field(min_length=1, max_length=128)
    niche_key: str = Field(min_length=1, max_length=128)
    baseline_volume: int = Field(ge=0, le=100_000_000)
    recent_volume: int = Field(ge=0, le=100_000_000)
    observation_days: int = Field(default=14, ge=1, le=90)
    related_queries: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("query_text", "design_style", "niche_key", mode="before")
    @classmethod
    def _strip_required(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("related_queries", mode="before")
    @classmethod
    def _clean_related(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("related_queries must be a list of strings.")
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("related_queries items must be strings.")
            text = item.strip()
            if text:
                cleaned.append(text[:256])
        return cleaned[:20]


class SupplyCardSignal(StrictDomainModel):
    """One top-card listing that currently covers (or fails to cover) demand."""

    sku: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=500)
    rank: int = Field(ge=1, le=10_000)
    design_style: str = Field(min_length=1, max_length=128)
    niche_key: str = Field(min_length=1, max_length=128)
    review_count: int = Field(default=0, ge=0, le=10_000_000)
    matched_query: str | None = Field(default=None, max_length=256)

    @field_validator("sku", "design_style", "niche_key", mode="before")
    @classmethod
    def _strip_required(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class StyleDemandCluster(StrictDomainModel):
    """Aggregated demand for one design style inside a niche."""

    design_style: str = Field(min_length=1, max_length=128)
    niche_key: str = Field(min_length=1, max_length=128)
    query_count: int = Field(ge=0)
    baseline_volume: int = Field(ge=0)
    recent_volume: int = Field(ge=0)
    growth_ratio: float
    primary_query: str = Field(min_length=1, max_length=256)
    related_queries: list[str] = Field(default_factory=list, max_length=40)


class StyleSupplySnapshot(StrictDomainModel):
    """How many top cards currently serve a design style."""

    design_style: str = Field(min_length=1, max_length=128)
    niche_key: str = Field(min_length=1, max_length=128)
    top_card_count: int = Field(ge=0)
    best_rank: int | None = Field(default=None, ge=1)
    skus: list[str] = Field(default_factory=list, max_length=50)


class NicheGapOpportunity(StrictDomainModel):
    """Detected demand/supply imbalance for a design style."""

    design_style: str = Field(min_length=1, max_length=128)
    niche_key: str = Field(min_length=1, max_length=128)
    primary_query: str = Field(min_length=1, max_length=256)
    related_queries: list[str] = Field(default_factory=list, max_length=40)
    baseline_volume: int = Field(ge=0)
    recent_volume: int = Field(ge=0)
    growth_ratio: float
    top_card_count: int = Field(ge=0)
    best_rank: int | None = None
    gap_score: float = Field(ge=0.0, le=100.0)
    severity: GapSeverity
    notification_message: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)


class ClaudeGapEnrichment(StrictDomainModel):
    """Claude JSON enrichment for one detected niche gap."""

    design_style: str = Field(min_length=1, max_length=128)
    refined_style_label: str = Field(min_length=1, max_length=128)
    notification_message: str = Field(min_length=1, max_length=500)
    infographic_brief: str = Field(min_length=1, max_length=800)
    traffic_capture_tips: list[str] = Field(min_length=1, max_length=12)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_trace: str = Field(min_length=1, max_length=4000)


class OracleScanReport(StrictDomainModel):
    """Deterministic pre-Claude gap scan result."""

    marketplace: str = Field(min_length=1, max_length=32)
    niche_key: str = Field(min_length=1, max_length=128)
    config: OracleGapConfig
    scanned_queries: int = Field(ge=0)
    scanned_supply_cards: int = Field(ge=0)
    demand_clusters: list[StyleDemandCluster] = Field(default_factory=list)
    supply_snapshots: list[StyleSupplySnapshot] = Field(default_factory=list)
    opportunities: list[NicheGapOpportunity] = Field(default_factory=list)
    scan_notes: list[str] = Field(default_factory=list, max_length=40)


class OraclePredictionResult(StrictDomainModel):
    """Final Oracle output: gaps + Claude-enriched niche alerts."""

    schema_version: str = Field(default="1.0", min_length=1, max_length=16)
    marketplace: str = Field(min_length=1, max_length=32)
    niche_key: str = Field(min_length=1, max_length=128)
    opportunities: list[NicheGapOpportunity] = Field(default_factory=list)
    enrichments: list[ClaudeGapEnrichment] = Field(default_factory=list)
    notifications: list[str] = Field(default_factory=list, max_length=50)
    model_name: str = Field(min_length=1, max_length=128)
    confidence_score: float = Field(ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list, max_length=40)


class OracleEnqueueRequest(StrictDomainModel):
    """API/domain request to run The Oracle on a niche."""

    niche_key: str = Field(min_length=1, max_length=128)
    marketplace: str = Field(min_length=1, max_length=32)
    search_queries: list[SearchQuerySignal] = Field(min_length=1, max_length=500)
    supply_cards: list[SupplyCardSignal] = Field(default_factory=list, max_length=500)
    gap_config: OracleGapConfig | None = None

    @field_validator("marketplace", "niche_key", mode="before")
    @classmethod
    def _strip_keys(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


@dataclass(frozen=True, slots=True)
class OracleJobView:
    """Projection of a persisted Oracle prediction job."""

    id: UUID
    user_id: UUID
    status: OracleJobStatus
    celery_task_id: str | None
    niche_key: str
    marketplace: str
    queries_payload: tuple[dict[str, Any], ...]
    supply_payload: tuple[dict[str, Any], ...]
    gap_config: dict[str, Any]
    scan_report: dict[str, Any] | None
    prediction_result: dict[str, Any] | None
    notifications: list[str] | None
    model_name: str
    error_message: str | None
    input_tokens: int
    output_tokens: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


ORACLE_ENRICHMENT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "gaps",
        "reasoning_trace",
    ],
    "properties": {
        "gaps": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "design_style",
                    "refined_style_label",
                    "notification_message",
                    "infographic_brief",
                    "traffic_capture_tips",
                    "confidence",
                ],
                "properties": {
                    "design_style": {"type": "string"},
                    "refined_style_label": {"type": "string"},
                    "notification_message": {"type": "string"},
                    "infographic_brief": {"type": "string"},
                    "traffic_capture_tips": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                    "confidence": {"type": "number"},
                },
            },
        },
        "reasoning_trace": {"type": "string"},
    },
}


_ORACLE_SYSTEM_PROMPT = (
    "You are The Oracle — a marketplace trend forecaster for Wildberries and Ozon. "
    "You receive deterministic market-gap candidates: search demand is rising while "
    "top-card supply for a design style is scarce. "
    "Refine the style label, keep the Russian niche notification format "
    "«Обнаружена ниша! Сделай инфографику в стиле X, чтобы забрать трафик», "
    "and produce a concrete infographic brief to capture the traffic. "
    "Return ONLY valid JSON matching the schema. Do not invent demand/supply numbers."
)


def oracle_system_prompt() -> str:
    return _ORACLE_SYSTEM_PROMPT


def build_niche_notification(design_style: str) -> str:
    """Canonical Russian niche alert for UI / push."""

    style = _normalize_style(design_style) or "X"
    return (
        f"Обнаружена ниша! Сделай инфографику в стиле {style}, "
        f"чтобы забрать трафик"
    )


def _normalize_style(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip())
    return cleaned[:128]


def _style_key(value: str) -> str:
    return _normalize_style(value).casefold()


def compute_growth_ratio(*, baseline_volume: int, recent_volume: int) -> float:
    """Relative growth of search demand (recent vs baseline)."""

    if baseline_volume <= 0:
        return float(recent_volume) if recent_volume > 0 else 0.0
    return (recent_volume - baseline_volume) / float(baseline_volume)


def severity_from_gap_score(score: float) -> GapSeverity:
    if score >= 85.0:
        return GapSeverity.CRITICAL
    if score >= 70.0:
        return GapSeverity.HIGH
    if score >= 55.0:
        return GapSeverity.MEDIUM
    return GapSeverity.LOW


def compute_gap_score(
    *,
    growth_ratio: float,
    recent_volume: int,
    top_card_count: int,
    config: OracleGapConfig,
) -> float:
    """0–100 score: high demand growth + scarce top supply → high gap."""

    growth_component = min(max(growth_ratio, 0.0) / max(config.min_query_growth_ratio, 1e-6), 3.0)
    volume_component = min(
        math.log1p(recent_volume) / math.log1p(max(config.min_recent_query_volume, 1)),
        2.0,
    )
    scarcity = 1.0 - (
        min(top_card_count, config.max_top_cards_for_gap + 1)
        / float(config.max_top_cards_for_gap + 1)
    )
    raw = (0.45 * growth_component + 0.25 * volume_component + 0.30 * scarcity * 2.0) * 40.0
    return round(min(max(raw, 0.0), 100.0), 2)


def aggregate_demand_clusters(
    queries: list[SearchQuerySignal],
    *,
    niche_key: str,
) -> list[StyleDemandCluster]:
    """Roll up search queries by design_style within the niche."""

    buckets: dict[str, dict[str, Any]] = {}
    niche_norm = niche_key.strip().casefold()
    for query in queries:
        if query.niche_key.strip().casefold() != niche_norm:
            continue
        key = _style_key(query.design_style)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "design_style": _normalize_style(query.design_style),
                "niche_key": niche_key.strip(),
                "baseline_volume": 0,
                "recent_volume": 0,
                "query_count": 0,
                "primary_query": query.query_text,
                "primary_recent": query.recent_volume,
                "related": [],
            }
            buckets[key] = bucket
        bucket["baseline_volume"] += query.baseline_volume
        bucket["recent_volume"] += query.recent_volume
        bucket["query_count"] += 1
        if query.recent_volume > bucket["primary_recent"]:
            bucket["primary_query"] = query.query_text
            bucket["primary_recent"] = query.recent_volume
        related = list(bucket["related"])
        related.append(query.query_text)
        related.extend(query.related_queries)
        # de-dupe preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for item in related:
            marker = item.casefold()
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(item)
        bucket["related"] = deduped[:40]

    clusters: list[StyleDemandCluster] = []
    for bucket in buckets.values():
        growth = compute_growth_ratio(
            baseline_volume=int(bucket["baseline_volume"]),
            recent_volume=int(bucket["recent_volume"]),
        )
        clusters.append(
            StyleDemandCluster(
                design_style=str(bucket["design_style"]),
                niche_key=str(bucket["niche_key"]),
                query_count=int(bucket["query_count"]),
                baseline_volume=int(bucket["baseline_volume"]),
                recent_volume=int(bucket["recent_volume"]),
                growth_ratio=growth,
                primary_query=str(bucket["primary_query"]),
                related_queries=list(bucket["related"]),
            )
        )
    clusters.sort(key=lambda c: (c.growth_ratio, c.recent_volume), reverse=True)
    return clusters


def aggregate_supply_snapshots(
    cards: list[SupplyCardSignal],
    *,
    niche_key: str,
    top_rank_ceiling: int,
) -> list[StyleSupplySnapshot]:
    """Count top-ranked cards per design style inside the niche."""

    buckets: dict[str, dict[str, Any]] = {}
    niche_norm = niche_key.strip().casefold()
    for card in cards:
        if card.niche_key.strip().casefold() != niche_norm:
            continue
        if card.rank > top_rank_ceiling:
            continue
        key = _style_key(card.design_style)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "design_style": _normalize_style(card.design_style),
                "niche_key": niche_key.strip(),
                "top_card_count": 0,
                "best_rank": card.rank,
                "skus": [],
            }
            buckets[key] = bucket
        bucket["top_card_count"] += 1
        if card.rank < int(bucket["best_rank"]):
            bucket["best_rank"] = card.rank
        skus = list(bucket["skus"])
        if card.sku not in skus:
            skus.append(card.sku)
        bucket["skus"] = skus[:50]

    snapshots = [
        StyleSupplySnapshot(
            design_style=str(b["design_style"]),
            niche_key=str(b["niche_key"]),
            top_card_count=int(b["top_card_count"]),
            best_rank=int(b["best_rank"]) if b["best_rank"] is not None else None,
            skus=list(b["skus"]),
        )
        for b in buckets.values()
    ]
    snapshots.sort(key=lambda s: s.top_card_count)
    return snapshots


def detect_market_gaps(
    *,
    marketplace: str,
    niche_key: str,
    search_queries: list[SearchQuerySignal],
    supply_cards: list[SupplyCardSignal],
    config: OracleGapConfig | None = None,
) -> OracleScanReport:
    """Compare rising search demand with scarce top-card supply."""

    cfg = config or OracleGapConfig()
    notes: list[str] = []
    marketplace_norm = marketplace.strip().lower()
    niche = niche_key.strip()

    if not search_queries:
        notes.append("Нет поисковых запросов — Oracle не может оценить спрос.")
        return OracleScanReport(
            marketplace=marketplace_norm,
            niche_key=niche,
            config=cfg,
            scanned_queries=0,
            scanned_supply_cards=len(supply_cards),
            scan_notes=notes,
        )

    demand = aggregate_demand_clusters(search_queries, niche_key=niche)
    supply = aggregate_supply_snapshots(
        supply_cards,
        niche_key=niche,
        top_rank_ceiling=cfg.top_rank_ceiling,
    )
    supply_by_style = {_style_key(s.design_style): s for s in supply}

    opportunities: list[NicheGapOpportunity] = []
    for cluster in demand:
        snapshot = supply_by_style.get(_style_key(cluster.design_style))
        top_count = snapshot.top_card_count if snapshot else 0
        best_rank = snapshot.best_rank if snapshot else None

        if cluster.growth_ratio < cfg.min_query_growth_ratio:
            continue
        if cluster.recent_volume < cfg.min_recent_query_volume:
            continue
        if top_count > cfg.max_top_cards_for_gap:
            continue

        score = compute_gap_score(
            growth_ratio=cluster.growth_ratio,
            recent_volume=cluster.recent_volume,
            top_card_count=top_count,
            config=cfg,
        )
        if score < cfg.min_gap_score:
            continue

        style = cluster.design_style
        notification = build_niche_notification(style)
        reason = (
            f"Спрос по запросам «{cluster.primary_query}» вырос на "
            f"{cluster.growth_ratio:.0%} (volume {cluster.baseline_volume}→"
            f"{cluster.recent_volume}), а в топ-{cfg.top_rank_ceiling} "
            f"карточек в стиле «{style}» всего {top_count}."
        )
        opportunities.append(
            NicheGapOpportunity(
                design_style=style,
                niche_key=niche,
                primary_query=cluster.primary_query,
                related_queries=cluster.related_queries,
                baseline_volume=cluster.baseline_volume,
                recent_volume=cluster.recent_volume,
                growth_ratio=cluster.growth_ratio,
                top_card_count=top_count,
                best_rank=best_rank,
                gap_score=score,
                severity=severity_from_gap_score(score),
                notification_message=notification,
                reason=reason[:500],
            )
        )

    opportunities.sort(key=lambda o: o.gap_score, reverse=True)
    truncated = opportunities[: cfg.max_alerts]
    if len(opportunities) > cfg.max_alerts:
        notes.append(
            f"Найдено {len(opportunities)} ниш; отдаём топ-{cfg.max_alerts} по gap_score."
        )
    if not truncated:
        notes.append(
            "Ниш не обнаружено: рост запросов недостаточен или топ уже насыщен."
        )
    else:
        notes.append(
            f"Обнаружено ниш: {len(truncated)}. Готовы уведомления для захвата трафика."
        )

    return OracleScanReport(
        marketplace=marketplace_norm,
        niche_key=niche,
        config=cfg,
        scanned_queries=len(search_queries),
        scanned_supply_cards=len(supply_cards),
        demand_clusters=demand,
        supply_snapshots=supply,
        opportunities=truncated,
        scan_notes=notes,
    )


def build_oracle_enrichment_prompt(*, scan_report: OracleScanReport) -> str:
    """User prompt for Claude enrichment of detected gaps."""

    lines: list[str] = [
        f"Маркетплейс: {scan_report.marketplace}. Ниша: {scan_report.niche_key}.",
        f"Найдено кандидатов в ниши: {len(scan_report.opportunities)}.",
        "Для каждого кандидата уточни refined_style_label и notification_message "
        "в формате: Обнаружена ниша! Сделай инфографику в стиле X, чтобы забрать трафик.",
        "Кандидаты:",
    ]
    for idx, gap in enumerate(scan_report.opportunities, start=1):
        lines.append(
            f"{idx}. style={gap.design_style}; query={gap.primary_query}; "
            f"growth={gap.growth_ratio:.0%}; volume={gap.recent_volume}; "
            f"top_cards={gap.top_card_count}; gap_score={gap.gap_score}; "
            f"severity={gap.severity.value}."
        )
    lines.append(
        "Сначала рассуждай в reasoning_trace, затем заполни JSON. "
        "design_style в ответе должен совпадать с входным style."
    )
    return " ".join(lines)


def build_prediction_result(
    *,
    scan_report: OracleScanReport,
    enrichments: list[ClaudeGapEnrichment],
    model_name: str,
) -> OraclePredictionResult:
    """Merge deterministic gaps with Claude enrichments into final result."""

    notes = list(scan_report.scan_notes)
    enrichment_by_style = {_style_key(e.design_style): e for e in enrichments}
    notifications: list[str] = []
    for gap in scan_report.opportunities:
        enriched = enrichment_by_style.get(_style_key(gap.design_style))
        if enriched is not None:
            notifications.append(enriched.notification_message)
        else:
            notifications.append(gap.notification_message)

    confidence = 0.0
    if enrichments:
        confidence = sum(e.confidence for e in enrichments) / len(enrichments)
    elif scan_report.opportunities:
        # Deterministic-only confidence from average normalized gap_score.
        confidence = min(
            sum(o.gap_score for o in scan_report.opportunities)
            / (100.0 * len(scan_report.opportunities)),
            1.0,
        )
        notes.append("Claude enrichment пропущен — уведомления по детерминированному скану.")

    return OraclePredictionResult(
        marketplace=scan_report.marketplace,
        niche_key=scan_report.niche_key,
        opportunities=list(scan_report.opportunities),
        enrichments=list(enrichments),
        notifications=notifications,
        model_name=model_name.strip() or "deterministic",
        confidence_score=round(confidence, 4),
        notes=notes[:40],
    )


def dump_scan_report(report: OracleScanReport) -> dict[str, Any]:
    return report.model_dump(mode="json")


def dump_prediction_result(result: OraclePredictionResult) -> dict[str, Any]:
    return result.model_dump(mode="json")


def redis_oracle_key(job_id: UUID, stage: str) -> str:
    """Redis key for an intermediate Oracle stage payload."""

    return f"claude:oracle:{job_id}:{stage}"
