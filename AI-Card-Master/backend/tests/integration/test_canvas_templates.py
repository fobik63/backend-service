"""Integration: CanvasStateDTO → PNG via CanvasServerRenderer.

Covers PNG generation, z-index compositing order, and missing-font fallback.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from app.schemas.templates import CanvasStateDTO, TextLayerDTO
from app.services.templates.font_manager import (
    DEFAULT_FALLBACK_FAMILY,
    FontManagerService,
    reset_font_manager_service_for_tests,
)
from app.services.templates.fonts import FontRegistry
from app.services.templates.image_cache import ImageAssetCache
from app.services.templates.renderer import CanvasServerRenderer


def _png_bytes(
    color: tuple[int, int, int, int] = (200, 40, 40, 255),
    size: tuple[int, int] = (200, 200),
) -> bytes:
    image = Image.new("RGBA", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _reset_font_manager() -> None:
    reset_font_manager_service_for_tests()
    yield
    reset_font_manager_service_for_tests()


@pytest.mark.asyncio
async def test_canvas_state_dto_renders_valid_png() -> None:
    """Full CanvasStateDTO document produces a real PNG bitmap."""

    cache = ImageAssetCache()
    product_url = "memory://product-integration.png"
    cache.put(product_url, _png_bytes((32, 160, 80, 255), size=(400, 400)))

    payload = {
        "width": 1080,
        "height": 1440,
        "background_color": "#FAFAFA",
        "layers": [
            {
                "layer_type": "shape",
                "id": str(uuid4()),
                "name": "footer",
                "x": 0.0,
                "y": 1320.0,
                "width": 1080.0,
                "height": 120.0,
                "z_index": 0,
                "shape_type": "rect",
                "fill_color": "#0F172A",
            },
            {
                "layer_type": "image",
                "id": str(uuid4()),
                "name": "product",
                "x": 140.0,
                "y": 180.0,
                "width": 800.0,
                "height": 800.0,
                "z_index": 2,
                "url": product_url,
                "scale_x": 1.0,
                "scale_y": 1.0,
            },
            {
                "layer_type": "text",
                "id": str(uuid4()),
                "name": "title",
                "x": 80.0,
                "y": 1040.0,
                "width": 920.0,
                "height": 140.0,
                "z_index": 4,
                "text": "Интеграционный тест рендера карточки",
                "font_family": "DejaVuSans",
                "font_size": 44,
                "font_weight": "bold",
                "color_hex": "#111827",
                "alignment": "center",
                "line_height": 1.2,
            },
            {
                "layer_type": "badge",
                "id": str(uuid4()),
                "name": "discount",
                "x": 64.0,
                "y": 64.0,
                "width": 200.0,
                "height": 72.0,
                "z_index": 6,
                "badge_type": "discount",
                "text": "-40%",
                "bg_color": "#DC2626",
                "text_color": "#FFFFFF",
            },
        ],
    }
    canvas = CanvasStateDTO.model_validate_json(json.dumps(payload))

    renderer = CanvasServerRenderer(
        font_registry=FontRegistry(),
        image_cache=cache,
    )
    result = await renderer.render(canvas, output_format="png")

    assert result.mime_type == "image/png"
    assert result.extension == ".png"
    assert result.width == 1080
    assert result.height == 1440
    assert result.image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(result.image_bytes) > 2_000

    with Image.open(io.BytesIO(result.image_bytes)) as image:
        assert image.format == "PNG"
        assert image.size == (1080, 1440)
        # Footer shape should paint near the bottom edge.
        footer_pixel = image.convert("RGBA").getpixel((540, 1380))
        assert footer_pixel[0] < 40 and footer_pixel[2] < 60


@pytest.mark.asyncio
async def test_z_index_sorts_layers_bottom_to_top() -> None:
    """Lower z_index paints first; higher z_index wins at overlapping pixels."""

    cache = ImageAssetCache()
    green_url = "memory://green.png"
    magenta_url = "memory://magenta.png"
    cache.put(green_url, _png_bytes((0, 220, 0, 255), size=(120, 120)))
    cache.put(magenta_url, _png_bytes((220, 0, 220, 255), size=(120, 120)))

    # Intentionally out-of-order in the JSON array — sort must use z_index.
    payload = {
        "width": 240,
        "height": 240,
        "background_color": "#FFFFFF",
        "layers": [
            {
                "layer_type": "image",
                "id": str(uuid4()),
                "name": "top-magenta",
                "x": 60.0,
                "y": 60.0,
                "width": 120.0,
                "height": 120.0,
                "z_index": 50,
                "url": magenta_url,
                "scale_x": 1.0,
                "scale_y": 1.0,
            },
            {
                "layer_type": "image",
                "id": str(uuid4()),
                "name": "bottom-green",
                "x": 60.0,
                "y": 60.0,
                "width": 120.0,
                "height": 120.0,
                "z_index": 5,
                "url": green_url,
                "scale_x": 1.0,
                "scale_y": 1.0,
            },
        ],
    }
    canvas = CanvasStateDTO.model_validate_json(json.dumps(payload))
    renderer = CanvasServerRenderer(image_cache=cache)
    result = await renderer.render(canvas, output_format="png", width=240, height=240)

    with Image.open(io.BytesIO(result.image_bytes)) as image:
        pixel = image.convert("RGBA").getpixel((120, 120))

    # Magenta (high z_index) must be on top.
    assert pixel[0] > 180 and pixel[2] > 180 and pixel[1] < 80


@pytest.mark.asyncio
async def test_missing_font_falls_back_and_still_renders(tmp_path: Path) -> None:
    """Unknown font_family falls back to Inter; render must not crash."""

    empty_assets = tmp_path / "assets"
    empty_custom = tmp_path / "custom"
    empty_assets.mkdir()
    empty_custom.mkdir()

    registry = FontRegistry(extra_search_dirs=[])
    manager = FontManagerService(
        registry=registry,
        assets_dir=empty_assets,
        custom_dir=empty_custom,
        fallback_family=DEFAULT_FALLBACK_FAMILY,
    )

    unknown = "TotallyFakeFontFamilyXYZ"
    resolved = manager.resolve_family(unknown)
    assert resolved.fell_back is True
    assert resolved.requested_family == unknown
    assert resolved.resolved_family == DEFAULT_FALLBACK_FAMILY

    canvas = CanvasStateDTO(
        width=640,
        height=640,
        background_color="#FFFFFF",
        layers=[
            TextLayerDTO(
                id=uuid4(),
                name="headline",
                x=40.0,
                y=200.0,
                width=560.0,
                height=200.0,
                z_index=1,
                text="Текст с несуществующим шрифтом",
                font_family=unknown,
                font_size=42,
                font_weight="bold",
                color_hex="#111111",
                alignment="center",
            ),
        ],
    )

    renderer = CanvasServerRenderer(
        font_registry=registry,
        font_manager=manager,
        image_cache=ImageAssetCache(),
    )
    result = await renderer.render(canvas, output_format="png", width=640, height=640)

    assert result.image_bytes.startswith(b"\x89PNG")
    assert result.width == 640
    assert result.height == 640
    with Image.open(io.BytesIO(result.image_bytes)) as image:
        assert image.size == (640, 640)
        # Ensure something other than a blank white canvas was painted.
        extrema = image.convert("L").getextrema()
        assert extrema[0] < extrema[1] or extrema[0] < 250
