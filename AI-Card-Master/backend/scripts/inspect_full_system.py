#!/usr/bin/env python3
"""Full backend system inspection — parser, layout/fonts, softbox, cutout, 360°.

Runs the core marketplace pipelines end-to-end and writes every artifact under
``artifacts/full_inspection/``. Prints per-module timings and ``ALL SYSTEMS OK``
when every stage succeeds.

Usage (from ``backend/``)::

    python scripts/inspect_full_system.py
    python -m scripts.inspect_full_system
    python scripts/inspect_full_system.py --url https://www.wildberries.ru/catalog/<nm>/detail.aspx
    python scripts/inspect_full_system.py --marketplace ozon --sku 123456789
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# Keep Settings bootstrap quiet for offline CLI use.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/ai_card_master_inspect",
)
os.environ.setdefault("JWT_SECRET_KEY", "i" * 64)
os.environ.setdefault("STABLE_DIFFUSION_API_KEY", "inspect-key")
os.environ.setdefault("MIDJOURNEY_PROVIDERS", "[]")
os.environ.setdefault("MIDJOURNEY_CALLBACK_BASE_URL", "https://api.inspect.example")
os.environ.setdefault(
    "MIDJOURNEY_WEBHOOK_TOKEN", "inspect-webhook-token-with-enough-entropy"
)
os.environ.setdefault(
    "MIDJOURNEY_REPLY_REF_SECRET", "inspect-reply-ref-secret-" + ("z" * 48)
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/14")
os.environ.setdefault("TELEGRAM_ERROR_LOGGING_ENABLED", "false")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")

from PIL import Image  # noqa: E402

from app.domain.competitor_audit import (  # noqa: E402
    CompetitorMarketplace,
    CompetitorProductLink,
    parse_competitor_product_link,
)
from app.domain.stock_parser import (  # noqa: E402
    ParseSkuRequest,
    ParsedSkuSnapshot,
    ParserMarketplace,
)
from app.infrastructure.competitor_audit.ozon_deep_client import (  # noqa: E402
    OzonDeepClient,
)
from app.infrastructure.competitor_audit.wb_deep_client import (  # noqa: E402
    WildberriesDeepClient,
)
from app.infrastructure.stock_parser.ozon_mobile_client import (  # noqa: E402
    OzonMobileClient,
    _map_ozon_product,
)
from app.infrastructure.stock_parser.wildberries_mobile_client import (  # noqa: E402
    WildberriesMobileClient,
    _map_wb_product,
)
from app.schemas.templates import TextLayerDTO  # noqa: E402
from app.services.bg_removal import BackgroundRemovalEngine  # noqa: E402
from app.services.relighting import RelightingEngineService, StudioLightDTO  # noqa: E402
from app.services.templates.download_default_fonts import ensure_default_fonts  # noqa: E402
from app.services.templates.font_manager import get_font_manager_service  # noqa: E402
from app.services.templates.fonts import FontRegistry  # noqa: E402
from app.services.templates.image_cache import ImageAssetCache  # noqa: E402
from app.services.templates.presets.ozon_top_seller import (  # noqa: E402
    ASSET_PRICE,
    ASSET_PRODUCT,
    ASSET_TITLE_PLATE,
    OZON_TOP_SELLER_PRESET_ID,
    OzonTopSellerConfig,
    build_ozon_top_seller_assets,
    build_ozon_top_seller_canvas,
    fit_product_box,
)
from app.services.templates.renderer import CanvasServerRenderer  # noqa: E402
from scripts.render_visual_test import (  # noqa: E402
    DEFAULT_ASSETS_DIR,
    SNEAKER_PNG_FILENAME,
    ensure_visual_test_assets,
)

logger = logging.getLogger("inspect_full_system")

DEFAULT_ARTIFACTS_DIR = _BACKEND_ROOT / "artifacts" / "full_inspection"
STUDIO_BG_CANDIDATES: tuple[Path, ...] = (
    DEFAULT_ASSETS_DIR / "product_on_studio_bg.png",
    _BACKEND_ROOT / "artifacts" / "test_assets" / "product_on_studio_bg.png",
)

# Public WB card that is typically reachable via card.wb.ru (override via CLI).
DEFAULT_WB_URL = "https://www.wildberries.ru/catalog/146132199/detail.aspx"
DEFAULT_WB_SKU = "146132199"

# Deterministic fixture used when marketplace APIs block the local IP (HTTP 403).
_WB_FIXTURE_PRODUCT: dict[str, Any] = {
    "id": 146132199,
    "name": "Кроссовки мужские для бега Air Flex Pro",
    "salePriceU": 899000,
    "priceU": 1499000,
    "sizes": [
        {
            "stocks": [
                {"wh": 507, "qty": 12},
                {"wh": 117986, "qty": 4},
                {"wh": 120762, "qty": 0},
            ]
        },
        {"stocks": [{"wh": 507, "qty": 3}, {"wh": 2737, "qty": 8}]},
    ],
}
_WB_FIXTURE_CHARACTERISTICS: tuple[dict[str, str], ...] = (
    {"name": "Бренд", "value": "Air Flex"},
    {"name": "Цвет", "value": "чёрный"},
    {"name": "Материал верха", "value": "текстиль / синтетика"},
    {"name": "Сезон", "value": "демисезон"},
    {"name": "Пол", "value": "Мужской"},
)
_OZON_FIXTURE_PRODUCT: dict[str, Any] = {
    "id": "1670164391",
    "title": "Кроссовки мужские для бега Air Flex Pro",
    "price": {"cardPrice": "8 990 ₽", "price": "14 990 ₽"},
    "stocks": [
        {"warehouse_id": "OMS", "qty": 15, "name": "Омск"},
        {"warehouse_id": "MSK", "qty": 22, "name": "Москва"},
        {"warehouse_id": "SPB", "qty": 7, "name": "Санкт-Петербург"},
    ],
}
_OZON_FIXTURE_CHARACTERISTICS: tuple[dict[str, str], ...] = (
    {"name": "Бренд", "value": "Air Flex"},
    {"name": "Тип", "value": "Кроссовки"},
    {"name": "Цвет", "value": "чёрный"},
    {"name": "Размер производителя", "value": "42"},
)

SOFTBOX_PRESETS: dict[str, StudioLightDTO] = {
    "warm_left": StudioLightDTO(
        light_angle=180.0,
        light_elevation=65.0,
        color_temp_k=3200,
        intensity=1.05,
        softbox_diffusion=0.85,
    ),
    "cold_right": StudioLightDTO(
        light_angle=0.0,
        light_elevation=45.0,
        color_temp_k=6500,
        intensity=1.15,
        softbox_diffusion=0.25,
    ),
    "soft_top": StudioLightDTO(
        light_angle=90.0,
        light_elevation=85.0,
        color_temp_k=5500,
        intensity=1.0,
        softbox_diffusion=0.92,
    ),
}


# ---------------------------------------------------------------------------
# Timing / status
# ---------------------------------------------------------------------------


@dataclass
class ModuleResult:
    name: str
    ok: bool
    elapsed_s: float
    detail: str = ""
    artifacts: list[str] = field(default_factory=list)


@dataclass
class TimedStage:
    name: str
    started: float
    elapsed_s: float = 0.0


@contextmanager
def timed(name: str) -> Iterator[TimedStage]:
    stage = TimedStage(name=name, started=time.perf_counter())
    print(f"\n=== [{name}] starting ===")
    try:
        yield stage
    finally:
        stage.elapsed_s = time.perf_counter() - stage.started
        print(f"=== [{name}] done in {stage.elapsed_s:.2f}s ===")


def _elapsed(stage: TimedStage) -> float:
    """Seconds since stage start (safe to call before ``timed`` finally)."""

    if stage.elapsed_s > 0.0:
        return stage.elapsed_s
    return max(0.0, time.perf_counter() - stage.started)


# ---------------------------------------------------------------------------
# 1. Parser
# ---------------------------------------------------------------------------


def _marketplace_from_arg(value: str) -> ParserMarketplace:
    key = value.strip().casefold()
    if key in {"wb", "wildberries", "вайлдберриз"}:
        return ParserMarketplace.WILDBERRIES
    if key in {"ozon", "озон"}:
        return ParserMarketplace.OZON
    raise argparse.ArgumentTypeError(f"Unknown marketplace: {value!r}")


def _resolve_link(
    *,
    marketplace: ParserMarketplace,
    sku: str | None,
    url: str | None,
) -> tuple[str, str | None]:
    """Return ``(sku, product_url)`` for the stock / deep clients."""

    if url:
        try:
            link = parse_competitor_product_link(url)
            return link.article, link.url
        except ValueError:
            # Allow non-strict URLs when sku is also provided.
            if sku:
                return sku.strip(), url.strip()
            raise
    if sku:
        article = "".join(ch for ch in sku if ch.isdigit()) or sku.strip()
        if marketplace is ParserMarketplace.WILDBERRIES:
            return article, f"https://www.wildberries.ru/catalog/{article}/detail.aspx"
        return article, f"https://www.ozon.ru/product/{article}/"
    if marketplace is ParserMarketplace.WILDBERRIES:
        return DEFAULT_WB_SKU, DEFAULT_WB_URL
    raise ValueError("Ozon inspect requires --sku or --url.")


def _snapshot_to_dict(snapshot: ParsedSkuSnapshot) -> dict[str, Any]:
    return {
        "marketplace": snapshot.marketplace.value,
        "sku": snapshot.sku,
        "product_url": snapshot.product_url,
        "title": snapshot.title,
        "price_kopecks": snapshot.price_kopecks,
        "price_before_discount_kopecks": snapshot.price_before_discount_kopecks,
        "currency": snapshot.currency,
        "total_stock": snapshot.total_stock,
        "stocks": [
            {
                "warehouse_id": row.warehouse_id,
                "quantity": row.quantity,
                "warehouse_name": row.warehouse_name,
            }
            for row in snapshot.stocks
        ],
    }


async def run_parser(
    out_dir: Path,
    *,
    marketplace: ParserMarketplace,
    sku: str | None,
    url: str | None,
    allow_fixture_fallback: bool,
) -> ModuleResult:
    stage_name = "parser"
    with timed(stage_name) as stage:
        article, product_url = _resolve_link(
            marketplace=marketplace, sku=sku, url=url
        )
        request = ParseSkuRequest(
            marketplace=marketplace,
            sku=article,
            product_url=product_url,
        )

        warnings: list[str] = []
        characteristics: list[dict[str, str]] = []
        description = ""
        deep_title: str | None = None
        source = "live"
        snapshot: ParsedSkuSnapshot | None = None
        live_error: str | None = None

        if marketplace is ParserMarketplace.WILDBERRIES:
            stock_client: WildberriesMobileClient | OzonMobileClient = (
                WildberriesMobileClient()
            )
            deep_client: WildberriesDeepClient | OzonDeepClient = WildberriesDeepClient()
            competitor_mp = CompetitorMarketplace.WILDBERRIES
        else:
            stock_client = OzonMobileClient()
            deep_client = OzonDeepClient()
            competitor_mp = CompetitorMarketplace.OZON

        try:
            try:
                snapshot = await stock_client.fetch_sku(request)
            except Exception as exc:  # noqa: BLE001 — live marketplace may 403
                live_error = f"{type(exc).__name__}: {exc}"
                logger.warning("Live stock parse failed: %s", live_error)
                warnings.append(f"live stock parse failed: {live_error}")
        finally:
            await stock_client.aclose()

        if snapshot is not None:
            try:
                deep_url = product_url or request.product_url
                if not deep_url:
                    if marketplace is ParserMarketplace.WILDBERRIES:
                        deep_url = (
                            f"https://www.wildberries.ru/catalog/{article}/detail.aspx"
                        )
                    else:
                        deep_url = f"https://www.ozon.ru/product/{article}/"
                link = CompetitorProductLink(
                    url=deep_url,
                    marketplace=competitor_mp,
                    article=article,
                )
                deep = await deep_client.scrape_card(link)
                characteristics = [
                    {"name": row.name, "value": row.value} for row in deep.specs
                ]
                description = deep.description or ""
                deep_title = deep.title
                warnings.extend(deep.scrape_warnings)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"characteristics enrichment failed: {exc}")
                logger.warning("Deep scrape failed: %s", exc)
            finally:
                await deep_client.aclose()
        else:
            await deep_client.aclose()

        if snapshot is None:
            if not allow_fixture_fallback:
                raise RuntimeError(
                    live_error
                    or "Live marketplace parse failed (no fixture fallback)."
                )
            source = "fixture_fallback"
            snapshot, characteristics, description = _fixture_snapshot(
                marketplace=marketplace,
                sku=article,
                product_url=product_url,
            )
            warnings.append(
                "Used local fixture through stock-parser mappers "
                "(marketplace API unavailable from this network)."
            )
            print("  ! live API blocked — fixture fallback via real mappers")

        payload: dict[str, Any] = {
            "inspected_at": datetime.now(UTC).isoformat(),
            "source": source,
            "warnings": warnings,
            **_snapshot_to_dict(snapshot),
            "description": description,
            "characteristics": characteristics,
            "deep_title": deep_title,
            "raw_payload": _truncate_json(snapshot.raw_payload, max_chars=120_000),
        }
        if deep_title and deep_title != snapshot.title:
            payload["title"] = deep_title

        out_path = out_dir / "parsed_product.json"
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        detail = (
            f"{snapshot.marketplace.value} sku={snapshot.sku} "
            f"source={source} stocks={len(snapshot.stocks)} "
            f"chars={len(characteristics)} total_qty={snapshot.total_stock}"
        )
        print(f"  saved: {out_path}")
        print(f"  {detail}")
        return ModuleResult(
            name=stage_name,
            ok=True,
            elapsed_s=_elapsed(stage),
            detail=detail,
            artifacts=[str(out_path.resolve())],
        )

def _fixture_snapshot(
    *,
    marketplace: ParserMarketplace,
    sku: str,
    product_url: str | None,
) -> tuple[ParsedSkuSnapshot, list[dict[str, str]], str]:
    """Exercise real mapper helpers against a deterministic card fixture."""

    if marketplace is ParserMarketplace.WILDBERRIES:
        product = dict(_WB_FIXTURE_PRODUCT)
        product["id"] = int("".join(ch for ch in sku if ch.isdigit()) or product["id"])
        snapshot = _map_wb_product(
            product,
            sku=sku,
            product_url=product_url,
            raw_payload={"data": {"products": [product]}, "_fixture": True},
        )
        return (
            snapshot,
            [dict(row) for row in _WB_FIXTURE_CHARACTERISTICS],
            "Тестовая карточка WB: лёгкие кроссовки для бега и города.",
        )

    product = dict(_OZON_FIXTURE_PRODUCT)
    product["id"] = sku
    snapshot = _map_ozon_product(
        product,
        sku=sku,
        product_url=product_url,
        raw_payload={"product": product, "_fixture": True},
    )
    return (
        snapshot,
        [dict(row) for row in _OZON_FIXTURE_CHARACTERISTICS],
        "Тестовая карточка Ozon: лёгкие кроссовки для бега и города.",
    )


def _truncate_json(value: Any, *, max_chars: int) -> Any:
    try:
        blob = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return {"_error": "raw_payload not JSON-serializable"}
    if len(blob) <= max_chars:
        return value
    return {
        "_truncated": True,
        "_original_chars": len(blob),
        "_preview": blob[:max_chars],
    }


# ---------------------------------------------------------------------------
# 2. Layout + fonts (Ozon Top Seller)
# ---------------------------------------------------------------------------


def _rects_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    *,
    pad: float = 2.0,
) -> bool:
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    return not (
        ax0 + aw + pad <= bx0
        or bx0 + bw + pad <= ax0
        or ay0 + ah + pad <= by0
        or by0 + bh + pad <= ay0
    )


def _validate_ozon_layout(canvas) -> list[str]:
    """Return human-readable issues (empty list ⇒ layout OK)."""

    issues: list[str] = []
    names = {layer.name for layer in canvas.layers}
    required = {"title-backdrop", "title-inter-extrabold", "accent-price-badge"}
    missing = required - names
    if missing:
        issues.append(f"missing layers: {sorted(missing)}")

    chip_layers = [layer for layer in canvas.layers if layer.name.startswith("feature-chip-")]
    if len(chip_layers) < 1:
        issues.append("no feature chips (плашки) present")

    text_boxes: list[tuple[str, tuple[float, float, float, float]]] = []
    for layer in canvas.layers:
        if isinstance(layer, TextLayerDTO) and layer.visible:
            text_boxes.append(
                (layer.name, (layer.x, layer.y, layer.width, layer.height))
            )

    for index, (name_a, box_a) in enumerate(text_boxes):
        for name_b, box_b in text_boxes[index + 1 :]:
            if _rects_overlap(box_a, box_b):
                issues.append(f"text overlap: {name_a} ↔ {name_b}")

    # Title must sit on its plate (no free-floating headline).
    title = next((layer for layer in canvas.layers if layer.name == "title-inter-extrabold"), None)
    plate = next((layer for layer in canvas.layers if layer.name == "title-backdrop"), None)
    if title is not None and plate is not None:
        inside = (
            title.x >= plate.x - 1
            and title.y >= plate.y - 1
            and title.x + title.width <= plate.x + plate.width + 1
            and title.y + title.height <= plate.y + plate.height + 1
        )
        if not inside:
            issues.append("title text is outside title plate (обводка/плашка)")

    return issues


def _assert_badge_outlines(assets: dict[str, bytes]) -> list[str]:
    """Sanity-check that price badge / chips have non-empty opaque pixels."""

    issues: list[str] = []
    for key in (ASSET_PRICE, ASSET_TITLE_PLATE):
        payload = assets.get(key)
        if not payload:
            issues.append(f"missing asset {key}")
            continue
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            rgba = image.convert("RGBA")
            if rgba.getbbox() is None:
                issues.append(f"empty raster for {key}")
    # Chips: at least one with outline plate.
    chip_keys = [k for k in assets if k.startswith("memory://presets/ozon-top-seller/chip-")]
    if not chip_keys:
        issues.append("no chip assets generated")
    return issues


async def run_layout(out_dir: Path, *, cutout_png: bytes) -> ModuleResult:
    stage_name = "layout_fonts"
    with timed(stage_name) as stage:
        ensure_default_fonts()
        font_manager = get_font_manager_service()
        await font_manager.bootstrap(persist_system_fonts=False)

        config = OzonTopSellerConfig()
        assets = build_ozon_top_seller_assets(cutout_png, config=config)
        layout_issues = _assert_badge_outlines(assets)

        cache = ImageAssetCache()
        for url, payload in assets.items():
            cache.put(url, payload)

        product_box = fit_product_box(assets[ASSET_PRODUCT])
        canvas = build_ozon_top_seller_canvas(product_box=product_box, config=config)
        layout_issues.extend(_validate_ozon_layout(canvas))

        renderer = CanvasServerRenderer(
            font_registry=FontRegistry(),
            font_manager=font_manager,
            image_cache=cache,
        )
        result = await renderer.render(canvas, output_format="png")
        out_path = out_dir / "ozon_perfect_card.png"
        out_path.write_bytes(result.image_bytes)

        ok = not layout_issues
        detail = (
            f"preset={OZON_TOP_SELLER_PRESET_ID} "
            f"{result.width}x{result.height} "
            + ("layout_ok" if ok else f"issues={layout_issues}")
        )
        print(f"  saved: {out_path}")
        print(f"  {detail}")
        if layout_issues:
            for issue in layout_issues:
                print(f"  ! {issue}")
        return ModuleResult(
            name=stage_name,
            ok=ok,
            elapsed_s=_elapsed(stage),
            detail=detail,
            artifacts=[str(out_path.resolve())],
        )


# ---------------------------------------------------------------------------
# 3. Softbox
# ---------------------------------------------------------------------------


async def run_softbox(out_dir: Path, *, cutout_png: bytes) -> ModuleResult:
    stage_name = "softbox"
    with timed(stage_name) as stage:
        engine = RelightingEngineService()
        artifacts: list[str] = []
        for name, light in SOFTBOX_PRESETS.items():
            result = await engine.process_custom(cutout_png, studio_light=light)
            path = out_dir / f"{name}.png"
            path.write_bytes(result.image_png)
            artifacts.append(str(path.resolve()))
            print(
                f"  {name}: {path.name} "
                f"({result.width}x{result.height}, "
                f"K={light.color_temp_k}, angle={light.light_angle})"
            )
        detail = f"generated={len(artifacts)}"
        return ModuleResult(
            name=stage_name,
            ok=len(artifacts) == len(SOFTBOX_PRESETS),
            elapsed_s=_elapsed(stage),
            detail=detail,
            artifacts=artifacts,
        )


# ---------------------------------------------------------------------------
# 4. Edge cleanup + 360°
# ---------------------------------------------------------------------------


def _resolve_studio_source(*, assets_dir: Path) -> bytes:
    for candidate in (assets_dir / "product_on_studio_bg.png", *STUDIO_BG_CANDIDATES):
        if candidate.is_file() and candidate.stat().st_size > 0:
            logger.info("Using studio source image: %s", candidate)
            return candidate.read_bytes()
    sneaker = assets_dir / SNEAKER_PNG_FILENAME
    if sneaker.is_file():
        # Flatten transparent sneaker onto a light studio plate so rembg still runs.
        with Image.open(sneaker) as src:
            src.load()
            rgba = src.convert("RGBA")
        plate = Image.new("RGB", rgba.size, (245, 245, 248))
        plate.paste(rgba, mask=rgba.getchannel("A"))
        buf = io.BytesIO()
        plate.save(buf, format="PNG")
        return buf.getvalue()
    raise FileNotFoundError(
        "No product_on_studio_bg.png / sneaker asset available for bg removal."
    )


def _validate_cutout(png_bytes: bytes) -> list[str]:
    issues: list[str] = []
    with Image.open(io.BytesIO(png_bytes)) as image:
        image.load()
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        extrema = alpha.getextrema()
        if extrema is None:
            issues.append("alpha channel missing")
        else:
            lo, hi = extrema
            if lo >= 250:
                issues.append("cutout has no transparency")
            if hi < 10:
                issues.append("cutout is fully transparent")
        if rgba.getbbox() is None:
            issues.append("cutout bbox is empty")
    return issues


async def run_cutout(out_dir: Path, *, assets_dir: Path) -> tuple[ModuleResult, bytes]:
    stage_name = "edge_cleanup"
    with timed(stage_name) as stage:
        source = _resolve_studio_source(assets_dir=assets_dir)
        engine = BackgroundRemovalEngine()
        result = await engine.process(source)
        issues = _validate_cutout(result.image_png)
        out_path = out_dir / "clean_cutout.png"
        out_path.write_bytes(result.image_png)
        ok = not issues
        detail = (
            f"{result.width}x{result.height} "
            + ("clean" if ok else f"defects={issues}")
        )
        print(f"  saved: {out_path}")
        print(f"  {detail}")
        return (
            ModuleResult(
                name=stage_name,
                ok=ok,
                elapsed_s=_elapsed(stage),
                detail=detail,
                artifacts=[str(out_path.resolve())],
            ),
            result.image_png,
        )


async def run_orbit(
    out_dir: Path,
    *,
    mesh_path: Path | None,
    backend: str,
) -> ModuleResult:
    stage_name = "orbit_360"
    with timed(stage_name) as stage:
        import scripts.render_visual_test as visual_test
        from app.services.three_d.errors import MeshLoadError

        resolved = _resolve_orbit_mesh(mesh_path, out_dir)
        if resolved is not None:
            print(f"  mesh: {resolved}")
        else:
            print("  mesh: procedural icosphere")

        def _render(mesh: Path | None, *, force_icosphere: bool = False):
            if not force_icosphere:
                return visual_test.render_orbit_artifacts(
                    out_dir,
                    mesh_path=mesh,
                    backend=backend,
                )
            # Bypass auto-discovery of MaterialsVariantsShoe.glb.
            original = visual_test._find_default_mesh
            visual_test._find_default_mesh = lambda: None  # type: ignore[assignment]
            try:
                return visual_test.render_orbit_artifacts(
                    out_dir,
                    mesh_path=None,
                    backend=backend,
                )
            finally:
                visual_test._find_default_mesh = original

        try:
            mp4_path, _gif_path = await asyncio.to_thread(_render, resolved)
        except MeshLoadError as exc:
            logger.warning("Mesh load failed (%s); retrying with icosphere", exc)
            print(f"  ! mesh load failed — retrying with icosphere ({exc})")
            mp4_path, _gif_path = await asyncio.to_thread(
                _render, None, force_icosphere=True
            )

        target = out_dir / "product_360.mp4"
        if mp4_path.resolve() != target.resolve():
            target.write_bytes(mp4_path.read_bytes())
            if mp4_path.name != target.name and mp4_path.is_file():
                try:
                    mp4_path.unlink()
                except OSError:
                    pass
        # Keep the inspect folder focused on the requested contract artifacts.
        for leftover in (
            out_dir / "real_360_output.mp4",
            out_dir / "real_360_preview.gif",
        ):
            if leftover.is_file():
                try:
                    leftover.unlink()
                except OSError:
                    pass
        detail = f"mp4={target.name} ({target.stat().st_size} bytes)"
        print(f"  saved: {target}")
        return ModuleResult(
            name=stage_name,
            ok=target.is_file() and target.stat().st_size > 0,
            elapsed_s=_elapsed(stage),
            detail=detail,
            artifacts=[str(target.resolve())],
        )


def _trimesh_available() -> bool:
    try:
        import trimesh  # noqa: F401

        return True
    except ImportError:
        return False


def _resolve_orbit_mesh(mesh_path: Path | None, out_dir: Path) -> Path | None:
    """Pick a loadable mesh; prefer OBJ when trimesh is unavailable."""

    has_trimesh = _trimesh_available()
    candidates: list[Path] = []
    if mesh_path is not None:
        candidates.append(mesh_path)
    candidates.extend(
        [
            DEFAULT_ASSETS_DIR / "MaterialsVariantsShoe.glb",
            _BACKEND_ROOT / "artifacts" / "test_assets" / "MaterialsVariantsShoe.glb",
        ]
    )
    obj = _find_cached_obj(out_dir)
    if obj is not None:
        candidates.append(obj)

    for path in candidates:
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in {".glb", ".gltf"} and not has_trimesh:
            continue
        if suffix in {".glb", ".gltf", ".obj"}:
            return path
    return None


def _find_cached_obj(out_dir: Path) -> Path | None:
    """Prefer a previously converted OBJ from the visual-test mesh cache."""

    candidates = [
        out_dir / "mesh_cache",
        _BACKEND_ROOT / "artifacts" / "mesh_cache",
        _BACKEND_ROOT / "artifacts" / "full_inspection" / "mesh_cache",
    ]
    for folder in candidates:
        if not folder.is_dir():
            continue
        objs = sorted(
            folder.glob("*.obj"), key=lambda p: p.stat().st_size, reverse=True
        )
        for path in objs:
            if path.stat().st_size > 1024:
                return path
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Full backend inspection: WB/Ozon parser, Ozon card layout, "
            "softbox lights, clean cutout, 360° video"
        ),
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=DEFAULT_ARTIFACTS_DIR,
        help=f"Output directory (default: {DEFAULT_ARTIFACTS_DIR})",
    )
    parser.add_argument(
        "--assets-dir",
        type=Path,
        default=DEFAULT_ASSETS_DIR,
        help=f"Cached visual assets (default: {DEFAULT_ASSETS_DIR})",
    )
    parser.add_argument(
        "--marketplace",
        type=_marketplace_from_arg,
        default=ParserMarketplace.WILDBERRIES,
        help="Marketplace for the parser stage (wb|ozon, default: wb)",
    )
    parser.add_argument("--sku", type=str, default=None, help="Product article / nmId")
    parser.add_argument("--url", type=str, default=None, help="WB/Ozon product URL")
    parser.add_argument(
        "--mesh",
        type=Path,
        default=None,
        help="Optional .glb/.obj for 360° (default: downloaded shoe GLB)",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "pyvista", "moderngl", "software"),
        default=os.environ.get("THREE_D_RENDER_BACKEND", "auto"),
        help="Offscreen GL / software backend for 360°",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Do not download visual assets (use cache only)",
    )
    parser.add_argument(
        "--skip-parser",
        action="store_true",
        help="Skip marketplace parser stage",
    )
    parser.add_argument(
        "--no-fixture-fallback",
        action="store_true",
        help="Fail parser stage when live WB/Ozon APIs are unreachable",
    )
    parser.add_argument(
        "--skip-video",
        action="store_true",
        help="Skip 360° orbit video",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG logging")
    return parser.parse_args(argv)


def _print_summary(results: list[ModuleResult]) -> int:
    print("\n" + "=" * 60)
    print("FULL SYSTEM INSPECTION SUMMARY")
    print("=" * 60)
    width = max((len(item.name) for item in results), default=8)
    for item in results:
        status = "OK" if item.ok else "FAIL"
        print(
            f"  {item.name:<{width}}  {item.elapsed_s:7.2f}s  [{status}]  {item.detail}"
        )
    total = sum(item.elapsed_s for item in results)
    print("-" * 60)
    print(f"  total{' ' * (width - 5)}  {total:7.2f}s")
    all_ok = bool(results) and all(item.ok for item in results)
    print()
    if all_ok:
        print("ALL SYSTEMS OK")
        return 0
    failed = [item.name for item in results if not item.ok]
    print(f"SYSTEM CHECK FAILED: {', '.join(failed)}")
    return 1


async def _async_main(args: argparse.Namespace) -> int:
    out_dir = args.artifacts_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = args.assets_dir.resolve()
    assets_dir.mkdir(parents=True, exist_ok=True)

    results: list[ModuleResult] = []
    mesh_path: Path | None = args.mesh

    if not args.skip_download:
        print("=== [assets] ensuring visual test assets ===")
        sneaker_path, downloaded_mesh = await asyncio.to_thread(
            ensure_visual_test_assets,
            assets_dir,
        )
        print(f"  sneaker: {sneaker_path}")
        print(f"  mesh   : {downloaded_mesh}")
        if mesh_path is None:
            mesh_path = downloaded_mesh

    # --- 1. Parser ---------------------------------------------------------
    if not args.skip_parser:
        try:
            results.append(
                await run_parser(
                    out_dir,
                    marketplace=args.marketplace,
                    sku=args.sku,
                    url=args.url,
                    allow_fixture_fallback=not args.no_fixture_fallback,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Parser stage failed")
            results.append(
                ModuleResult(
                    name="parser",
                    ok=False,
                    elapsed_s=0.0,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
    else:
        print("=== [parser] skipped ===")

    # --- 4a. Edge cleanup (cutout feeds layout + softbox) ------------------
    cutout_png: bytes | None = None
    try:
        cutout_result, cutout_png = await run_cutout(out_dir, assets_dir=assets_dir)
        results.append(cutout_result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Edge cleanup failed")
        results.append(
            ModuleResult(
                name="edge_cleanup",
                ok=False,
                elapsed_s=0.0,
                detail=f"{type(exc).__name__}: {exc}",
            )
        )
        # Fall back to cached transparent sneaker so later stages can still run.
        sneaker = assets_dir / SNEAKER_PNG_FILENAME
        if sneaker.is_file():
            cutout_png = sneaker.read_bytes()
            print(f"  fallback cutout: {sneaker}")

    if cutout_png is None:
        print("ERROR: no cutout available; aborting remaining visual stages.")
        return _print_summary(results)

    # --- 2. Layout + fonts -------------------------------------------------
    try:
        results.append(await run_layout(out_dir, cutout_png=cutout_png))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Layout stage failed")
        results.append(
            ModuleResult(
                name="layout_fonts",
                ok=False,
                elapsed_s=0.0,
                detail=f"{type(exc).__name__}: {exc}",
            )
        )

    # --- 3. Softbox --------------------------------------------------------
    try:
        results.append(await run_softbox(out_dir, cutout_png=cutout_png))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Softbox stage failed")
        results.append(
            ModuleResult(
                name="softbox",
                ok=False,
                elapsed_s=0.0,
                detail=f"{type(exc).__name__}: {exc}",
            )
        )

    # --- 4b. 360° ----------------------------------------------------------
    if not args.skip_video:
        try:
            results.append(
                await run_orbit(out_dir, mesh_path=mesh_path, backend=args.backend)
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("360° stage failed")
            results.append(
                ModuleResult(
                    name="orbit_360",
                    ok=False,
                    elapsed_s=0.0,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
    else:
        print("=== [orbit_360] skipped ===")

    print("\nArtifacts directory:", out_dir)
    for item in results:
        for path in item.artifacts:
            print(f"  - {path}")

    return _print_summary(results)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        logger.exception("Full inspection failed: %s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
