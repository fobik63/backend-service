"""Parametric softbox helpers: StudioLightDTO ↔ direction / shadows / prompts."""

from __future__ import annotations

import math
import re
from typing import Final

from app.services.relighting.dto import (
    LightingPresetDTO,
    LightRole,
    RelightLightDTO,
    RelightingPresetName,
    ShadowParamsDTO,
    StudioLightDTO,
)

# Neutral catalog backdrop used for custom softbox jobs.
_CUSTOM_BACKGROUND_RGB: Final[tuple[int, int, int]] = (248, 248, 250)


def softbox_direction(light: StudioLightDTO) -> tuple[float, float, float]:
    """Map angle/elevation to image-local light direction (X right, Y up, Z camera)."""

    azimuth = math.radians(float(light.light_angle) % 360.0)
    elevation = math.radians(float(light.light_elevation))
    # Azimuth 0° = +X (right), 90° = +Z (front), 180° = −X (left).
    # Elevation 90° = +Y (overhead).
    dx = math.cos(elevation) * math.cos(azimuth)
    dy = math.sin(elevation)
    dz = math.cos(elevation) * math.sin(azimuth)
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length < 1e-8:
        return (0.0, 1.0, 0.0)
    return (dx / length, dy / length, dz / length)


def softbox_to_lighting_preset(light: StudioLightDTO) -> LightingPresetDTO:
    """Build an ephemeral lighting preset from a parametric softbox."""

    diffusion = max(0.0, min(1.0, float(light.softbox_diffusion)))
    intensity = max(0.0, min(2.0, float(light.intensity)))
    direction = softbox_direction(light)

    # Opposite fill keeps the unlit side readable on marketplace cards.
    fill_dir = (-direction[0] * 0.55, abs(direction[1]) * 0.35 + 0.15, max(0.35, direction[2] * 0.4 + 0.55))
    ambient = 0.12 + 0.22 * diffusion
    key_softness = 0.18 + 0.72 * diffusion

    return LightingPresetDTO(
        name=RelightingPresetName.SOFT_COMMERCIAL,
        description="Parametric softbox (StudioLightDTO).",
        color_temperature_k=int(light.color_temp_k),
        ambient_rgb=(0.14, 0.14, 0.16),
        ambient_intensity=ambient,
        background_rgb=_CUSTOM_BACKGROUND_RGB,
        shadow_blur_px=_softbox_blur_px(diffusion),
        shadow_angle_deg=_shadow_cast_angle_deg(light.light_angle),
        shadow_opacity=_softbox_shadow_opacity(diffusion, intensity),
        cast_length=_softbox_cast_length(light.light_elevation, diffusion),
        lights=(
            RelightLightDTO(
                role=LightRole.KEY,
                direction=direction,
                color_rgb=(1.0, 1.0, 1.0),
                intensity=0.55 + intensity * 0.95,
                softness=key_softness,
            ),
            RelightLightDTO(
                role=LightRole.FILL,
                direction=_normalize3(fill_dir),
                color_rgb=(0.96, 0.97, 1.0),
                intensity=0.18 + 0.35 * diffusion,
                softness=min(1.0, key_softness + 0.15),
            ),
        ),
    )


def build_softbox_shadow_params(light: StudioLightDTO) -> ShadowParamsDTO:
    """Soft contact + cast shadow under the product, opposite the softbox."""

    diffusion = max(0.0, min(1.0, float(light.softbox_diffusion)))
    intensity = max(0.0, min(2.0, float(light.intensity)))
    # Horizontal push of the contact blob away from the key (opposite azimuth).
    # light_angle 0° (from right) → shadow offset to the left (negative).
    opposite_azimuth = (float(light.light_angle) + 180.0) % 360.0
    contact_offset = -math.cos(math.radians(float(light.light_angle))) * (
        0.08 + 0.22 * (1.0 - diffusion)
    )
    # Elevation: low sun → longer, harder-looking cast; overhead → short puddle.
    elev_factor = 1.0 - (float(light.light_elevation) - 10.0) / 80.0
    strength_scale = max(0.15, min(1.0, 0.35 + intensity * 0.35))

    return ShadowParamsDTO(
        blur_px=_softbox_blur_px(diffusion),
        angle_deg=opposite_azimuth if opposite_azimuth <= 180.0 else opposite_azimuth - 360.0,
        opacity=max(0.0, min(1.0, _softbox_shadow_opacity(diffusion, intensity))),
        cast_length=_softbox_cast_length(light.light_elevation, diffusion) * (0.55 + 0.45 * elev_factor),
        contact_strength=max(0.2, min(1.0, (0.45 + 0.40 * diffusion) * strength_scale)),
        contact_offset_ratio=max(-1.0, min(1.0, contact_offset)),
    )


def parse_studio_light_instruction(instruction: str) -> StudioLightDTO:
    """Convert a short RU/EN lighting phrase into ``StudioLightDTO``.

    Examples:
      - "мягкий тёплый свет слева сверху"
      - "hard cool light from the right"
      - "яркий холодный свет справа"
    """

    text = (instruction or "").strip().lower()
    if not text:
        raise ValueError("instruction must not be empty.")

    normalized = (
        text.replace("ё", "е")
        .replace(",", " ")
        .replace(".", " ")
        .replace(";", " ")
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()

    angle = _parse_angle(normalized)
    elevation = _parse_elevation(normalized)
    color_temp_k = _parse_color_temp(normalized)
    intensity = _parse_intensity(normalized)
    diffusion = _parse_diffusion(normalized)

    return StudioLightDTO(
        light_angle=angle,
        light_elevation=elevation,
        color_temp_k=color_temp_k,
        intensity=intensity,
        softbox_diffusion=diffusion,
    )


def _softbox_blur_px(diffusion: float) -> int:
    return max(4, min(80, int(round(6 + diffusion * 36))))


def _softbox_shadow_opacity(diffusion: float, intensity: float) -> float:
    hard = 1.0 - diffusion
    return max(0.08, min(0.85, (0.22 + hard * 0.38) * (0.55 + 0.45 * min(intensity, 1.5) / 1.5)))


def _softbox_cast_length(elevation: float, diffusion: float) -> float:
    elev = max(10.0, min(90.0, float(elevation)))
    # Low elevation → longer cast; high diffusion shortens perceived length.
    return max(0.06, min(0.85, (0.55 - (elev - 10.0) / 80.0 * 0.42) * (1.0 - 0.35 * diffusion)))


def _shadow_cast_angle_deg(light_angle: float) -> float:
    """Map softbox azimuth to legacy preset shadow_angle_deg (−90..90)."""

    opposite = (float(light_angle) + 180.0) % 360.0
    # Project onto the range expected by LightingPresetDTO.
    if opposite > 180.0:
        opposite -= 360.0
    return max(-90.0, min(90.0, opposite if abs(opposite) <= 90.0 else math.copysign(90.0, opposite)))


def _normalize3(vec: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = vec
    length = math.sqrt(x * x + y * y + z * z)
    if length < 1e-8:
        return (0.0, 0.0, 1.0)
    return (x / length, y / length, z / length)


def _parse_angle(text: str) -> float:
    # Explicit degrees win when present.
    match = re.search(r"(?:angle|азимут|угол)\s*[:=]?\s*(\d{1,3})", text)
    if match:
        return float(int(match.group(1)) % 360)

    left = bool(re.search(r"\b(left|слева|левы\w*|налево)\b", text))
    right = bool(re.search(r"\b(right|справа|правы\w*|направо)\b", text))
    front = bool(re.search(r"\b(front|frontal|спереди|фронтальн\w*)\b", text))
    back = bool(re.search(r"\b(back|behind|сзади|с тыла)\b", text))

    if left and not right:
        return 180.0 if not front else 135.0
    if right and not left:
        return 0.0 if not front else 45.0
    if front and not back:
        return 90.0
    if back and not front:
        return 270.0
    # "сверху" alone → slight front-right key (classic catalog).
    if re.search(r"\b(top|overhead|сверху|над|потолок)\b", text):
        return 90.0
    return 45.0


def _parse_elevation(text: str) -> float:
    match = re.search(r"(?:elevation|высота|elev)\s*[:=]?\s*(\d{1,2})", text)
    if match:
        return float(max(10, min(90, int(match.group(1)))))

    if re.search(r"\b(overhead|zenith|прямо сверху|над головой|потолок)\b", text):
        return 85.0
    if re.search(r"\b(сверху|top|high|высоко|верхн\w*)\b", text):
        return 65.0
    if re.search(r"\b(снизу|bottom|low|низк\w*|нижн\w*)\b", text):
        return 18.0
    if re.search(r"\b(side|боков\w*|сбоку|lateral)\b", text):
        return 35.0
    return 55.0


def _parse_color_temp(text: str) -> int:
    match = re.search(r"(\d{4})\s*k\b", text)
    if match:
        return max(2700, min(7500, int(match.group(1))))

    if re.search(r"\b(warm|тепл\w*|золотист\w*|sunset|golden)\b", text):
        return 3200
    if re.search(r"\b(cool|холодн\w*|син\w*|blueish|bluish|daylight)\b", text):
        return 6500
    if re.search(r"\b(нейтральн\w*|neutral|white)\b", text):
        return 5500
    return 5500


def _parse_intensity(text: str) -> float:
    match = re.search(r"(?:intensity|яркост\w*|сила)\s*[:=]?\s*(\d+(?:\.\d+)?)", text)
    if match:
        return max(0.0, min(2.0, float(match.group(1))))

    if re.search(r"\b(very bright|очень яркий|мощн\w*)\b", text):
        return 1.7
    if re.search(r"\b(bright|яркий|яркая|strong|сильн\w*)\b", text):
        return 1.35
    if re.search(r"\b(dim|слабый|слабая|тускл\w*|мягко приглуш\w*)\b", text):
        return 0.55
    return 1.0


def _parse_diffusion(text: str) -> float:
    match = re.search(
        r"(?:diffusion|softbox_diffusion|диффуз\w*)\s*[:=]?\s*(\d+(?:\.\d+)?)",
        text,
    )
    if match:
        value = float(match.group(1))
        if value > 1.0:
            value = value / 100.0
        return max(0.0, min(1.0, value))

    if re.search(r"\b(ultra soft|очень мягк\w*|максимально мягк\w*)\b", text):
        return 0.95
    if re.search(r"\b(soft|мягк\w*|diffused|рассеянн\w*)\b", text):
        return 0.85
    if re.search(r"\b(hard|жестк\w*|жёстк\w*|sharp|резк\w*|spot)\b", text):
        return 0.15
    return 0.65


__all__ = [
    "build_softbox_shadow_params",
    "parse_studio_light_instruction",
    "softbox_direction",
    "softbox_to_lighting_preset",
]
