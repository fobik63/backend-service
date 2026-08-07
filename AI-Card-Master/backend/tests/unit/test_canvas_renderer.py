"""Unit tests for CanvasServerRenderer + FontRegistry."""

from __future__ import annotations

import io
import json
from uuid import uuid4

import pytest
from PIL import Image

from app.schemas.templates import (
    BadgeLayerDTO,
    CanvasStateDTO,
    TextLayerDTO,
)
from app.services.templates import (
    PREVIEW_HEIGHT,
    PREVIEW_WIDTH,
    CanvasServerRenderer,
    FontRegistry,
    ImageAssetCache,
)


def _png_bytes(
    color: tuple[int, int, int, int] = (200, 40, 40, 255),
    size: tuple[int, int] = (200, 200),
) -> bytes:
    image = Image.new("RGBA", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_render_png_1080x1440_with_layers() -> None:
    cache = ImageAssetCache()
    product_url = "memory://product.png"
    cache.put(product_url, _png_bytes())

    payload = {
        "width": 1080,
        "height": 1440,
        "background_color": "#F5F5F5",
        "layers": [
            {
                "layer_type": "image",
                "id": str(uuid4()),
                "name": "product",
                "x": 90.0,
                "y": 120.0,
                "width": 900.0,
                "height": 900.0,
                "z_index": 1,
                "url": product_url,
                "scale_x": 1.0,
                "scale_y": 1.0,
            },
            {
                "layer_type": "text",
                "id": str(uuid4()),
                "name": "title",
                "x": 80.0,
                "y": 1080.0,
                "width": 920.0,
                "height": 160.0,
                "z_index": 3,
                "text": "Премиум кроссовки с амортизацией",
                "font_family": "DejaVuSans",
                "font_size": 48,
                "font_weight": "bold",
                "color_hex": "#111111",
                "alignment": "center",
                "line_height": 1.25,
                "shadow_color": "#00000055",
                "shadow_blur": 4.0,
            },
            {
                "layer_type": "badge",
                "id": str(uuid4()),
                "name": "sale",
                "x": 60.0,
                "y": 60.0,
                "width": 220.0,
                "height": 72.0,
                "z_index": 5,
                "badge_type": "discount",
                "text": "-35%",
                "bg_color": "#E11D48",
                "text_color": "#FFFFFF",
            },
            {
                "layer_type": "shape",
                "id": str(uuid4()),
                "name": "accent",
                "x": 0.0,
                "y": 1380.0,
                "width": 1080.0,
                "height": 60.0,
                "z_index": 0,
                "shape_type": "rect",
                "fill_color": "#0F172A",
            },
        ],
    }
    canvas = CanvasStateDTO.model_validate_json(json.dumps(payload))

    renderer = CanvasServerRenderer(
        font_registry=FontRegistry(),
        image_cache=cache,
    )
    result = await renderer.render(canvas, output_format="png")

    assert result.width == 1080
    assert result.height == 1440
    assert result.mime_type == "image/png"
    assert result.extension == ".png"
    assert result.is_preview is False
    assert result.image_bytes.startswith(b"\x89PNG")

    with Image.open(io.BytesIO(result.image_bytes)) as image:
        assert image.size == (1080, 1440)


@pytest.mark.asyncio
async def test_render_preview_300x400_webp() -> None:
    canvas = CanvasStateDTO(
        width=1080,
        height=1440,
        background_color="#FFFFFF",
        layers=[
            BadgeLayerDTO(
                id=uuid4(),
                name="top",
                x=40.0,
                y=40.0,
                width=280.0,
                height=80.0,
                z_index=1,
                badge_type="top_sales",
                text="Хит продаж",
                bg_color="#2563EB",
                text_color="#FFFFFF",
            ),
            TextLayerDTO(
                id=uuid4(),
                name="body",
                x=40.0,
                y=200.0,
                width=1000.0,
                height=400.0,
                z_index=2,
                text=(
                    "Длинный заголовок который должен перенестись "
                    "на несколько строк автоматически"
                ),
                font_family="Arial",
                font_size=56,
                font_weight="700",
                color_hex="#0A0A0A",
                alignment="left",
                line_height=1.3,
                letter_spacing=0.5,
            ),
        ],
    )

    renderer = CanvasServerRenderer(font_registry=FontRegistry())
    result = await renderer.render_preview(canvas, output_format="webp")

    assert result.width == PREVIEW_WIDTH
    assert result.height == PREVIEW_HEIGHT
    assert result.mime_type == "image/webp"
    assert result.is_preview is True
    assert len(result.image_bytes) > 100

    with Image.open(io.BytesIO(result.image_bytes)) as image:
        assert image.size == (PREVIEW_WIDTH, PREVIEW_HEIGHT)


@pytest.mark.asyncio
async def test_z_index_orders_layers() -> None:
    """Higher z_index must paint above lower ones (pixel sample)."""

    cache = ImageAssetCache()
    red_url = "memory://red.png"
    blue_url = "memory://blue.png"
    cache.put(red_url, _png_bytes((255, 0, 0, 255), size=(100, 100)))
    cache.put(blue_url, _png_bytes((0, 0, 255, 255), size=(100, 100)))

    payload = {
        "width": 200,
        "height": 200,
        "background_color": "#000000",
        "layers": [
            {
                "layer_type": "image",
                "id": str(uuid4()),
                "name": "red-top",
                "x": 50.0,
                "y": 50.0,
                "width": 100.0,
                "height": 100.0,
                "z_index": 10,
                "url": red_url,
                "scale_x": 1.0,
                "scale_y": 1.0,
            },
            {
                "layer_type": "image",
                "id": str(uuid4()),
                "name": "blue-bottom",
                "x": 50.0,
                "y": 50.0,
                "width": 100.0,
                "height": 100.0,
                "z_index": 1,
                "url": blue_url,
                "scale_x": 1.0,
                "scale_y": 1.0,
            },
        ],
    }
    canvas = CanvasStateDTO.model_validate_json(json.dumps(payload))

    renderer = CanvasServerRenderer(image_cache=cache)
    result = await renderer.render(canvas, output_format="png", width=200, height=200)
    with Image.open(io.BytesIO(result.image_bytes)) as image:
        pixel = image.convert("RGBA").getpixel((100, 100))
    assert pixel[0] > 200 and pixel[2] < 50  # red on top


def test_font_registry_caches_instances() -> None:
    registry = FontRegistry()
    font_a = registry.get_font("Arial", 24, "bold")
    font_b = registry.get_font("Arial", 24, "bold")
    assert font_a is font_b
    # Either a FreeType font was resolved (preferred) or default bitmap fallback.
    assert registry.cached_font_count >= 1 or font_a is not None
