"""Ozon Top Seller — commercial marketplace card layout preset.

Layer stack (bottom → top)
--------------------------
1. Soft studio background
2. Product cutout, centered slightly below mid-frame, with dual shadows
   (Contact Shadow + Soft Cast Shadow)
3. Title plate — dark translucent backdrop + Inter ExtraBold headline
4. Feature chips (bottom-left) with icons
5. Accent price badge — bright rounded pill with new + struck-through old price
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Final
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.schemas.templates import (
    CanvasStateDTO,
    ImageLayerDTO,
    TextLayerDTO,
)

OZON_TOP_SELLER_PRESET_ID: Final[str] = "ozon_top_seller"

CANVAS_WIDTH: Final[int] = 1080
CANVAS_HEIGHT: Final[int] = 1440

ASSET_BG: Final[str] = "memory://presets/ozon-top-seller/bg.png"
ASSET_PRODUCT: Final[str] = "memory://presets/ozon-top-seller/product.png"
ASSET_PRICE: Final[str] = "memory://presets/ozon-top-seller/price.png"
ASSET_TITLE_PLATE: Final[str] = "memory://presets/ozon-top-seller/title-plate.png"
ASSET_CHIP_TEMPLATE: Final[str] = "memory://presets/ozon-top-seller/chip-{index}.png"

DEFAULT_TITLE: Final[str] = "Кроссовки Salomon XT-6\nTrail Running"
DEFAULT_PRICE_NEW: Final[str] = "8 990 ₽"
DEFAULT_PRICE_OLD: Final[str] = "14 990 ₽"
DEFAULT_FEATURES: Final[tuple[tuple[str, str], ...]] = (
    ("check", "Оригинал"),
    ("season", "Сезон 2026"),
    ("breath", "Дышащий материал"),
)

# Product sits a touch below geometric center so chips / price read clearly.
PRODUCT_CENTER_Y: Final[float] = 740.0
PRODUCT_MAX_W: Final[float] = 860.0
PRODUCT_MAX_H: Final[float] = 680.0


@dataclass(frozen=True, slots=True)
class OzonTopSellerConfig:
    """Content knobs for the Ozon Top Seller commercial layout."""

    title: str = DEFAULT_TITLE
    price_new: str = DEFAULT_PRICE_NEW
    price_old: str = DEFAULT_PRICE_OLD
    features: tuple[tuple[str, str], ...] = DEFAULT_FEATURES
    background_color: str = "#F3F5F8"
    canvas_width: int = CANVAS_WIDTH
    canvas_height: int = CANVAS_HEIGHT


def build_ozon_top_seller_canvas(
    *,
    product_url: str = ASSET_PRODUCT,
    background_url: str = ASSET_BG,
    price_badge_url: str = ASSET_PRICE,
    title_plate_url: str = ASSET_TITLE_PLATE,
    chip_urls: tuple[str, ...] | None = None,
    product_box: tuple[float, float, float, float] | None = None,
    config: OzonTopSellerConfig | None = None,
) -> CanvasStateDTO:
    """Assemble the commercial layer stack as a ``CanvasStateDTO`` document."""

    cfg = config or OzonTopSellerConfig()
    features = cfg.features[:3]
    if chip_urls is None:
        chip_urls = tuple(
            ASSET_CHIP_TEMPLATE.format(index=index) for index in range(len(features))
        )
    if product_box is None:
        px, py, pw, ph = _default_product_box(cfg.canvas_width, cfg.canvas_height)
    else:
        px, py, pw, ph = product_box

    title_pad_x = 56.0
    title_backdrop_x = 48.0
    title_backdrop_y = 56.0
    title_backdrop_w = float(cfg.canvas_width) - title_backdrop_x * 2.0
    title_backdrop_h = 210.0

    layers: list[ImageLayerDTO | TextLayerDTO] = [
        ImageLayerDTO(
            id=uuid4(),
            name="product-cutout",
            x=px,
            y=py,
            width=pw,
            height=ph,
            z_index=2,
            url=product_url,
            scale_x=1.0,
            scale_y=1.0,
        ),
        ImageLayerDTO(
            id=uuid4(),
            name="title-backdrop",
            x=title_backdrop_x,
            y=title_backdrop_y,
            width=title_backdrop_w,
            height=title_backdrop_h,
            z_index=10,
            url=title_plate_url,
        ),
        TextLayerDTO(
            id=uuid4(),
            name="title-inter-extrabold",
            x=title_backdrop_x + title_pad_x,
            y=title_backdrop_y + 36.0,
            width=title_backdrop_w - title_pad_x * 2.0,
            height=title_backdrop_h - 56.0,
            z_index=11,
            text=cfg.title,
            font_family="Inter",
            font_size=54,
            font_weight="extrabold",
            color_hex="#FFFFFF",
            alignment="left",
            line_height=1.18,
            letter_spacing=-0.5,
            shadow_color="#00000066",
            shadow_blur=6.0,
        ),
    ]

    chip_x = 56.0
    chip_y0 = float(cfg.canvas_height) - 320.0
    chip_gap = 18.0
    chip_w = 360.0
    chip_h = 64.0
    for index, chip_url in enumerate(chip_urls[:3]):
        layers.append(
            ImageLayerDTO(
                id=uuid4(),
                name=f"feature-chip-{index}",
                x=chip_x,
                y=chip_y0 + index * (chip_h + chip_gap),
                width=chip_w,
                height=chip_h,
                z_index=20 + index,
                url=chip_url,
            )
        )

    price_w = 320.0
    price_h = 118.0
    layers.append(
        ImageLayerDTO(
            id=uuid4(),
            name="accent-price-badge",
            x=float(cfg.canvas_width) - price_w - 56.0,
            y=float(cfg.canvas_height) - price_h - 72.0,
            width=price_w,
            height=price_h,
            z_index=30,
            url=price_badge_url,
        )
    )

    return CanvasStateDTO(
        width=cfg.canvas_width,
        height=cfg.canvas_height,
        background_color=cfg.background_color,
        background_image_url=background_url,
        layers=layers,
    )


def build_ozon_top_seller_assets(
    product_png: bytes,
    *,
    config: OzonTopSellerConfig | None = None,
    bake_product_shadows: bool = True,
) -> dict[str, bytes]:
    """Raster helpers keyed by the memory:// URLs used in the canvas."""

    cfg = config or OzonTopSellerConfig()
    product = (
        compose_product_with_dual_shadows(product_png)
        if bake_product_shadows
        else product_png
    )
    assets: dict[str, bytes] = {
        ASSET_BG: _studio_background_png(cfg.canvas_width, cfg.canvas_height),
        ASSET_PRODUCT: product,
        ASSET_PRICE: render_price_badge_png(
            price_new=cfg.price_new,
            price_old=cfg.price_old,
        ),
        ASSET_TITLE_PLATE: render_title_plate_png(
            width=cfg.canvas_width - 96,
            height=210,
        ),
    }
    for index, (icon_key, label) in enumerate(cfg.features[:3]):
        assets[ASSET_CHIP_TEMPLATE.format(index=index)] = render_feature_chip_png(
            label=label,
            icon_key=icon_key,
        )
    return assets


def fit_product_box(
    image_bytes: bytes,
    *,
    canvas_w: int = CANVAS_WIDTH,
    canvas_h: int = CANVAS_HEIGHT,
    max_w: float = PRODUCT_MAX_W,
    max_h: float = PRODUCT_MAX_H,
    center_y: float = PRODUCT_CENTER_Y,
) -> tuple[float, float, float, float]:
    """Return ``(x, y, width, height)`` preserving aspect, slightly below center."""

    with Image.open(io.BytesIO(image_bytes)) as image:
        image.load()
        src_w, src_h = image.size
    if src_w < 1 or src_h < 1:
        return _default_product_box(canvas_w, canvas_h)

    scale = min(max_w / float(src_w), max_h / float(src_h))
    width = float(src_w) * scale
    height = float(src_h) * scale
    x = (float(canvas_w) - width) / 2.0
    y = center_y - height / 2.0
    # Keep clear of title plate (top) and chips / price (bottom).
    y = max(260.0, min(float(canvas_h) - height - 340.0, y))
    return x, y, width, height


def compose_product_with_dual_shadows(
    png_bytes: bytes,
    *,
    cast_offset: tuple[int, int] = (28, 42),
    cast_blur: int = 36,
    cast_opacity: float = 0.38,
    contact_blur: int = 10,
    contact_opacity: float = 0.52,
    contact_scale: tuple[float, float] = (0.78, 0.12),
) -> bytes:
    """Bake Soft Cast + Contact shadows under a transparent product cutout.

    Canvas shape layers add a second grounding pass; this baked plate keeps
    the silhouette-accurate Soft Cast even when ellipse layers are subtle.
    """

    with Image.open(io.BytesIO(png_bytes)) as source:
        source.load()
        product = source.convert("RGBA")

    bbox = product.getbbox()
    if bbox is not None:
        product = product.crop(bbox)

    alpha = product.getchannel("A")
    cast_dx, cast_dy = cast_offset
    pad = max(cast_blur * 2, contact_blur * 2, abs(cast_dx), abs(cast_dy)) + 24
    canvas_w = product.width + pad * 2 + abs(cast_dx)
    canvas_h = product.height + pad * 2 + abs(cast_dy) + int(product.height * 0.08)
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    origin_x, origin_y = pad, pad

    # --- Soft Cast Shadow: offset silhouette, heavy Gaussian blur ----------
    cast_alpha = alpha.point(
        lambda pixel: int(round(pixel * max(0.0, min(1.0, cast_opacity))))
    )
    cast = Image.new("RGBA", product.size, (0, 0, 0, 0))
    cast.putalpha(cast_alpha)
    # Mild perspective squash so the cast reads as floor-bound.
    squashed_h = max(1, int(round(product.height * 0.55)))
    cast = cast.resize((product.width, squashed_h), Image.Resampling.LANCZOS)
    cast = cast.filter(ImageFilter.GaussianBlur(radius=cast_blur))
    cast_x = origin_x + cast_dx
    cast_y = origin_y + product.height - squashed_h + cast_dy
    canvas.alpha_composite(cast, (cast_x, cast_y))

    # --- Contact Shadow: tight ellipse under the sole ----------------------
    contact_w = max(8, int(round(product.width * contact_scale[0])))
    contact_h = max(4, int(round(product.height * contact_scale[1])))
    contact = Image.new("RGBA", (contact_w + contact_blur * 4, contact_h + contact_blur * 4), (0, 0, 0, 0))
    contact_draw = ImageDraw.Draw(contact)
    inset = contact_blur * 2
    strength = int(round(255 * max(0.0, min(1.0, contact_opacity))))
    contact_draw.ellipse(
        (inset, inset, inset + contact_w - 1, inset + contact_h - 1),
        fill=(0, 0, 0, strength),
    )
    contact = contact.filter(ImageFilter.GaussianBlur(radius=contact_blur))
    contact_x = origin_x + (product.width - contact.width) // 2
    contact_y = origin_y + product.height - contact.height // 2 - 4
    canvas.alpha_composite(contact, (contact_x, contact_y))

    canvas.alpha_composite(product, (origin_x, origin_y))

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_title_plate_png(*, width: int = 984, height: int = 210) -> bytes:
    """Dark translucent rounded plate behind the ExtraBold headline."""

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=28,
        fill=(11, 18, 32, 210),
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_feature_chip_png(
    *,
    label: str,
    icon_key: str = "check",
    width: int = 360,
    height: int = 64,
) -> bytes:
    """Rounded feature chip with a small glyph icon + label."""

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = height // 2
    draw.rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=radius,
        fill=(255, 255, 255, 235),
        outline=(15, 23, 42, 28),
        width=2,
    )

    icon_box = 40
    icon_x = 12
    icon_y = (height - icon_box) // 2
    _draw_chip_icon(draw, icon_key, icon_x, icon_y, icon_box)

    font = _load_ui_font(size=22, weight="bold")
    text_x = icon_x + icon_box + 12
    bbox = draw.textbbox((0, 0), label, font=font)
    text_h = bbox[3] - bbox[1]
    text_y = (height - text_h) / 2.0 - bbox[1]
    draw.text((text_x, text_y), label, font=font, fill=(15, 23, 42, 255))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_price_badge_png(
    *,
    price_new: str,
    price_old: str,
    width: int = 320,
    height: int = 118,
) -> bytes:
    """Bright rounded accent badge: new price + struck-through old price."""

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # Ozon-adjacent coral/rose accent — high CTR on marketplace feeds.
    draw.rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=28,
        fill=(225, 29, 72, 255),
        outline=(255, 255, 255, 40),
        width=2,
    )

    new_font = _load_ui_font(size=36, weight="bold")
    old_font = _load_ui_font(size=20, weight="regular")

    new_bbox = draw.textbbox((0, 0), price_new, font=new_font)
    new_w = new_bbox[2] - new_bbox[0]
    new_h = new_bbox[3] - new_bbox[1]
    new_x = (width - new_w) / 2.0 - new_bbox[0]
    new_y = 18.0 - new_bbox[1]
    draw.text((new_x, new_y), price_new, font=new_font, fill=(255, 255, 255, 255))

    old_bbox = draw.textbbox((0, 0), price_old, font=old_font)
    old_w = old_bbox[2] - old_bbox[0]
    old_h = old_bbox[3] - old_bbox[1]
    old_x = (width - old_w) / 2.0 - old_bbox[0]
    old_y = new_y + new_h + 10.0 - old_bbox[1]
    old_fill = (255, 255, 255, 190)
    draw.text((old_x, old_y), price_old, font=old_font, fill=old_fill)

    # Strikethrough through the old price midline.
    strike_y = int(round(old_y + old_bbox[1] + old_h / 2.0))
    pad = 4
    draw.line(
        (int(old_x) - pad, strike_y, int(old_x + old_w) + pad, strike_y),
        fill=(255, 255, 255, 210),
        width=2,
    )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _default_product_box(
    canvas_w: int,
    canvas_h: int,
) -> tuple[float, float, float, float]:
    width = min(PRODUCT_MAX_W, float(canvas_w) * 0.78)
    height = min(PRODUCT_MAX_H, float(canvas_h) * 0.45)
    x = (float(canvas_w) - width) / 2.0
    y = PRODUCT_CENTER_Y - height / 2.0
    return x, y, width, height


def _studio_background_png(width: int, height: int) -> bytes:
    """Cool marketplace studio wash — soft vignette, not flat white."""

    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    top = (243, 245, 248)
    bottom = (226, 232, 240)
    for y in range(height):
        t = y / max(1, height - 1)
        ease = t * t * (3.0 - 2.0 * t)
        rgb = tuple(int(top[i] + (bottom[i] - top[i]) * ease) for i in range(3))
        draw.line([(0, y), (width, y)], fill=(*rgb, 255))

    # Soft radial spotlight behind the product zone.
    vignette = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    vignette_draw = ImageDraw.Draw(vignette)
    cx, cy = width // 2, int(height * 0.48)
    rx, ry = int(width * 0.55), int(height * 0.38)
    for step in range(12, 0, -1):
        alpha = int(10 * (13 - step) / 12)
        scale = 0.55 + 0.45 * (step / 12.0)
        vignette_draw.ellipse(
            (
                int(cx - rx * scale),
                int(cy - ry * scale),
                int(cx + rx * scale),
                int(cy + ry * scale),
            ),
            fill=(255, 255, 255, alpha),
        )
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=28))
    image = Image.alpha_composite(image, vignette)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _draw_chip_icon(
    draw: ImageDraw.ImageDraw,
    icon_key: str,
    x: int,
    y: int,
    size: int,
) -> None:
    """Minimal geometric icons (no external SVG dependency)."""

    pad = 4
    left, top = x + pad, y + pad
    right, bottom = x + size - pad, y + size - pad
    cx = (left + right) / 2.0
    cy = (top + bottom) / 2.0
    accent = (5, 150, 105, 255)  # teal seal
    ink = (15, 23, 42, 255)

    draw.ellipse((left, top, right, bottom), fill=(236, 253, 245, 255), outline=accent, width=2)

    key = icon_key.strip().lower()
    if key in {"check", "original", "оригинал"}:
        # Checkmark.
        draw.line(
            [
                (left + size * 0.22, cy),
                (cx - 1, bottom - size * 0.28),
                (right - size * 0.20, top + size * 0.22),
            ],
            fill=accent,
            width=3,
            joint="curve",
        )
    elif key in {"season", "calendar", "сезон"}:
        # Mini calendar glyph.
        draw.rounded_rectangle(
            (left + 6, top + 8, right - 6, bottom - 6),
            radius=3,
            outline=ink,
            width=2,
        )
        draw.line((left + 6, top + 14, right - 6, top + 14), fill=ink, width=2)
        draw.line((cx - 5, top + 4, cx - 5, top + 10), fill=accent, width=2)
        draw.line((cx + 5, top + 4, cx + 5, top + 10), fill=accent, width=2)
    else:
        # Breathable / airflow — three curved strokes.
        for i, dy in enumerate((-6, 0, 6)):
            start = (left + 8, cy + dy)
            mid = (cx, cy + dy - 3 + i)
            end = (right - 8, cy + dy)
            draw.arc(
                (
                    int(start[0]),
                    int(mid[1] - 4),
                    int(end[0]),
                    int(mid[1] + 8),
                ),
                start=200,
                end=340,
                fill=accent,
                width=2,
            )


def _load_ui_font(*, size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    """Resolve Inter / bundled fallback for chip & price raster helpers."""

    try:
        from app.services.templates.fonts import FontRegistry

        registry = FontRegistry()
        return registry.get_font("Inter", size, weight)
    except Exception:  # noqa: BLE001 — offline raster must still succeed
        return ImageFont.load_default()


__all__ = [
    "ASSET_BG",
    "ASSET_CHIP_TEMPLATE",
    "ASSET_PRICE",
    "ASSET_PRODUCT",
    "ASSET_TITLE_PLATE",
    "CANVAS_HEIGHT",
    "CANVAS_WIDTH",
    "DEFAULT_FEATURES",
    "DEFAULT_PRICE_NEW",
    "DEFAULT_PRICE_OLD",
    "DEFAULT_TITLE",
    "OZON_TOP_SELLER_PRESET_ID",
    "OzonTopSellerConfig",
    "build_ozon_top_seller_assets",
    "build_ozon_top_seller_canvas",
    "compose_product_with_dual_shadows",
    "fit_product_box",
    "render_feature_chip_png",
    "render_price_badge_png",
    "render_title_plate_png",
]
