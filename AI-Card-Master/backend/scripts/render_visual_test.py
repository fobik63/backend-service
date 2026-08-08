#!/usr/bin/env python3
"""Local visual E2E check for CanvasServerRenderer + 360° orbit video.

Downloads real graphical assets (transparent sneaker PNG + shoe .glb) when
missing, builds a rich CanvasStateDTO with drop-shadowed product photo, then
compiles a short studio-lit orbital MP4 + GIF preview from the real mesh.

Usage (from ``backend/``)::

    python scripts/render_visual_test.py
    python -m scripts.render_visual_test
    python scripts/render_visual_test.py --mesh path/to/model.glb
    python scripts/render_visual_test.py --backend software
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import math
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# Keep Settings bootstrap quiet for offline CLI use.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/ai_card_master_visual",
)
os.environ.setdefault("JWT_SECRET_KEY", "v" * 64)
os.environ.setdefault("STABLE_DIFFUSION_API_KEY", "visual-test-key")
os.environ.setdefault("MIDJOURNEY_PROVIDERS", "[]")
os.environ.setdefault("MIDJOURNEY_CALLBACK_BASE_URL", "https://api.visual.example")
os.environ.setdefault(
    "MIDJOURNEY_WEBHOOK_TOKEN", "visual-webhook-token-with-enough-entropy"
)
os.environ.setdefault(
    "MIDJOURNEY_REPLY_REF_SECRET", "visual-reply-ref-secret-" + ("z" * 48)
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("TELEGRAM_ERROR_LOGGING_ENABLED", "false")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from app.schemas.templates import (  # noqa: E402
    BadgeLayerDTO,
    CanvasStateDTO,
    ImageLayerDTO,
    ShapeLayerDTO,
    TextLayerDTO,
)
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
from app.services.three_d.errors import FFmpegEncodeError  # noqa: E402
from app.services.three_d.render_engine import (  # noqa: E402
    FFmpegPipeEncoder,
    Offscreen3DRenderer,
    RenderEngineConfig,
    build_mp4_ffmpeg_argv,
)
from app.services.three_d.styles import (  # noqa: E402
    LightingPresetName,
    RenderSettingsDTO,
    ShadowCatcherFloorSettings,
)

logger = logging.getLogger("render_visual_test")

DEFAULT_ARTIFACTS_DIR = _BACKEND_ROOT / "artifacts"
DEFAULT_ASSETS_DIR = DEFAULT_ARTIFACTS_DIR / "test_assets"
CANVAS_OUT_NAME = "real_canvas_output.png"
OZON_CARD_OUT_NAME = "ozon_perfect_card.png"
VIDEO_OUT_NAME = "real_360_output.mp4"
PREVIEW_OUT_NAME = "real_360_preview.gif"

SNEAKER_PNG_FILENAME = "sneaker_transparent.png"
CLEAN_CUTOUT_FILENAME = "clean_cutout.png"
MESH_GLB_FILENAME = "MaterialsVariantsShoe.glb"

# Public CDN mirrors — first success wins. PNG must carry a real Alpha channel.
SNEAKER_PNG_URLS: tuple[str, ...] = (
    "https://pngimg.com/uploads/running_shoes/running_shoes_PNG5825.png",
    "https://pngimg.com/d/running_shoes_PNG5823.png",
)
MESH_GLB_URLS: tuple[str, ...] = (
    "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/"
    "main/Models/MaterialsVariantsShoe/glTF-Binary/MaterialsVariantsShoe.glb",
    "https://cdn.jsdelivr.net/gh/KhronosGroup/glTF-Sample-Assets@main/"
    "Models/MaterialsVariantsShoe/glTF-Binary/MaterialsVariantsShoe.glb",
)

_DOWNLOAD_USER_AGENT = (
    "AI-Card-Master-VisualTest/1.0 (+https://github.com/; visual E2E assets)"
)
_DOWNLOAD_TIMEOUT_SECONDS = 120.0

# Candidate locations for a bundled / previously cached product mesh.
_DEFAULT_MESH_CANDIDATES: tuple[Path, ...] = (
    DEFAULT_ASSETS_DIR / MESH_GLB_FILENAME,
    _BACKEND_ROOT / "app" / "assets" / "meshes" / "default.glb",
    _BACKEND_ROOT / "app" / "assets" / "meshes" / "sample_product.glb",
    _BACKEND_ROOT / "storage" / "meshes" / "default.glb",
    _BACKEND_ROOT / "fixtures" / "sample_product.glb",
)

# 3 s @ 24 fps — short enough for a local smoke run, long enough to see motion.
VIDEO_DURATION_SECONDS = 3
VIDEO_FPS = 24
VIDEO_FRAME_COUNT = VIDEO_DURATION_SECONDS * VIDEO_FPS
# 3:4 marketplace aspect at half-HD keeps software raster practical locally.
VIDEO_WIDTH = 540
VIDEO_HEIGHT = 720
PREVIEW_MAX_SIDE = 360
PREVIEW_FPS = 12


# ---------------------------------------------------------------------------
# Asset download
# ---------------------------------------------------------------------------


def _download_bytes(url: str, *, timeout: float = _DOWNLOAD_TIMEOUT_SECONDS) -> bytes:
    """Fetch ``url`` with a browser-like User-Agent (some CDNs block bare clients)."""

    request = urllib.request.Request(
        url,
        headers={"User-Agent": _DOWNLOAD_USER_AGENT, "Accept": "*/*"},
        method="GET",
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        payload = response.read()
    if not payload:
        raise RuntimeError(f"Empty download from {url}")
    return payload


def _download_first_available(
    urls: tuple[str, ...],
    dest: Path,
    *,
    label: str,
    validate,
) -> Path:
    """Try each URL until one validates; write atomically to ``dest``."""

    dest.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for url in urls:
        try:
            logger.info("Downloading %s from %s …", label, url)
            payload = _download_bytes(url)
            validate(payload)
            tmp = dest.with_suffix(dest.suffix + ".partial")
            tmp.write_bytes(payload)
            tmp.replace(dest)
            logger.info("Saved %s → %s (%s bytes)", label, dest, len(payload))
            return dest
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            OSError,
            RuntimeError,
            ValueError,
        ) as exc:
            msg = f"{url}: {exc}"
            errors.append(msg)
            logger.warning("Failed %s download (%s)", label, msg)
    raise RuntimeError(
        f"Could not download {label}. Tried {len(urls)} URL(s):\n  - "
        + "\n  - ".join(errors)
    )


def _validate_transparent_png(payload: bytes) -> None:
    """Require a PNG with a usable Alpha channel (not a flat opaque plate)."""

    if len(payload) < 24 or payload[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Not a PNG file")
    with Image.open(io.BytesIO(payload)) as image:
        image.load()
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        extrema = alpha.getextrema()
        if extrema is None or extrema[0] >= 250:
            raise ValueError("PNG has no transparent Alpha channel")
        if rgba.getbbox() is None:
            raise ValueError("PNG is fully transparent")


def _validate_glb(payload: bytes) -> None:
    """Minimal glTF binary magic check."""

    if len(payload) < 12 or payload[:4] != b"glTF":
        raise ValueError("Not a GLB (missing glTF magic)")


def ensure_visual_test_assets(assets_dir: Path) -> tuple[Path, Path]:
    """Ensure sneaker PNG + shoe GLB exist on disk; download when missing.

    Returns
    -------
    (sneaker_png_path, mesh_glb_path)
    """

    assets_dir = assets_dir.resolve()
    assets_dir.mkdir(parents=True, exist_ok=True)

    sneaker_path = assets_dir / SNEAKER_PNG_FILENAME
    mesh_path = assets_dir / MESH_GLB_FILENAME

    if sneaker_path.is_file() and sneaker_path.stat().st_size > 0:
        try:
            _validate_transparent_png(sneaker_path.read_bytes())
            logger.info("Reusing cached sneaker PNG: %s", sneaker_path)
        except (OSError, ValueError) as exc:
            logger.warning("Cached sneaker PNG invalid (%s); re-downloading", exc)
            sneaker_path.unlink(missing_ok=True)

    if not sneaker_path.is_file():
        _download_first_available(
            SNEAKER_PNG_URLS,
            sneaker_path,
            label="transparent sneaker PNG",
            validate=_validate_transparent_png,
        )

    if mesh_path.is_file() and mesh_path.stat().st_size > 0:
        try:
            _validate_glb(mesh_path.read_bytes()[:64])
            logger.info("Reusing cached shoe GLB: %s", mesh_path)
        except (OSError, ValueError) as exc:
            logger.warning("Cached shoe GLB invalid (%s); re-downloading", exc)
            mesh_path.unlink(missing_ok=True)

    if not mesh_path.is_file():
        _download_first_available(
            MESH_GLB_URLS,
            mesh_path,
            label="shoe GLB mesh",
            validate=_validate_glb,
        )

    return sneaker_path, mesh_path


# ---------------------------------------------------------------------------
# Canvas helpers
# ---------------------------------------------------------------------------


def _gradient_png(
    size: tuple[int, int] = (1080, 1440),
    top: tuple[int, int, int] = (28, 22, 18),
    bottom: tuple[int, int, int] = (212, 196, 168),
) -> bytes:
    """Studio beige / warm dark vertical gradient for marketplace cards."""

    width, height = size
    image = Image.new("RGBA", size)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(1, height - 1)
        # Ease toward a soft beige mid/lower plate.
        ease = t * t * (3.0 - 2.0 * t)
        rgb = tuple(int(top[i] + (bottom[i] - top[i]) * ease) for i in range(3))
        draw.line([(0, y), (width, y)], fill=(*rgb, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _product_placeholder_png(size: tuple[int, int] = (720, 720)) -> bytes:
    """Soft studio product plate with a cleaner sneaker silhouette.

    Kept as an offline fallback when the real CDN download is unavailable.
    """

    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = 36
    # Soft studio card under the product.
    draw.rounded_rectangle(
        (margin, margin, size[0] - margin, size[1] - margin),
        radius=56,
        fill=(252, 248, 240, 240),
        outline=(230, 214, 190, 255),
        width=3,
    )
    # Soft contact ellipse (grounding shadow).
    cx, cy = size[0] // 2, size[1] // 2 + 40
    draw.ellipse(
        (cx - 210, cy + 90, cx + 210, cy + 150),
        fill=(40, 32, 24, 55),
    )
    # Sneaker body / sole / accent — layered rounded forms.
    draw.rounded_rectangle(
        (cx - 200, cy - 30, cx + 210, cy + 95),
        radius=80,
        fill=(28, 26, 24, 255),
    )
    draw.rounded_rectangle(
        (cx - 150, cy - 110, cx + 90, cy + 20),
        radius=70,
        fill=(72, 64, 56, 255),
    )
    draw.ellipse(
        (cx + 70, cy - 50, cx + 190, cy + 55),
        fill=(212, 175, 55, 230),
    )
    draw.rounded_rectangle(
        (cx - 190, cy + 55, cx + 200, cy + 100),
        radius=20,
        fill=(245, 245, 245, 255),
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _apply_drop_shadow(
    png_bytes: bytes,
    *,
    offset_x: int = 10,
    offset_y: int = 32,
    blur_radius: int = 32,
    shadow_opacity: int = 150,
) -> bytes:
    """Composite a soft Gaussian drop shadow under a transparent product PNG."""

    with Image.open(io.BytesIO(png_bytes)) as source:
        source.load()
        product = source.convert("RGBA")

    bbox = product.getbbox()
    if bbox is not None:
        product = product.crop(bbox)

    pad = max(blur_radius * 2, abs(offset_x), abs(offset_y)) + 16
    canvas_w = product.width + pad * 2 + abs(offset_x)
    canvas_h = product.height + pad * 2 + abs(offset_y)
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    alpha = product.getchannel("A")
    shadow_alpha = alpha.point(lambda pixel: (pixel * shadow_opacity) // 255)
    shadow = Image.new("RGBA", product.size, (0, 0, 0, 0))
    shadow.putalpha(shadow_alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    origin_x, origin_y = pad, pad
    canvas.alpha_composite(
        shadow,
        (origin_x + offset_x, origin_y + offset_y),
    )
    canvas.alpha_composite(product, (origin_x, origin_y))

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _product_fit_box(
    image_bytes: bytes,
    *,
    canvas_w: int = 1080,
    canvas_h: int = 1440,
    max_w: float = 820.0,
    max_h: float = 720.0,
    center_y: float = 700.0,
) -> tuple[float, float, float, float]:
    """Return ``(x, y, width, height)`` that preserves aspect inside the card."""

    with Image.open(io.BytesIO(image_bytes)) as image:
        image.load()
        src_w, src_h = image.size
    if src_w < 1 or src_h < 1:
        return ((canvas_w - max_w) / 2.0, center_y - max_h / 2.0, max_w, max_h)

    scale = min(max_w / float(src_w), max_h / float(src_h))
    width = float(src_w) * scale
    height = float(src_h) * scale
    x = (float(canvas_w) - width) / 2.0
    y = center_y - height / 2.0
    # Keep product inside the canvas with a small margin.
    y = max(220.0, min(float(canvas_h) - height - 260.0, y))
    return x, y, width, height


def build_test_canvas(
    *,
    bg_url: str,
    product_url: str,
    product_box: tuple[float, float, float, float] | None = None,
) -> CanvasStateDTO:
    """Rich 1080×1440 marketplace card — Cyrillic Inter/Montserrat/Roboto."""

    if product_box is None:
        px, py, pw, ph = 180.0, 380.0, 720.0, 720.0
    else:
        px, py, pw, ph = product_box

    # Soft elliptical contact shadow under the product (z below ImageLayer).
    shadow_w = pw * 0.78
    shadow_h = max(36.0, ph * 0.10)
    shadow_x = px + (pw - shadow_w) / 2.0
    shadow_y = py + ph - shadow_h * 0.55

    return CanvasStateDTO(
        width=1080,
        height=1440,
        background_color="#1C1612",
        background_image_url=bg_url,
        layers=[
            ShapeLayerDTO(
                id=uuid4(),
                name="product-contact-shadow",
                x=shadow_x,
                y=shadow_y,
                width=shadow_w,
                height=shadow_h,
                z_index=0,
                opacity=0.42,
                shape_type="circle",
                fill_color="#00000099",
            ),
            ImageLayerDTO(
                id=uuid4(),
                name="product-sneaker",
                x=px,
                y=py,
                width=pw,
                height=ph,
                z_index=1,
                url=product_url,
                scale_x=1.0,
                scale_y=1.0,
            ),
            TextLayerDTO(
                id=uuid4(),
                name="title-inter-bold",
                x=72.0,
                y=100.0,
                width=650.0,
                height=150.0,
                z_index=10,
                text="Кроссовки Nike Air Max",
                font_family="Inter",
                font_size=56,
                font_weight="bold",
                color_hex="#FFFFFF",
                alignment="left",
                line_height=1.15,
                shadow_color="#000000AA",
                shadow_blur=10.0,
            ),
            TextLayerDTO(
                id=uuid4(),
                name="subtitle-montserrat-gold",
                x=90.0,
                y=270.0,
                width=780.0,
                height=70.0,
                rotation=-15.0,
                z_index=11,
                text="ЛЕТНЯЯ КОЛЛЕКЦИЯ 2026",
                font_family="Montserrat",
                font_size=34,
                font_weight="bold",
                color_hex="#D4AF37",
                alignment="left",
                line_height=1.2,
                letter_spacing=3.0,
                shadow_color="#00000066",
                shadow_blur=4.0,
            ),
            TextLayerDTO(
                id=uuid4(),
                name="body-roboto-cyrillic",
                x=90.0,
                y=1140.0,
                width=900.0,
                height=220.0,
                z_index=12,
                text=(
                    "Лёгкая сетка, амортизация React и уверенный сцеп с "
                    "асфальтом — идеальный выбор для городских пробежек "
                    "и повседневных образов этим летом."
                ),
                font_family="Roboto",
                font_size=30,
                font_weight="regular",
                color_hex="#F5F0E8",
                alignment="left",
                line_height=1.45,
            ),
            BadgeLayerDTO(
                id=uuid4(),
                name="price-badge",
                x=760.0,
                y=115.0,
                width=260.0,
                height=96.0,
                z_index=20,
                badge_type="discount",
                text="12 890 ₽",
                bg_color="#E11D48",
                text_color="#FFFFFF",
            ),
        ],
    )


def _resolve_product_cutout(
    *,
    sneaker_path: Path | None,
    artifacts_dir: Path,
) -> tuple[bytes, str]:
    """Prefer cleaned cutout → cached sneaker → drawn placeholder."""

    candidates: list[Path] = []
    clean = artifacts_dir / CLEAN_CUTOUT_FILENAME
    if clean.is_file():
        candidates.append(clean)
    if sneaker_path is not None:
        candidates.append(sneaker_path)
    assets_sneaker = DEFAULT_ASSETS_DIR / SNEAKER_PNG_FILENAME
    if assets_sneaker.is_file():
        candidates.append(assets_sneaker)

    for path in candidates:
        if not path.is_file():
            continue
        try:
            payload = path.read_bytes()
            _validate_transparent_png(payload)
            logger.info("Using product cutout: %s", path.resolve())
            return payload, str(path.resolve())
        except (OSError, ValueError) as exc:
            logger.warning("Skipping cutout %s (%s)", path, exc)

    logger.warning("No transparent cutout found — falling back to drawn placeholder")
    return _product_placeholder_png(), "placeholder"


async def render_ozon_top_seller_artifact(
    artifacts_dir: Path,
    *,
    sneaker_path: Path | None = None,
) -> Path:
    """Render the ``ozon_top_seller`` commercial preset → ``ozon_perfect_card.png``."""

    ensure_default_fonts()
    font_manager = get_font_manager_service()
    await font_manager.bootstrap(persist_system_fonts=False)

    product_source, source_label = _resolve_product_cutout(
        sneaker_path=sneaker_path,
        artifacts_dir=artifacts_dir,
    )
    config = OzonTopSellerConfig()
    assets = build_ozon_top_seller_assets(product_source, config=config)
    cache = ImageAssetCache()
    for url, payload in assets.items():
        cache.put(url, payload)

    product_box = fit_product_box(assets[ASSET_PRODUCT])
    canvas = build_ozon_top_seller_canvas(
        product_box=product_box,
        config=config,
    )
    renderer = CanvasServerRenderer(
        font_registry=FontRegistry(),
        font_manager=font_manager,
        image_cache=cache,
    )
    result = await renderer.render(canvas, output_format="png")

    out_path = artifacts_dir / OZON_CARD_OUT_NAME
    out_path.write_bytes(result.image_bytes)
    logger.info(
        "Ozon Top Seller (%s) PNG saved: %s (%sx%s, %s bytes, source=%s)",
        OZON_TOP_SELLER_PRESET_ID,
        out_path,
        result.width,
        result.height,
        len(result.image_bytes),
        source_label,
    )
    return out_path.resolve()


async def render_canvas_artifact(
    artifacts_dir: Path,
    *,
    sneaker_path: Path | None = None,
) -> Path:
    """Ensure fonts, render canvas with real sneaker + drop shadow, write PNG."""

    ensure_default_fonts()
    font_manager = get_font_manager_service()
    await font_manager.bootstrap(persist_system_fonts=False)

    bg_url = "memory://visual-test/gradient-bg.png"
    product_url = "memory://visual-test/sneaker-drop-shadow.png"
    cache = ImageAssetCache()
    cache.put(bg_url, _gradient_png())

    product_source: bytes
    if sneaker_path is not None and sneaker_path.is_file():
        product_source = sneaker_path.read_bytes()
        logger.info("Using real sneaker PNG: %s", sneaker_path.resolve())
    else:
        logger.warning("Sneaker PNG missing — falling back to drawn placeholder")
        product_source = _product_placeholder_png()

    product_with_shadow = _apply_drop_shadow(product_source)
    cache.put(product_url, product_with_shadow)
    product_box = _product_fit_box(product_with_shadow)

    canvas = build_test_canvas(
        bg_url=bg_url,
        product_url=product_url,
        product_box=product_box,
    )
    renderer = CanvasServerRenderer(
        font_registry=FontRegistry(),
        font_manager=font_manager,
        image_cache=cache,
    )
    result = await renderer.render(canvas, output_format="png")

    out_path = artifacts_dir / CANVAS_OUT_NAME
    out_path.write_bytes(result.image_bytes)
    logger.info(
        "Canvas PNG saved: %s (%sx%s, %s bytes)",
        out_path,
        result.width,
        result.height,
        len(result.image_bytes),
    )
    return out_path.resolve()


# ---------------------------------------------------------------------------
# 360° mesh + video helpers
# ---------------------------------------------------------------------------


def _find_default_mesh() -> Path | None:
    for candidate in _DEFAULT_MESH_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def _icosphere_obj(*, subdivisions: int = 5, radius: float = 1.0) -> bytes:
    """Generate a high-poly smooth icosphere OBJ (subdivision >= 5)."""

    t = (1.0 + math.sqrt(5.0)) / 2.0
    verts: list[tuple[float, float, float]] = [
        (-1, t, 0),
        (1, t, 0),
        (-1, -t, 0),
        (1, -t, 0),
        (0, -1, t),
        (0, 1, t),
        (0, -1, -t),
        (0, 1, -t),
        (t, 0, -1),
        (t, 0, 1),
        (-t, 0, -1),
        (-t, 0, 1),
    ]

    def _norm(v: tuple[float, float, float]) -> tuple[float, float, float]:
        length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
        return (v[0] / length * radius, v[1] / length * radius, v[2] / length * radius)

    verts = [_norm(v) for v in verts]
    faces: list[tuple[int, int, int]] = [
        (0, 11, 5),
        (0, 5, 1),
        (0, 1, 7),
        (0, 7, 10),
        (0, 10, 11),
        (1, 5, 9),
        (5, 11, 4),
        (11, 10, 2),
        (10, 7, 6),
        (7, 1, 8),
        (3, 9, 4),
        (3, 4, 2),
        (3, 2, 6),
        (3, 6, 8),
        (3, 8, 9),
        (4, 9, 5),
        (2, 4, 11),
        (6, 2, 10),
        (8, 6, 7),
        (9, 8, 1),
    ]

    midpoint_cache: dict[tuple[int, int], int] = {}

    def _midpoint(i: int, j: int) -> int:
        key = (i, j) if i < j else (j, i)
        cached = midpoint_cache.get(key)
        if cached is not None:
            return cached
        a, b = verts[i], verts[j]
        mid = _norm(((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5, (a[2] + b[2]) * 0.5))
        idx = len(verts)
        verts.append(mid)
        midpoint_cache[key] = idx
        return idx

    levels = max(5, int(subdivisions))
    for _ in range(levels):
        next_faces: list[tuple[int, int, int]] = []
        for i, j, k in faces:
            a = _midpoint(i, j)
            b = _midpoint(j, k)
            c = _midpoint(k, i)
            next_faces.extend(((i, a, c), (j, b, a), (k, c, b), (a, b, c)))
        faces = next_faces

    lines = [
        "# visual-test high-poly icosphere (smooth shading)",
        f"# verts={len(verts)} faces={len(faces)} subdivisions={levels}",
    ]
    for x, y, z in verts:
        lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
    for i, j, k in faces:
        lines.append(f"f {i + 1} {j + 1} {k + 1}")
    return ("\n".join(lines) + "\n").encode("ascii")


def _ffmpeg_supports_palettegen(ffmpeg_bin: str) -> bool:
    """Return True when FFmpeg can build GIF via ``palettegen`` (modern builds)."""

    import shutil
    import subprocess

    resolved = shutil.which(ffmpeg_bin) or ffmpeg_bin
    try:
        proc = subprocess.run(
            [resolved, "-hide_banner", "-filters"],
            capture_output=True,
            timeout=12,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, FileNotFoundError):
        return False
    blob = (proc.stdout or b"") + (proc.stderr or b"")
    return b"palettegen" in blob


def _encode_gif_pillow(
    frames_rgb24: list[bytes],
    *,
    width: int,
    height: int,
    fps: int,
    max_side: int = PREVIEW_MAX_SIDE,
) -> bytes:
    """Encode an animated GIF without relying on FFmpeg ``palettegen``.

    Older Windows FFmpeg nightlies (e.g. Zeranoe N-55702) ship without
    ``palettegen`` / ``libwebp``; Pillow keeps the visual E2E portable.
    """

    if not frames_rgb24:
        raise RuntimeError("No RGB frames available for GIF preview.")

    scale = min(1.0, float(max_side) / float(max(width, height)))
    out_w = max(1, int(round(width * scale)))
    out_h = max(1, int(round(height * scale)))
    duration_ms = max(1, int(round(1000.0 / max(1, fps))))

    images: list[Image.Image] = []
    for rgb in frames_rgb24:
        frame = Image.frombytes("RGB", (width, height), rgb)
        if (out_w, out_h) != (width, height):
            frame = frame.resize((out_w, out_h), Image.Resampling.LANCZOS)
        images.append(frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=256))

    buffer = io.BytesIO()
    images[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=images[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
    )
    return buffer.getvalue()


def _render_orbit_with_pillow_gif(
    renderer: Offscreen3DRenderer,
    cfg: RenderEngineConfig,
) -> tuple[bytes, bytes, str]:
    """MP4 via FFmpeg pipe + GIF via Pillow (legacy-FFmpeg-safe path)."""

    ffmpeg_bin = cfg.ffmpeg_bin
    mp4 = FFmpegPipeEncoder(
        argv=build_mp4_ffmpeg_argv(
            ffmpeg_bin=ffmpeg_bin,
            width=cfg.width,
            height=cfg.height,
            fps=cfg.fps,
            crf=cfg.mp4_crf,
            preset=cfg.mp4_preset,
        ),
        width=cfg.width,
        height=cfg.height,
        label="ffmpeg-mp4",
    )
    preview_stride = max(1, int(round(cfg.fps / float(PREVIEW_FPS))))
    preview_frames: list[bytes] = []
    try:
        mp4.start()
        for index, frame in enumerate(renderer.iter_orbit_frames()):
            mp4.write_frame(frame)
            if index % preview_stride == 0:
                preview_frames.append(frame)
        mp4_buf = mp4.finish()
    except Exception:
        mp4.close(abort=True)
        raise

    gif_bytes = _encode_gif_pillow(
        preview_frames,
        width=cfg.width,
        height=cfg.height,
        fps=PREVIEW_FPS,
        max_side=cfg.preview_max_side,
    )
    backend_name = cfg.backend if cfg.backend != "auto" else "auto"
    if renderer._frame_backend is not None:  # noqa: SLF001 - diagnostic only
        backend_name = renderer._frame_backend.name
    return mp4_buf.getvalue(), gif_bytes, backend_name


def render_orbit_artifacts(
    artifacts_dir: Path,
    *,
    mesh_path: Path | None,
    backend: str,
) -> tuple[Path, Path]:
    """Compile a 3-second studio_soft orbit MP4 + GIF preview from a real mesh."""

    settings = RenderSettingsDTO.for_marketplace_card(
        width=VIDEO_WIDTH,
        height=VIDEO_HEIGHT,
        lighting_preset=LightingPresetName.STUDIO_SOFT,
        # Lighter studio plate so Key/Fill/Rim and the contact shadow read clearly.
        background_rgb=(52, 56, 68),
        shadow_catcher=ShadowCatcherFloorSettings(
            enabled=True,
            shadow_strength=0.88,
            shadow_softness=0.78,
            opacity=0.72,
        ),
    )
    cfg = RenderEngineConfig.from_studio_settings(
        settings,
        fps=VIDEO_FPS,
        frame_count=VIDEO_FRAME_COUNT,
        backend=backend,  # type: ignore[arg-type]
        preview_format="gif",
        cache_dir=artifacts_dir / "mesh_cache",
        ffmpeg_bin=os.environ.get("THREE_D_FFMPEG_BIN", "ffmpeg"),
        preview_max_side=PREVIEW_MAX_SIDE,
        preview_fps=PREVIEW_FPS,
        ssaa_factor=2,
        mesh_subdivisions=0,
    )

    resolved_mesh = mesh_path if mesh_path and mesh_path.is_file() else _find_default_mesh()

    with Offscreen3DRenderer(cfg) as renderer:
        if resolved_mesh is not None:
            logger.info("Loading mesh from %s", resolved_mesh.resolve())
            renderer.load_mesh_file(resolved_mesh)
        else:
            logger.info(
                "No .glb found — generating high-poly icosphere "
                "(subdivision=5, smooth normals) for orbit test"
            )
            renderer.load_mesh_bytes(
                _icosphere_obj(subdivisions=5),
                source_name="visual_icosphere.obj",
            )

        mp4_bytes: bytes
        gif_bytes: bytes
        used_backend: str
        use_native_preview = _ffmpeg_supports_palettegen(cfg.ffmpeg_bin)
        if use_native_preview:
            try:
                result = renderer.render_orbit_video()
                mp4_bytes = result.mp4_bytes
                gif_bytes = result.preview_bytes
                used_backend = result.backend
            except (OSError, FFmpegEncodeError) as exc:
                logger.warning(
                    "Native FFmpeg GIF preview failed (%s); "
                    "falling back to MP4 pipe + Pillow GIF.",
                    exc,
                )
                mp4_bytes, gif_bytes, used_backend = _render_orbit_with_pillow_gif(
                    renderer, cfg
                )
        else:
            logger.warning(
                "FFmpeg build lacks palettegen; encoding GIF with Pillow "
                "(MP4 still via FFmpeg)."
            )
            mp4_bytes, gif_bytes, used_backend = _render_orbit_with_pillow_gif(
                renderer, cfg
            )

    mp4_path = artifacts_dir / VIDEO_OUT_NAME
    gif_path = artifacts_dir / PREVIEW_OUT_NAME
    mp4_path.write_bytes(mp4_bytes)
    gif_path.write_bytes(gif_bytes)
    logger.info(
        "360° video saved: %s (%s frames @ %sfps, backend=%s, %s bytes)",
        mp4_path,
        VIDEO_FRAME_COUNT,
        VIDEO_FPS,
        used_backend,
        len(mp4_bytes),
    )
    logger.info("360° preview GIF saved: %s (%s bytes)", gif_path, len(gif_bytes))
    return mp4_path.resolve(), gif_path.resolve()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Visual E2E: real sneaker Canvas PNG + shoe GLB 360° orbit",
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
        help=f"Cached real assets directory (default: {DEFAULT_ASSETS_DIR})",
    )
    parser.add_argument(
        "--mesh",
        type=Path,
        default=None,
        help="Optional path to .glb / .obj (default: downloaded MaterialsVariantsShoe)",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "pyvista", "moderngl", "software"),
        default=os.environ.get("THREE_D_RENDER_BACKEND", "auto"),
        help="Offscreen GL / software backend (default: auto)",
    )
    parser.add_argument(
        "--skip-canvas",
        action="store_true",
        help="Skip CanvasServerRenderer PNG pass",
    )
    parser.add_argument(
        "--legacy-canvas",
        action="store_true",
        help="Also render the older real_canvas_output.png demo card",
    )
    parser.add_argument(
        "--skip-video",
        action="store_true",
        help="Skip 360° orbit video pass",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Do not download assets (use cache / --mesh / placeholder only)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG logging",
    )
    return parser.parse_args(argv)


async def _async_main(args: argparse.Namespace) -> int:
    artifacts_dir = args.artifacts_dir.resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = args.assets_dir.resolve()

    sneaker_path: Path | None = None
    mesh_path: Path | None = args.mesh

    if not args.skip_download:
        print("=== [0/2] Ensuring real graphical assets ===")
        sneaker_path, downloaded_mesh = await asyncio.to_thread(
            ensure_visual_test_assets,
            assets_dir,
        )
        if mesh_path is None:
            mesh_path = downloaded_mesh
        print(f"  sneaker: {sneaker_path}")
        print(f"  mesh   : {mesh_path}")
    else:
        cached_sneaker = assets_dir / SNEAKER_PNG_FILENAME
        sneaker_path = cached_sneaker if cached_sneaker.is_file() else None
        if mesh_path is None:
            mesh_path = _find_default_mesh()

    canvas_path: Path | None = None
    ozon_path: Path | None = None
    mp4_path: Path | None = None
    gif_path: Path | None = None

    if not args.skip_canvas:
        print(
            f"=== [1/2] Ozon Top Seller preset ({OZON_TOP_SELLER_PRESET_ID}) ==="
        )
        ozon_path = await render_ozon_top_seller_artifact(
            artifacts_dir,
            sneaker_path=sneaker_path,
        )
        if args.legacy_canvas:
            print("=== [1b/2] Legacy canvas demo (real_canvas_output.png) ===")
            canvas_path = await render_canvas_artifact(
                artifacts_dir,
                sneaker_path=sneaker_path,
            )
    else:
        print("=== [1/2] CanvasServerRenderer (skipped) ===")

    if not args.skip_video:
        print("=== [2/2] 360° orbit video (studio_soft, real GLB) ===")
        mp4_path, gif_path = await asyncio.to_thread(
            render_orbit_artifacts,
            artifacts_dir,
            mesh_path=mesh_path,
            backend=args.backend,
        )
    else:
        print("=== [2/2] 360° orbit video (skipped) ===")

    print()
    print("Visual E2E artifacts:")
    if ozon_path is not None:
        print(f"  ozon   : {ozon_path}")
    if canvas_path is not None:
        print(f"  canvas : {canvas_path}")
    if mp4_path is not None:
        print(f"  video  : {mp4_path}")
    if gif_path is not None:
        print(f"  preview: {gif_path}")
    return 0


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
    except Exception as exc:  # noqa: BLE001 - top-level CLI boundary
        logger.exception("Visual E2E failed: %s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
