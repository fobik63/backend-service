"""Deterministic product compositing with masks, edge blending, and shadows."""

from __future__ import annotations

import asyncio
import io
from statistics import median

from PIL import Image, ImageChops, ImageFilter, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field


class ProductCompositorError(ValueError):
    """Product or background cannot be composited safely."""


class CompositingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    product_scale: float = Field(default=0.72, ge=0.25, le=0.9)
    vertical_anchor: float = Field(default=0.54, ge=0.25, le=0.8)
    shadow_opacity: int = Field(default=90, ge=0, le=180)
    shadow_blur_px: int = Field(default=22, ge=0, le=80)
    shadow_offset_y: int = Field(default=14, ge=-20, le=80)
    edge_blend_px: int = Field(default=5, ge=0, le=20)


class CompositedImage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    image_bytes: bytes
    edge_mask_bytes: bytes
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    mask_coverage: float = Field(gt=0.0, le=1.0)


async def composite_product_on_background(
    *,
    product_image: bytes,
    background_image: bytes,
    options: CompositingOptions | None = None,
) -> CompositedImage:
    """Composite the original product over an AI-generated background."""

    return await asyncio.to_thread(
        _composite_sync,
        bytes(product_image),
        bytes(background_image),
        options or CompositingOptions(),
    )


def _composite_sync(
    product_bytes: bytes,
    background_bytes: bytes,
    options: CompositingOptions,
) -> CompositedImage:
    try:
        with Image.open(io.BytesIO(product_bytes)) as product_source:
            product_source.load()
            product = ImageOps.exif_transpose(product_source).convert("RGBA")
        with Image.open(io.BytesIO(background_bytes)) as background_source:
            background_source.load()
            background = ImageOps.exif_transpose(background_source).convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ProductCompositorError(
            "Product or background image cannot be decoded."
        ) from exc

    mask = _extract_product_mask(product)
    bbox = mask.getbbox()
    if bbox is None:
        raise ProductCompositorError("Could not extract a non-empty product mask.")

    product = product.crop(bbox)
    mask = mask.crop(bbox)
    canvas = _fit_background(background, background.size)

    max_width = max(1, int(canvas.width * options.product_scale))
    max_height = max(1, int(canvas.height * options.product_scale))
    scale = min(max_width / product.width, max_height / product.height)
    size = (
        max(1, round(product.width * scale)),
        max(1, round(product.height * scale)),
    )
    product = product.resize(size, Image.Resampling.LANCZOS)
    mask = mask.resize(size, Image.Resampling.LANCZOS)

    if options.edge_blend_px > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(options.edge_blend_px / 2))
    product.putalpha(mask)

    x = (canvas.width - product.width) // 2
    desired_center_y = int(canvas.height * options.vertical_anchor)
    y = max(
        0, min(canvas.height - product.height, desired_center_y - product.height // 2)
    )

    shadow_alpha = mask.filter(ImageFilter.GaussianBlur(options.shadow_blur_px))
    shadow_alpha = shadow_alpha.point(
        lambda pixel: (pixel * options.shadow_opacity) // 255
    )
    shadow = Image.new("RGBA", product.size, (0, 0, 0, 0))
    shadow.putalpha(shadow_alpha)

    # Contact shadow is wider and flatter close to the virtual ground plane.
    contact_height = max(4, product.height // 8)
    contact_alpha = mask.crop(
        (0, product.height - contact_height, product.width, product.height)
    )
    contact_alpha = contact_alpha.resize(
        (product.width, max(4, contact_height // 3)),
        Image.Resampling.LANCZOS,
    ).filter(ImageFilter.GaussianBlur(max(3, options.shadow_blur_px // 2)))
    contact = Image.new("RGBA", contact_alpha.size, (0, 0, 0, 0))
    contact.putalpha(contact_alpha.point(lambda pixel: min(120, pixel // 2)))

    canvas.alpha_composite(
        shadow,
        (x, min(canvas.height - product.height, y + options.shadow_offset_y)),
    )
    contact_y = min(
        canvas.height - contact.height, y + product.height - contact.height // 2
    )
    canvas.alpha_composite(contact, (x, max(0, contact_y)))
    canvas.alpha_composite(product, (x, y))

    edge_mask = _edge_ring(mask, max(1, options.edge_blend_px))
    full_edge_mask = Image.new("L", canvas.size, 0)
    full_edge_mask.paste(edge_mask, (x, y))

    output = io.BytesIO()
    canvas.convert("RGB").save(output, format="PNG", optimize=True, compress_level=9)
    edge_output = io.BytesIO()
    full_edge_mask.save(edge_output, format="PNG", optimize=True, compress_level=9)
    coverage = sum(value * count for value, count in enumerate(mask.histogram())) / (
        255 * mask.width * mask.height
    )
    return CompositedImage(
        image_bytes=output.getvalue(),
        edge_mask_bytes=edge_output.getvalue(),
        width=canvas.width,
        height=canvas.height,
        mask_coverage=max(0.000001, min(float(coverage), 1.0)),
    )


def _extract_product_mask(product: Image.Image) -> Image.Image:
    alpha = product.getchannel("A")
    first_non_empty_alpha = next(
        (value for value, count in enumerate(alpha.histogram()) if count),
        255,
    )
    if first_non_empty_alpha < 250:
        return alpha.point(lambda pixel: 255 if pixel >= 12 else 0).filter(
            ImageFilter.MaxFilter(5)
        )

    rgb = product.convert("RGB")
    samples = [
        rgb.getpixel((0, 0)),
        rgb.getpixel((rgb.width - 1, 0)),
        rgb.getpixel((0, rgb.height - 1)),
        rgb.getpixel((rgb.width - 1, rgb.height - 1)),
    ]
    background = tuple(int(median(channel)) for channel in zip(*samples, strict=True))
    background_image = Image.new("RGB", rgb.size, background)
    difference = ImageChops.difference(rgb, background_image).convert("L")
    # Dynamic threshold handles both clean studio backgrounds and moderate noise.
    histogram = difference.histogram()
    total = max(1, rgb.width * rgb.height)
    cumulative = 0
    percentile = 18
    for value, count in enumerate(histogram):
        cumulative += count
        if cumulative / total >= 0.70:
            percentile = value
            break
    threshold = max(16, min(64, percentile + 10))
    mask = difference.point(lambda pixel: 255 if pixel >= threshold else 0)
    mask = mask.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.MedianFilter(5))
    bbox = mask.getbbox()
    coverage = sum(value * count for value, count in enumerate(mask.histogram())) / (
        255 * total
    )
    if bbox is None or coverage < 0.01 or coverage > 0.95:
        # Safe fallback: keep the central product area instead of returning an
        # empty/full mask that would create an invalid composite.
        mask = Image.new("L", rgb.size, 0)
        inset_x = max(1, rgb.width // 12)
        inset_y = max(1, rgb.height // 12)
        central = Image.new(
            "L",
            (rgb.width - 2 * inset_x, rgb.height - 2 * inset_y),
            255,
        )
        mask.paste(central, (inset_x, inset_y))
    return mask


def _fit_background(background: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(
        background,
        size,
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    ).convert("RGBA")


def _edge_ring(mask: Image.Image, radius: int) -> Image.Image:
    kernel = max(3, radius * 2 + 1)
    if kernel % 2 == 0:
        kernel += 1
    expanded = mask.filter(ImageFilter.MaxFilter(kernel))
    contracted = mask.filter(ImageFilter.MinFilter(kernel))
    return ImageChops.subtract(expanded, contracted)
