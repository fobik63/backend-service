"""Physical contact + cast shadow synthesis from a product alpha mask."""

from __future__ import annotations

import math

from PIL import Image, ImageFilter

from app.services.relighting.dto import ShadowParamsDTO


class ShadowGeneratorError(ValueError):
    """Raised when shadow layers cannot be built."""


def build_shadow_params(
    *,
    blur_px: int,
    angle_deg: float,
    opacity: float,
    cast_length: float,
    shadow_intensity: float,
) -> ShadowParamsDTO:
    """Scale preset shadow knobs by ``shadow_intensity`` (0..1)."""

    intensity = max(0.0, min(1.0, float(shadow_intensity)))
    return ShadowParamsDTO(
        blur_px=max(0, min(80, int(round(blur_px * (0.35 + 0.65 * intensity))))),
        angle_deg=float(angle_deg),
        opacity=max(0.0, min(1.0, opacity * intensity)),
        cast_length=max(0.0, cast_length * (0.4 + 0.6 * intensity)),
        contact_strength=max(0.0, min(1.0, 0.35 + 0.65 * intensity)),
    )


def generate_shadow_layer(
    mask: Image.Image,
    canvas_size: tuple[int, int],
    product_origin: tuple[int, int],
    params: ShadowParamsDTO,
) -> Image.Image:
    """Compose contact + cast shadows onto a transparent canvas.

    ``mask`` is the product alpha (L), pasted at ``product_origin`` on
    ``canvas_size``. Returns an RGBA shadow plate ready for alpha_composite.
    """

    if mask.mode != "L":
        mask = mask.convert("L")
    width, height = canvas_size
    if width < 1 or height < 1:
        raise ShadowGeneratorError("Canvas size must be positive.")

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if params.opacity <= 0.0 and params.contact_strength <= 0.0:
        return canvas

    ox, oy = product_origin
    cast = _cast_shadow(mask, params)
    contact = _contact_shadow(mask, params)

    if cast is not None:
        canvas.alpha_composite(cast, (ox, oy))
    if contact is not None:
        # Contact sits near the virtual ground (bottom of the mask bbox).
        bbox = mask.getbbox()
        if bbox is not None:
            contact_x = ox + bbox[0]
            contact_y = oy + bbox[3] - contact.height // 2
            canvas.alpha_composite(
                contact,
                (
                    max(0, min(width - contact.width, contact_x)),
                    max(0, min(height - contact.height, contact_y)),
                ),
            )
    return canvas


def _cast_shadow(mask: Image.Image, params: ShadowParamsDTO) -> Image.Image | None:
    if params.opacity <= 0.0:
        return None

    angle = math.radians(params.angle_deg)
    length_px = max(1, int(round(mask.height * params.cast_length)))
    dx = int(round(math.sin(angle) * length_px))
    dy = int(round(abs(math.cos(angle)) * length_px * 0.45))

    # Squash silhouette onto a virtual ground plane, then offset by light angle.
    squashed = mask.resize(
        (mask.width, max(1, int(mask.height * 0.35))),
        Image.Resampling.LANCZOS,
    )
    pad = abs(dx) + abs(dy) + params.blur_px + 4
    sheet = Image.new("L", (mask.width + pad * 2, mask.height + pad * 2), 0)
    paste_x = pad + dx
    paste_y = pad + mask.height - squashed.height + dy
    sheet.paste(squashed, (paste_x, paste_y))

    if params.blur_px > 0:
        sheet = sheet.filter(ImageFilter.GaussianBlur(radius=params.blur_px))

    crop = sheet.crop((pad, pad, pad + mask.width, pad + mask.height))
    alpha = crop.point(lambda p: int(round(p * params.opacity)))
    shadow = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    shadow.putalpha(alpha)
    return shadow


def _contact_shadow(mask: Image.Image, params: ShadowParamsDTO) -> Image.Image | None:
    if params.contact_strength <= 0.0:
        return None

    bbox = mask.getbbox()
    if bbox is None:
        return None

    left, top, right, bottom = bbox
    band_h = max(4, (bottom - top) // 8)
    band = mask.crop((left, max(top, bottom - band_h), right, bottom))
    target_h = max(3, band_h // 3)
    contact = band.resize((band.width, target_h), Image.Resampling.LANCZOS)
    blur = max(2, params.blur_px // 2 if params.blur_px else 4)
    contact = contact.filter(ImageFilter.GaussianBlur(radius=blur))
    strength = min(1.0, params.contact_strength)
    alpha = contact.point(lambda p: min(180, int(p * 0.55 * strength)))
    layer = Image.new("RGBA", contact.size, (0, 0, 0, 0))
    layer.putalpha(alpha)
    return layer
