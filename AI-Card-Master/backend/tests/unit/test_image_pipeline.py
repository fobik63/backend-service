from __future__ import annotations

import hashlib
import io

import pytest
from PIL import Image, ImageDraw

from app.services.image_optimizer import create_generation_thumbnail, optimize_image_lossless
from app.services.product_compositor import (
    CompositingOptions,
    composite_product_on_background,
)


def _png(image: Image.Image, *, compress_level: int = 0) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=compress_level)
    return buffer.getvalue()


def _pixel_digest(payload: bytes) -> str:
    with Image.open(io.BytesIO(payload)) as image:
        rgba = image.convert("RGBA")
        digest = hashlib.sha256()
        digest.update(f"{rgba.width}x{rgba.height}".encode("ascii"))
        digest.update(rgba.tobytes())
        return digest.hexdigest()


@pytest.mark.asyncio
async def test_png_optimization_is_pixel_lossless_and_smaller() -> None:
    source = Image.new("RGB", (256, 256), "white")
    ImageDraw.Draw(source).rectangle((50, 50, 205, 205), fill=(180, 20, 30))
    original = _png(source, compress_level=0)

    optimized = await optimize_image_lossless(original)

    assert optimized.mime_type == "image/png"
    assert optimized.extension == ".png"
    assert optimized.optimized_size < optimized.original_size
    assert optimized.pixel_sha256 == _pixel_digest(original)
    assert _pixel_digest(optimized.image_bytes) == _pixel_digest(original)


@pytest.mark.asyncio
async def test_jpeg_metadata_removal_does_not_reencode_pixels() -> None:
    source = Image.new("RGB", (96, 96), (90, 130, 180))
    exif = Image.Exif()
    exif[0x010E] = "metadata that can be removed losslessly"
    buffer = io.BytesIO()
    source.save(buffer, format="JPEG", quality=92, exif=exif)
    original = buffer.getvalue()

    optimized = await optimize_image_lossless(original)

    assert optimized.mime_type == "image/jpeg"
    assert optimized.optimized_size < optimized.original_size
    assert _pixel_digest(optimized.image_bytes) == _pixel_digest(original)


@pytest.mark.asyncio
async def test_generation_thumbnail_is_capped_at_100kb() -> None:
    source = Image.new("RGB", (1400, 1400), (240, 240, 240))
    draw = ImageDraw.Draw(source)
    for offset in range(0, 1400, 20):
        draw.line((0, offset, 1400, 1400 - offset), fill=(30, 90, 160), width=4)
        draw.line((offset, 0, 1400 - offset, 1400), fill=(180, 40, 70), width=4)

    thumbnail = await create_generation_thumbnail(_png(source, compress_level=0))

    assert thumbnail.mime_type == "image/jpeg"
    assert thumbnail.extension == ".jpg"
    assert thumbnail.size_bytes <= 100 * 1024
    assert len(thumbnail.image_bytes) == thumbnail.size_bytes


@pytest.mark.asyncio
async def test_compositor_preserves_product_and_builds_edge_and_shadow() -> None:
    product = Image.new("RGB", (120, 120), "white")
    ImageDraw.Draw(product).rounded_rectangle(
        (35, 25, 85, 100),
        radius=8,
        fill=(220, 20, 30),
    )
    background = Image.new("RGB", (180, 180), (100, 170, 230))

    with_shadow = await composite_product_on_background(
        product_image=_png(product),
        background_image=_png(background),
    )
    without_ambient_shadow = await composite_product_on_background(
        product_image=_png(product),
        background_image=_png(background),
        options=CompositingOptions(shadow_opacity=0),
    )

    assert with_shadow.width == 180
    assert with_shadow.height == 180
    assert 0 < with_shadow.mask_coverage <= 1
    assert with_shadow.image_bytes != without_ambient_shadow.image_bytes
    with Image.open(io.BytesIO(with_shadow.edge_mask_bytes)) as edge:
        assert edge.getbbox() is not None
        assert edge.getextrema()[1] > 0
    with Image.open(io.BytesIO(with_shadow.image_bytes)) as output:
        assert output.convert("RGB").getpixel((90, 90)) == (220, 20, 30)
        colors = output.convert("RGB").getcolors(maxcolors=1_000_000)
        assert colors is not None
        assert any(red > 170 and green < 80 for _count, (red, green, _blue) in colors)
