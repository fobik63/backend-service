#!/usr/bin/env python3
"""Full-stack health verification — parser, canvas, softbox, cutout + report.

Writes diagnostic artifacts under ``artifacts/system_health/``:

* parsed_data_test.json
* canvas_render_test.png
* softbox_lighting_test.png
* clean_cutout_test.png
* health_report.json

Usage (from ``backend/``)::

    python scripts/verify_full_stack.py
    python -m scripts.verify_full_stack
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
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/ai_card_master_verify",
)
os.environ.setdefault("JWT_SECRET_KEY", "v" * 64)
os.environ.setdefault("STABLE_DIFFUSION_API_KEY", "verify-key")
os.environ.setdefault("MIDJOURNEY_PROVIDERS", "[]")
os.environ.setdefault("MIDJOURNEY_CALLBACK_BASE_URL", "https://api.verify.example")
os.environ.setdefault(
    "MIDJOURNEY_WEBHOOK_TOKEN", "verify-webhook-token-with-enough-entropy"
)
os.environ.setdefault(
    "MIDJOURNEY_REPLY_REF_SECRET", "verify-reply-ref-secret-" + ("z" * 48)
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/13")
os.environ.setdefault("TELEGRAM_ERROR_LOGGING_ENABLED", "false")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")

from PIL import Image  # noqa: E402

from app.domain.competitor_audit import (  # noqa: E402
    CompetitorMarketplace,
    CompetitorProductLink,
    parse_competitor_product_link,
)
from app.domain.stock_parser import ParseSkuRequest, ParserMarketplace  # noqa: E402
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
from app.services.bg_removal import BackgroundRemovalEngine  # noqa: E402
from app.services.relighting import RelightingEngineService, StudioLightDTO  # noqa: E402
from app.services.templates.download_default_fonts import ensure_default_fonts  # noqa: E402
from app.services.templates.font_manager import get_font_manager_service  # noqa: E402
from app.services.templates.fonts import FontRegistry  # noqa: E402
from app.services.templates.image_cache import ImageAssetCache  # noqa: E402
from app.services.templates.presets.ozon_top_seller import (  # noqa: E402
    ASSET_PRODUCT,
    OZON_TOP_SELLER_PRESET_ID,
    OzonTopSellerConfig,
    build_ozon_top_seller_assets,
    build_ozon_top_seller_canvas,
    fit_product_box,
)
from app.services.templates.renderer import CanvasServerRenderer  # noqa: E402
from scripts.inspect_full_system import (  # noqa: E402
    DEFAULT_WB_URL,
    _OZON_FIXTURE_CHARACTERISTICS,
    _OZON_FIXTURE_PRODUCT,
    _WB_FIXTURE_CHARACTERISTICS,
    _WB_FIXTURE_PRODUCT,
    _validate_cutout,
)
from scripts.render_visual_test import (  # noqa: E402
    DEFAULT_ASSETS_DIR,
    SNEAKER_PNG_FILENAME,
    ensure_visual_test_assets,
)

logger = logging.getLogger("verify_full_stack")

DEFAULT_ARTIFACTS_DIR = _BACKEND_ROOT / "artifacts" / "system_health"

# Frontend client paths (relative to /api/v1) that must exist on FastAPI.
_REQUIRED_API_PATHS: tuple[tuple[str, str], ...] = (
    ("POST", "/api/v1/canvas/render"),
    ("POST", "/api/v1/relighting/custom"),
    ("POST", "/api/v1/parser/parse"),
    ("POST", "/api/v1/templates/prompt-to-json"),
    ("POST", "/api/v1/tools/remove-bg"),
)


@dataclass
class StageResult:
    name: str
    ok: bool
    elapsed_ms: float
    detail: str = ""
    artifact: str | None = None


@dataclass
class HealthReport:
    generated_at: str
    overall_ok: bool
    stages: list[dict[str, Any]] = field(default_factory=list)
    api_routes_sync: dict[str, Any] = field(default_factory=dict)
    security: dict[str, Any] = field(default_factory=dict)
    artifacts_dir: str = ""


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _fixture_parse(marketplace: ParserMarketplace, sku: str, url: str) -> dict[str, Any]:
    if marketplace is ParserMarketplace.WILDBERRIES:
        product = dict(_WB_FIXTURE_PRODUCT)
        product["id"] = int("".join(ch for ch in sku if ch.isdigit()) or product["id"])
        snapshot = _map_wb_product(
            product,
            sku=sku,
            product_url=url,
            raw_payload={"data": {"products": [product]}, "_fixture": True},
        )
        characteristics = [dict(row) for row in _WB_FIXTURE_CHARACTERISTICS]
        description = "Fixture WB card for system health verification."
    else:
        product = dict(_OZON_FIXTURE_PRODUCT)
        product["id"] = sku
        snapshot = _map_ozon_product(
            product,
            sku=sku,
            product_url=url,
            raw_payload={"product": product, "_fixture": True},
        )
        characteristics = [dict(row) for row in _OZON_FIXTURE_CHARACTERISTICS]
        description = "Fixture Ozon card for system health verification."

    return {
        "marketplace": snapshot.marketplace.value,
        "sku": snapshot.sku,
        "product_url": snapshot.product_url or url,
        "title": snapshot.title,
        "price_kopecks": snapshot.price_kopecks,
        "price_before_discount_kopecks": snapshot.price_before_discount_kopecks,
        "currency": snapshot.currency,
        "description": description,
        "characteristics": characteristics,
        "image_urls": [],
        "total_stock": snapshot.total_stock,
        "source": "fixture_fallback",
    }


async def stage_parser(out_dir: Path, *, url: str | None) -> StageResult:
    started = time.perf_counter()
    product_url = url or DEFAULT_WB_URL
    source = "live"
    warnings: list[str] = []

    try:
        link = parse_competitor_product_link(product_url)
    except ValueError as exc:
        return StageResult(
            name="parser",
            ok=False,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            detail=f"invalid url: {exc}",
        )

    parser_mp = (
        ParserMarketplace.WILDBERRIES
        if link.marketplace is CompetitorMarketplace.WILDBERRIES
        else ParserMarketplace.OZON
    )
    request = ParseSkuRequest(
        marketplace=parser_mp,
        sku=link.article,
        product_url=link.url,
    )

    if link.marketplace is CompetitorMarketplace.WILDBERRIES:
        stock_client: WildberriesMobileClient | OzonMobileClient = (
            WildberriesMobileClient()
        )
        deep_client: WildberriesDeepClient | OzonDeepClient = WildberriesDeepClient()
    else:
        stock_client = OzonMobileClient()
        deep_client = OzonDeepClient()

    payload: dict[str, Any] | None = None
    try:
        try:
            snapshot = await stock_client.fetch_sku(request)
            deep = await deep_client.scrape_card(
                CompetitorProductLink(
                    url=link.url,
                    marketplace=link.marketplace,
                    article=link.article,
                )
            )
            payload = {
                "marketplace": link.marketplace.value,
                "sku": link.article,
                "product_url": link.url,
                "title": deep.title or snapshot.title,
                "price_kopecks": deep.price_after_discount_kopecks
                or snapshot.price_kopecks,
                "price_before_discount_kopecks": (
                    deep.price_before_discount_kopecks
                    or snapshot.price_before_discount_kopecks
                ),
                "currency": deep.currency or snapshot.currency,
                "description": deep.description or None,
                "characteristics": [
                    {"name": row.name, "value": row.value} for row in deep.specs
                ],
                "image_urls": list(deep.photo_urls),
                "total_stock": snapshot.total_stock,
                "source": "live",
            }
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{type(exc).__name__}: {exc}")
            source = "fixture_fallback"
            payload = _fixture_parse(parser_mp, link.article, link.url)
            payload["warnings"] = warnings
            print(f"  ! live parse blocked — fixture fallback ({exc})")
    finally:
        await stock_client.aclose()
        await deep_client.aclose()

    assert payload is not None
    payload["inspected_at"] = datetime.now(UTC).isoformat()
    out_path = out_dir / "parsed_data_test.json"
    _write_json(out_path, payload)
    ok = bool(payload.get("title")) and bool(payload.get("sku"))
    return StageResult(
        name="parser",
        ok=ok,
        elapsed_ms=(time.perf_counter() - started) * 1000,
        detail=f"source={source} sku={payload.get('sku')}",
        artifact=str(out_path.resolve()),
    )


async def stage_cutout(out_dir: Path, *, assets_dir: Path) -> tuple[StageResult, bytes]:
    started = time.perf_counter()
    studio = assets_dir / "product_on_studio_bg.png"
    sneaker = assets_dir / SNEAKER_PNG_FILENAME

    if studio.is_file():
        source = studio.read_bytes()
    elif sneaker.is_file():
        with Image.open(sneaker) as src:
            src.load()
            rgba = src.convert("RGBA")
        plate = Image.new("RGB", rgba.size, (245, 245, 248))
        plate.paste(rgba, mask=rgba.getchannel("A"))
        buf = io.BytesIO()
        plate.save(buf, format="PNG")
        source = buf.getvalue()
    else:
        raise FileNotFoundError("No studio/sneaker asset for cutout stage")

    engine = BackgroundRemovalEngine()
    result = await engine.process(source)
    issues = _validate_cutout(result.image_png)
    out_path = out_dir / "clean_cutout_test.png"
    out_path.write_bytes(result.image_png)
    ok = not issues
    return (
        StageResult(
            name="cutout",
            ok=ok,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            detail=(
                f"{result.width}x{result.height} "
                + ("clean" if ok else f"issues={issues}")
            ),
            artifact=str(out_path.resolve()),
        ),
        result.image_png,
    )


async def stage_canvas(out_dir: Path, *, cutout_png: bytes) -> StageResult:
    started = time.perf_counter()
    ensure_default_fonts()
    font_manager = get_font_manager_service()
    await font_manager.bootstrap(persist_system_fonts=False)

    config = OzonTopSellerConfig()
    assets = build_ozon_top_seller_assets(cutout_png, config=config)
    cache = ImageAssetCache()
    for url, payload in assets.items():
        cache.put(url, payload)

    product_box = fit_product_box(assets[ASSET_PRODUCT])
    canvas = build_ozon_top_seller_canvas(product_box=product_box, config=config)
    # Validate Pydantic schema round-trip (JSON wire format → DTO).
    canvas = type(canvas).model_validate_json(
        json.dumps(canvas.model_dump(mode="json"))
    )

    renderer = CanvasServerRenderer(
        font_registry=FontRegistry(),
        font_manager=font_manager,
        image_cache=cache,
    )
    result = await renderer.render(canvas, output_format="png")
    out_path = out_dir / "canvas_render_test.png"
    out_path.write_bytes(result.image_bytes)
    return StageResult(
        name="canvas",
        ok=result.width > 0 and result.height > 0 and len(result.image_bytes) > 0,
        elapsed_ms=(time.perf_counter() - started) * 1000,
        detail=f"preset={OZON_TOP_SELLER_PRESET_ID} {result.width}x{result.height}",
        artifact=str(out_path.resolve()),
    )


async def stage_softbox(out_dir: Path, *, cutout_png: bytes) -> StageResult:
    started = time.perf_counter()
    light = StudioLightDTO(
        light_angle=180.0,
        light_elevation=65.0,
        color_temp_k=3200,
        intensity=1.05,
        softbox_diffusion=0.85,
    )
    # Validate DTO constraints.
    light = StudioLightDTO.model_validate(light.model_dump())
    engine = RelightingEngineService()
    result = await engine.process_custom(cutout_png, studio_light=light)
    out_path = out_dir / "softbox_lighting_test.png"
    out_path.write_bytes(result.image_png)
    return StageResult(
        name="softbox",
        ok=len(result.image_png) > 0,
        elapsed_ms=(time.perf_counter() - started) * 1000,
        detail=(
            f"{result.width}x{result.height} "
            f"K={light.color_temp_k} angle={light.light_angle}"
        ),
        artifact=str(out_path.resolve()),
    )


def stage_api_routes_sync() -> StageResult:
    started = time.perf_counter()
    from app.main import app

    openapi_paths = app.openapi()["paths"]
    missing = [
        f"{method} {path}"
        for method, path in _REQUIRED_API_PATHS
        if method.lower() not in (openapi_paths.get(path) or {})
    ]
    ok = not missing
    return StageResult(
        name="api_routes_sync",
        ok=ok,
        elapsed_ms=(time.perf_counter() - started) * 1000,
        detail="ok" if ok else f"missing={missing}",
    )


def stage_security() -> StageResult:
    started = time.perf_counter()
    backend_example = _BACKEND_ROOT / ".env.example"
    web_example = _BACKEND_ROOT.parent / "web" / ".env.example"
    issues: list[str] = []

    if not backend_example.is_file():
        issues.append("backend/.env.example missing")
    else:
        text = backend_example.read_text(encoding="utf-8")
        for key in (
            "DATABASE_URL",
            "JWT_SECRET_KEY",
            "ALLOWED_ORIGINS",
            "STABLE_DIFFUSION_API_KEY",
        ):
            if key not in text:
                issues.append(f"backend .env.example missing {key}")
        # No live-looking secrets in the example file.
        for bad in ("sk-proj-", "sk-ant-", "AKIA"):
            if bad in text:
                issues.append(f"possible live secret prefix in .env.example: {bad}")

    if not web_example.is_file():
        issues.append("web/.env.example missing")
    else:
        web_text = web_example.read_text(encoding="utf-8")
        if "NEXT_PUBLIC_API_BASE_URL" not in web_text:
            issues.append("web .env.example missing NEXT_PUBLIC_API_BASE_URL")

    from app.core.config import Settings
    from pydantic_settings import BaseSettings

    if not issubclass(Settings, BaseSettings):
        issues.append("Settings must inherit pydantic BaseSettings (env-backed)")
    model_fields = getattr(Settings, "model_fields", {})
    if "jwt_secret_key" not in model_fields:
        issues.append("JWT_SECRET_KEY field missing on Settings")
    if "database_url" not in model_fields:
        issues.append("DATABASE_URL field missing on Settings")

    ok = not issues
    return StageResult(
        name="security",
        ok=ok,
        elapsed_ms=(time.perf_counter() - started) * 1000,
        detail="ok" if ok else "; ".join(issues),
    )


def _print_colored_summary(
    *,
    backend_tests: str,
    frontend: str,
    api_sync: str,
    artifacts: str,
    security: str,
) -> None:
    green = "\033[92m"
    red = "\033[91m"
    reset = "\033[0m"

    def line(ok: bool, label: str, detail: str) -> None:
        mark = f"{green}[+]{reset}" if ok else f"{red}[-]{reset}"
        status = "OK" if ok else "FAILED"
        suffix = f" ({detail})" if detail and detail not in {"OK", "FAILED"} else ""
        if detail and detail.startswith("OK"):
            # detail already encodes status, e.g. "OK (617/617 tests)"
            print(f"{mark} {label}: {detail}")
        else:
            print(f"{mark} {label}: {status}{suffix}")

    print("\n" + "=" * 64)
    print("FULL STACK HEALTH SUMMARY")
    print("=" * 64)
    line(backend_tests.startswith("OK"), "Backend Test Suite", backend_tests)
    line(frontend.startswith("OK"), "Frontend TypeCheck & Build", frontend)
    line(api_sync.startswith("OK"), "API Routes Sync", api_sync)
    line(
        artifacts.startswith("OK"),
        "Visual Artifacts Generated",
        artifacts if artifacts.startswith("OK") else artifacts,
    )
    line(security.startswith("OK"), "Security Check", security)
    print("=" * 64)


async def _async_main(args: argparse.Namespace) -> int:
    out_dir = args.artifacts_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = args.assets_dir.resolve()
    assets_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_download:
        print("=== [assets] ensuring visual test assets ===")
        sneaker_path, mesh_path = await asyncio.to_thread(
            ensure_visual_test_assets,
            assets_dir,
        )
        print(f"  sneaker: {sneaker_path}")
        print(f"  mesh   : {mesh_path}")

    stages: list[StageResult] = []

    print("\n=== [parser] ===")
    stages.append(await stage_parser(out_dir, url=args.url))
    print(f"  {stages[-1].detail} ({stages[-1].elapsed_ms:.0f} ms)")

    cutout_png: bytes | None = None
    print("\n=== [cutout / defringe] ===")
    try:
        cutout_result, cutout_png = await stage_cutout(out_dir, assets_dir=assets_dir)
        stages.append(cutout_result)
        print(f"  {cutout_result.detail} ({cutout_result.elapsed_ms:.0f} ms)")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Cutout failed")
        stages.append(
            StageResult(
                name="cutout",
                ok=False,
                elapsed_ms=0.0,
                detail=f"{type(exc).__name__}: {exc}",
            )
        )
        sneaker = assets_dir / SNEAKER_PNG_FILENAME
        if sneaker.is_file():
            cutout_png = sneaker.read_bytes()

    if cutout_png is None:
        print("ERROR: no cutout bytes — aborting visual stages")
    else:
        print("\n=== [canvas ozon_top_seller] ===")
        try:
            stages.append(await stage_canvas(out_dir, cutout_png=cutout_png))
            print(f"  {stages[-1].detail} ({stages[-1].elapsed_ms:.0f} ms)")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Canvas failed")
            stages.append(
                StageResult(
                    name="canvas",
                    ok=False,
                    elapsed_ms=0.0,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )

        print("\n=== [softbox StudioLightDTO] ===")
        try:
            stages.append(await stage_softbox(out_dir, cutout_png=cutout_png))
            print(f"  {stages[-1].detail} ({stages[-1].elapsed_ms:.0f} ms)")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Softbox failed")
            stages.append(
                StageResult(
                    name="softbox",
                    ok=False,
                    elapsed_ms=0.0,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )

    print("\n=== [api routes sync] ===")
    api_stage = stage_api_routes_sync()
    stages.append(api_stage)
    print(f"  {api_stage.detail} ({api_stage.elapsed_ms:.0f} ms)")

    print("\n=== [security] ===")
    security_stage = stage_security()
    stages.append(security_stage)
    print(f"  {security_stage.detail} ({security_stage.elapsed_ms:.0f} ms)")

    overall_ok = all(item.ok for item in stages)
    report = HealthReport(
        generated_at=datetime.now(UTC).isoformat(),
        overall_ok=overall_ok,
        stages=[asdict(item) for item in stages],
        api_routes_sync={
            "required": [f"{m} {p}" for m, p in _REQUIRED_API_PATHS],
            "ok": api_stage.ok,
            "detail": api_stage.detail,
        },
        security={"ok": security_stage.ok, "detail": security_stage.detail},
        artifacts_dir=str(out_dir.resolve()),
    )
    report_path = out_dir / "health_report.json"
    _write_json(report_path, asdict(report))

    # External status strings filled by the caller / wrapper when available.
    backend_tests = os.environ.get("AUDIT_BACKEND_TESTS", "unknown")
    frontend = os.environ.get("AUDIT_FRONTEND", "unknown")
    _print_colored_summary(
        backend_tests=backend_tests if backend_tests != "unknown" else (
            "see pytest run"
        ),
        frontend=frontend if frontend != "unknown" else "see tsc/build run",
        api_sync="OK" if api_stage.ok else "FAILED",
        artifacts=(
            f"OK artifacts/system_health/"
            if any(s.name in {"canvas", "softbox", "cutout"} and s.ok for s in stages)
            else "FAILED"
        ),
        security="OK" if security_stage.ok else "FAILED",
    )
    print(f"\nHealth report: {report_path}")
    return 0 if overall_ok else 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Full-stack system health verification")
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=DEFAULT_ARTIFACTS_DIR,
    )
    parser.add_argument(
        "--assets-dir",
        type=Path,
        default=DEFAULT_ASSETS_DIR,
    )
    parser.add_argument("--url", type=str, default=None, help="WB/Ozon product URL")
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Reuse cached visual assets only",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        logger.exception("verify_full_stack failed")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
