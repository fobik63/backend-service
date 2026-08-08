"""High-performance server-side canvas renderer (Pillow).

``CanvasServerRenderer`` composites ``CanvasStateDTO`` layers by ``z_index``
into a high-resolution card (default 1080×1440) as PNG or WebP, plus fast
catalog previews at 300×400.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Literal

from PIL import Image, ImageDraw, ImageFilter, ImageFont, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.templates import (
    BadgeLayerDTO,
    CanvasStateDTO,
    ImageLayerDTO,
    ShapeLayerDTO,
    TextLayerDTO,
)
from app.services.templates.fonts import FontRegistry, get_font_registry
from app.services.templates.font_manager import (
    FontManagerService,
    get_font_manager_service,
)
from app.services.templates.image_cache import (
    ImageAssetCache,
    ImageAssetCacheError,
    get_image_asset_cache,
)

logger = logging.getLogger(__name__)

OutputFormat = Literal["png", "webp"]

DEFAULT_EXPORT_WIDTH = 1080
DEFAULT_EXPORT_HEIGHT = 1440
PREVIEW_WIDTH = 300
PREVIEW_HEIGHT = 400
# Internal supersample factor — render at 2× then LANCZOS-downsample for crisp
# rotated text / soft shadows (1080×1440 → 2160×2880 working buffer).
CANVAS_SUPERSAMPLE_SCALE = 2
# Badge type tracks height; slightly under 0.5 leaves room for padding.
BADGE_FONT_HEIGHT_RATIO = 0.48
DEFAULT_BADGE_FONT_FAMILY = "Inter"

try:
    LANCZOS = Image.Resampling.LANCZOS
    BICUBIC = Image.Resampling.BICUBIC
except AttributeError:  # pragma: no cover
    LANCZOS = Image.LANCZOS
    BICUBIC = Image.BICUBIC


class CanvasRenderError(RuntimeError):
    """Base error for canvas rendering failures."""


class CanvasRenderValidationError(CanvasRenderError, ValueError):
    """Invalid canvas document or render parameters."""


class RenderedCanvas(BaseModel):
    """Strict output contract for a rendered canvas bitmap."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    image_bytes: bytes = Field(..., min_length=1)
    mime_type: Literal["image/png", "image/webp"]
    extension: Literal[".png", ".webp"]
    width: int = Field(..., ge=1)
    height: int = Field(..., ge=1)
    format: OutputFormat
    is_preview: bool = False


class CanvasServerRenderer:
    """Layered Pillow compositor for card templates.

    Rendering pipeline
    ------------------
    1. Sort visible layers by ascending ``z_index`` (stable by list order).
    2. Paint background color / optional background image.
    3. Composite Image / Text / Badge / Shape layers with transforms.
    4. Encode PNG or WebP; optionally downscale to catalog preview size.
    """

    def __init__(
        self,
        *,
        font_registry: FontRegistry | None = None,
        font_manager: FontManagerService | None = None,
        image_cache: ImageAssetCache | None = None,
    ) -> None:
        self._fonts = font_registry or get_font_registry()
        self._font_manager = font_manager or get_font_manager_service()
        self._images = image_cache or get_image_asset_cache()
    async def render(
        self,
        canvas: CanvasStateDTO,
        *,
        output_format: OutputFormat = "png",
        width: int | None = None,
        height: int | None = None,
        webp_quality: int = 92,
    ) -> RenderedCanvas:
        """Render a high-resolution export (defaults to 1080×1440)."""

        target_w = width if width is not None else (canvas.width or DEFAULT_EXPORT_WIDTH)
        target_h = height if height is not None else (
            canvas.height or DEFAULT_EXPORT_HEIGHT
        )
        return await self._render_async(
            canvas,
            target_width=target_w,
            target_height=target_h,
            output_format=output_format,
            webp_quality=webp_quality,
            is_preview=False,
        )

    async def render_preview(
        self,
        canvas: CanvasStateDTO,
        *,
        output_format: OutputFormat = "webp",
        width: int = PREVIEW_WIDTH,
        height: int = PREVIEW_HEIGHT,
        webp_quality: int = 82,
    ) -> RenderedCanvas:
        """Render a lightweight catalog preview (default 300×400)."""

        return await self._render_async(
            canvas,
            target_width=width,
            target_height=height,
            output_format=output_format,
            webp_quality=webp_quality,
            is_preview=True,
        )

    async def _render_async(
        self,
        canvas: CanvasStateDTO,
        *,
        target_width: int,
        target_height: int,
        output_format: OutputFormat,
        webp_quality: int,
        is_preview: bool,
    ) -> RenderedCanvas:
        if target_width < 1 or target_height < 1:
            raise CanvasRenderValidationError("Target dimensions must be >= 1.")
        if output_format not in {"png", "webp"}:
            raise CanvasRenderValidationError(
                f"Unsupported output format: {output_format!r}"
            )
        if not 1 <= webp_quality <= 100:
            raise CanvasRenderValidationError("webp_quality must be in 1..100.")

        asset_map = await self._prefetch_assets(canvas)

        return await asyncio.to_thread(
            self._render_sync,
            canvas,
            asset_map,
            target_width,
            target_height,
            output_format,
            webp_quality,
            is_preview,
        )

    async def _prefetch_assets(self, canvas: CanvasStateDTO) -> dict[str, bytes]:
        """Download / resolve every referenced image URL once (cached)."""

        urls: set[str] = set()
        if canvas.background_image_url:
            urls.add(canvas.background_image_url)
        for layer in canvas.layers:
            if isinstance(layer, ImageLayerDTO) and layer.visible:
                urls.add(layer.url)

        asset_map: dict[str, bytes] = {}
        if not urls:
            return asset_map

        async def _one(url: str) -> tuple[str, bytes | None, Exception | None]:
            try:
                return url, await self._images.get(url), None
            except ImageAssetCacheError as exc:
                return url, None, exc
            except Exception as exc:  # noqa: BLE001 - isolate per-asset failures
                return url, None, exc

        results = await asyncio.gather(*(_one(url) for url in urls))
        for url, payload, error in results:
            if payload is not None:
                asset_map[url] = payload
            else:
                logger.warning("Canvas asset load failed for %s: %s", url, error)
        return asset_map

    def _render_sync(
        self,
        canvas: CanvasStateDTO,
        asset_map: dict[str, bytes],
        target_width: int,
        target_height: int,
        output_format: OutputFormat,
        webp_quality: int,
        is_preview: bool,
    ) -> RenderedCanvas:
        src_w = max(1, int(canvas.width))
        src_h = max(1, int(canvas.height))

        # Supersample working buffer, then LANCZOS-downsample to the export size.
        # Previews stay 1× (small catalog thumbs don't need the extra cost).
        ss = 1 if is_preview else CANVAS_SUPERSAMPLE_SCALE
        work_w = max(1, int(target_width * ss))
        work_h = max(1, int(target_height * ss))
        scale_x = work_w / src_w
        scale_y = work_h / src_h

        canvas_img = Image.new(
            "RGBA",
            (work_w, work_h),
            color=_parse_hex_color(canvas.background_color),
        )

        if canvas.background_image_url:
            bg_bytes = asset_map.get(canvas.background_image_url)
            if bg_bytes:
                try:
                    bg = _decode_image(bg_bytes).resize(
                        (work_w, work_h),
                        LANCZOS,
                    )
                    canvas_img = Image.alpha_composite(canvas_img, bg)
                except CanvasRenderError as exc:
                    logger.warning("Background image skipped: %s", exc)

        layers = [
            layer
            for _, layer in sorted(
                (
                    (index, layer)
                    for index, layer in enumerate(canvas.layers)
                    if layer.visible
                ),
                key=lambda item: (item[1].z_index, item[0]),
            )
        ]

        for layer in layers:
            try:
                if isinstance(layer, ImageLayerDTO):
                    fragment = self._render_image_layer(layer, asset_map, scale_x, scale_y)
                elif isinstance(layer, TextLayerDTO):
                    fragment = self._render_text_layer(layer, scale_x, scale_y)
                elif isinstance(layer, BadgeLayerDTO):
                    fragment = self._render_badge_layer(layer, scale_x, scale_y)
                elif isinstance(layer, ShapeLayerDTO):
                    fragment = self._render_shape_layer(layer, scale_x, scale_y)
                else:  # pragma: no cover - defensive
                    continue
            except CanvasRenderError as exc:
                logger.warning("Skipping layer %s (%s): %s", layer.id, layer.name, exc)
                continue
            except FileNotFoundError as exc:
                logger.warning(
                    "Skipping layer %s (%s): missing TrueType font: %s",
                    layer.id,
                    layer.name,
                    exc,
                )
                continue

            if fragment is None:
                continue
            _paste_layer(
                canvas_img,
                fragment,
                x=layer.x * scale_x,
                y=layer.y * scale_y,
                width=layer.width * scale_x,
                height=layer.height * scale_y,
                rotation=layer.rotation,
                opacity=layer.opacity,
            )

        if ss > 1 and (work_w, work_h) != (target_width, target_height):
            canvas_img = canvas_img.resize((target_width, target_height), LANCZOS)

        encoded = _encode_image(
            canvas_img,
            output_format=output_format,
            webp_quality=webp_quality,
        )
        mime = "image/png" if output_format == "png" else "image/webp"
        ext = ".png" if output_format == "png" else ".webp"
        return RenderedCanvas(
            image_bytes=encoded,
            mime_type=mime,
            extension=ext,
            width=target_width,
            height=target_height,
            format=output_format,
            is_preview=is_preview,
        )

    # ------------------------------------------------------------------
    # Layer renderers
    # ------------------------------------------------------------------

    def _render_image_layer(
        self,
        layer: ImageLayerDTO,
        asset_map: dict[str, bytes],
        scale_x: float,
        scale_y: float,
    ) -> Image.Image | None:
        payload = asset_map.get(layer.url)
        if payload is None:
            raise CanvasRenderError(f"Image asset unavailable: {layer.url}")

        image = _decode_image(payload)

        if (
            layer.crop_w is not None
            and layer.crop_h is not None
            and layer.crop_w > 0
            and layer.crop_h > 0
        ):
            left = int(max(0.0, layer.crop_x or 0.0))
            top = int(max(0.0, layer.crop_y or 0.0))
            right = int(min(image.width, left + layer.crop_w))
            bottom = int(min(image.height, top + layer.crop_h))
            if right > left and bottom > top:
                image = image.crop((left, top, right, bottom))

        box_w = max(1, int(round(layer.width * scale_x * layer.scale_x)))
        box_h = max(1, int(round(layer.height * scale_y * layer.scale_y)))
        return image.resize((box_w, box_h), LANCZOS)

    def _render_text_layer(
        self,
        layer: TextLayerDTO,
        scale_x: float,
        scale_y: float,
    ) -> Image.Image:
        box_w = max(1, int(round(layer.width * scale_x)))
        box_h = max(1, int(round(layer.height * scale_y)))
        font_size = max(1, int(round(layer.font_size * ((scale_x + scale_y) / 2.0))))
        resolved = self._font_manager.resolve_family(layer.font_family)
        font = self._fonts.get_font(
            resolved.resolved_family,
            font_size,
            layer.font_weight,
        )

        surface = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(surface)

        avg_scale = (scale_x + scale_y) / 2.0
        letter_spacing = layer.letter_spacing * avg_scale
        line_spacing_extra = max(0, int(round(font_size * (layer.line_height - 1.0))))

        wrapped_lines = _wrap_text(
            draw,
            layer.text,
            font=font,
            max_width=box_w,
            letter_spacing=letter_spacing,
        )
        fill = _parse_hex_color(layer.color_hex)
        shadow_color = (
            _parse_hex_color(layer.shadow_color) if layer.shadow_color else None
        )
        shadow_blur = max(0.0, layer.shadow_blur * avg_scale)

        if shadow_color:
            shadow_layer = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow_layer)
            _draw_wrapped_text(
                shadow_draw,
                wrapped_lines,
                font=font,
                fill=shadow_color,
                box_width=box_w,
                alignment=layer.alignment,
                line_spacing=line_spacing_extra,
                letter_spacing=letter_spacing,
                offset_x=max(1, int(round(2 * avg_scale))),
                offset_y=max(1, int(round(2 * avg_scale))),
            )
            if shadow_blur > 0:
                radius = max(1, int(round(shadow_blur)))
                shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius))
            surface = Image.alpha_composite(surface, shadow_layer)
            draw = ImageDraw.Draw(surface)

        _draw_wrapped_text(
            draw,
            wrapped_lines,
            font=font,
            fill=fill,
            box_width=box_w,
            alignment=layer.alignment,
            line_spacing=line_spacing_extra,
            letter_spacing=letter_spacing,
        )
        return surface

    def _render_badge_layer(
        self,
        layer: BadgeLayerDTO,
        scale_x: float,
        scale_y: float,
    ) -> Image.Image:
        box_w = max(1, int(round(layer.width * scale_x)))
        box_h = max(1, int(round(layer.height * scale_y)))
        surface = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(surface)

        radius = _badge_corner_radius(layer.badge_type, box_w, box_h)
        bg = _parse_hex_color(layer.bg_color)
        try:
            draw.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=radius, fill=bg)
        except AttributeError:  # pragma: no cover
            draw.rectangle((0, 0, box_w - 1, box_h - 1), fill=bg)

        # Comfortable inner padding so price text never kisses the badge edge.
        padding_x = max(12, int(round(box_w * 0.14)))
        padding_y = max(8, int(round(box_h * 0.18)))
        max_text_w = max(8, box_w - padding_x * 2)
        max_text_h = max(8, box_h - padding_y * 2)

        # Adaptive type: primary size tracks badge height (font_size ≈ h * 0.5).
        font, text = self._fit_badge_text(
            draw,
            text=layer.text,
            max_width=max_text_w,
            max_height=max_text_h,
            badge_height=box_h,
        )
        text_color = _parse_hex_color(layer.text_color)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        # Center on both axes (compensate FreeType glyph bearing via bbox origin).
        text_x = (box_w - text_w) / 2.0 - bbox[0]
        text_y = (box_h - text_h) / 2.0 - bbox[1]
        draw.text((text_x, text_y), text, font=font, fill=text_color)
        return surface

    def _render_shape_layer(
        self,
        layer: ShapeLayerDTO,
        scale_x: float,
        scale_y: float,
    ) -> Image.Image:
        box_w = max(1, int(round(layer.width * scale_x)))
        box_h = max(1, int(round(layer.height * scale_y)))
        surface = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(surface)
        fill = _parse_hex_color(layer.fill_color)
        stroke = (
            _parse_hex_color(layer.stroke_color) if layer.stroke_color else None
        )
        stroke_w = max(0, int(round(layer.stroke_width * ((scale_x + scale_y) / 2.0))))

        if layer.shape_type == "circle":
            draw.ellipse(
                (0, 0, box_w - 1, box_h - 1),
                fill=fill,
                outline=stroke,
                width=stroke_w if stroke else 0,
            )
        else:
            draw.rectangle(
                (0, 0, box_w - 1, box_h - 1),
                fill=fill,
                outline=stroke,
                width=stroke_w if stroke else 0,
            )
        return surface

    def _fit_badge_text(
        self,
        draw: ImageDraw.ImageDraw,
        *,
        text: str,
        max_width: int,
        max_height: int,
        badge_height: int,
    ) -> tuple[ImageFont.FreeTypeFont, str]:
        target = max(10, int(round(badge_height * BADGE_FONT_HEIGHT_RATIO)))
        start = min(target, max_height)
        min_size = max(8, int(round(badge_height * 0.28)))
        resolved = self._font_manager.resolve_family(DEFAULT_BADGE_FONT_FAMILY)
        family = resolved.resolved_family

        for size in range(start, min_size - 1, -1):
            font = self._fonts.get_font(family, size, "bold")
            bbox = draw.textbbox((0, 0), text, font=font)
            if (bbox[2] - bbox[0]) <= max_width and (bbox[3] - bbox[1]) <= max_height:
                return font, text

        font = self._fonts.get_font(family, min_size, "bold")
        # Truncate with ellipsis if still too wide.
        if not text:
            return font, text
        candidate = text
        while candidate:
            bbox = draw.textbbox((0, 0), candidate, font=font)
            if (bbox[2] - bbox[0]) <= max_width:
                return font, candidate
            if len(candidate) <= 1:
                break
            candidate = candidate[:-2] + "…" if len(candidate) > 2 else "…"
        return font, "…"


# ----------------------------------------------------------------------
# Geometry / drawing helpers
# ----------------------------------------------------------------------


def _paste_layer(
    canvas: Image.Image,
    fragment: Image.Image,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    rotation: float,
    opacity: float,
) -> None:
    layer = fragment.convert("RGBA")
    if opacity < 1.0:
        layer = _apply_opacity(layer, opacity)

    # If fragment was scaled differently from the nominal box (image scale_*),
    # center it inside the layer box before rotation.
    box_w = max(1, int(round(width)))
    box_h = max(1, int(round(height)))
    if layer.size != (box_w, box_h):
        holder = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        ox = (box_w - layer.width) // 2
        oy = (box_h - layer.height) // 2
        holder.alpha_composite(layer, dest=(ox, oy))
        layer = holder

    if abs(rotation) > 1e-6:
        # Pillow affine rotate accepts NEAREST/BILINEAR/BICUBIC only; 2×
        # supersample + final LANCZOS downsample removes residual stair-steps.
        layer = layer.rotate(-rotation, resample=BICUBIC, expand=True)

    # Position: top-left of unrotated box → center stays fixed under rotation.
    center_x = x + width / 2.0
    center_y = y + height / 2.0
    paste_x = int(round(center_x - layer.width / 2.0))
    paste_y = int(round(center_y - layer.height / 2.0))
    canvas.alpha_composite(layer, dest=(paste_x, paste_y))


def _apply_opacity(image: Image.Image, opacity: float) -> Image.Image:
    factor = max(0.0, min(1.0, opacity))
    if factor >= 1.0:
        return image
    r, g, b, a = image.split()
    a = a.point(lambda px: int(px * factor))
    out = Image.merge("RGBA", (r, g, b, a))
    return out


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    max_width: int,
    letter_spacing: float,
) -> list[str]:
    if not text:
        return []

    paragraphs = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines: list[str] = []
    for paragraph in paragraphs:
        if paragraph == "":
            lines.append("")
            continue
        words = paragraph.split(" ")
        current = ""
        for word in words:
            pieces = _split_token(draw, word, font, max_width, letter_spacing)
            for piece in pieces:
                trial = piece if not current else f"{current} {piece}"
                if _measure_line(draw, trial, font, letter_spacing) <= max_width or not current:
                    current = trial
                else:
                    lines.append(current)
                    current = piece
        if current or paragraph.endswith(" "):
            lines.append(current)
    return lines


def _split_token(
    draw: ImageDraw.ImageDraw,
    token: str,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    max_width: int,
    letter_spacing: float,
) -> list[str]:
    if not token:
        return [token]
    if _measure_line(draw, token, font, letter_spacing) <= max_width:
        return [token]

    chunks: list[str] = []
    current = ""
    for char in token:
        trial = current + char
        if _measure_line(draw, trial, font, letter_spacing) <= max_width or not current:
            current = trial
        else:
            chunks.append(current)
            current = char
    if current:
        chunks.append(current)
    return chunks


def _measure_line(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    letter_spacing: float,
) -> float:
    if not text:
        return 0.0
    if abs(letter_spacing) < 1e-6:
        bbox = draw.textbbox((0, 0), text, font=font)
        return float(bbox[2] - bbox[0])
    width = 0.0
    for index, char in enumerate(text):
        bbox = draw.textbbox((0, 0), char, font=font)
        width += bbox[2] - bbox[0]
        if index < len(text) - 1:
            width += letter_spacing
    return width


def _draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    *,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    box_width: int,
    alignment: str,
    line_spacing: int,
    letter_spacing: float,
    offset_x: int = 0,
    offset_y: int = 0,
) -> None:
    ascent, descent = _font_metrics(font)
    line_height = ascent + descent + line_spacing
    y = float(offset_y)

    for line in lines:
        line_w = _measure_line(draw, line, font, letter_spacing)
        if alignment == "center":
            x = (box_width - line_w) / 2.0 + offset_x
        elif alignment == "right":
            x = box_width - line_w + offset_x
        else:
            x = float(offset_x)

        if abs(letter_spacing) < 1e-6:
            draw.text((x, y), line, font=font, fill=fill)
        else:
            cursor = x
            for char in line:
                draw.text((cursor, y), char, font=font, fill=fill)
                bbox = draw.textbbox((0, 0), char, font=font)
                cursor += (bbox[2] - bbox[0]) + letter_spacing
        y += line_height


def _font_metrics(
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
) -> tuple[int, int]:
    try:
        ascent, descent = font.getmetrics()  # type: ignore[attr-defined]
        return int(ascent), int(descent)
    except Exception:  # noqa: BLE001
        size = getattr(font, "size", 12) or 12
        return int(size), max(2, int(size * 0.25))


def _badge_corner_radius(badge_type: str, width: int, height: int) -> int:
    base = max(4, min(width, height) // 5)
    if badge_type == "rating":
        return min(width, height) // 2  # pill
    if badge_type == "top_sales":
        return max(6, base)
    return max(8, base)  # discount


def _decode_image(payload: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(payload)) as source:
            source.load()
            return source.convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise CanvasRenderError("Failed to decode image asset.") from exc


def _encode_image(
    image: Image.Image,
    *,
    output_format: OutputFormat,
    webp_quality: int,
) -> bytes:
    buffer = io.BytesIO()
    if output_format == "png":
        image.save(buffer, format="PNG", optimize=True)
    else:
        # WebP supports alpha; quality applies to lossy mode.
        image.save(buffer, format="WEBP", quality=webp_quality, method=4)
    payload = buffer.getvalue()
    if not payload:
        raise CanvasRenderError("Encoder produced an empty image.")
    return payload


def _parse_hex_color(value: str) -> tuple[int, int, int, int]:
    raw = value.strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
        return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16), 255)
    if len(raw) == 6:
        return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16), 255)
    if len(raw) == 8:
        return (
            int(raw[0:2], 16),
            int(raw[2:4], 16),
            int(raw[4:6], 16),
            int(raw[6:8], 16),
        )
    raise CanvasRenderValidationError(f"Invalid hex color: {value!r}")


def get_canvas_server_renderer() -> CanvasServerRenderer:
    """Factory using process-wide FontRegistry + ImageAssetCache singletons."""

    return CanvasServerRenderer(
        font_registry=get_font_registry(),
        font_manager=get_font_manager_service(),
        image_cache=get_image_asset_cache(),
    )
