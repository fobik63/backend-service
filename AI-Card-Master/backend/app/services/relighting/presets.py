"""Virtual lighting presets for 2D product relighting."""

from __future__ import annotations

from typing import Final

from app.services.relighting.dto import (
    LightingPresetDTO,
    LightRole,
    RelightingPresetName,
    RelightLightDTO,
)


def _light(
    role: LightRole,
    direction: tuple[float, float, float],
    *,
    color: tuple[float, float, float] = (1.0, 1.0, 1.0),
    intensity: float = 1.0,
    softness: float = 0.5,
) -> RelightLightDTO:
    return RelightLightDTO(
        role=role,
        direction=direction,
        color_rgb=color,
        intensity=intensity,
        softness=softness,
    )


# Warm side key ~3500K, soft long shadows.
_GOLDEN_HOUR = LightingPresetDTO(
    name=RelightingPresetName.GOLDEN_HOUR,
    description="Warm lateral golden-hour light (3500K) with soft elongated shadows.",
    color_temperature_k=3500,
    ambient_rgb=(0.22, 0.14, 0.08),
    ambient_intensity=0.28,
    background_rgb=(255, 236, 214),
    shadow_blur_px=28,
    shadow_angle_deg=48.0,
    shadow_opacity=0.52,
    cast_length=0.55,
    lights=(
        _light(
            LightRole.KEY,
            (0.72, 0.35, 0.55),
            color=(1.0, 0.72, 0.38),
            intensity=1.55,
            softness=0.78,
        ),
        _light(
            LightRole.FILL,
            (-0.35, 0.15, 0.70),
            color=(1.0, 0.85, 0.70),
            intensity=0.35,
            softness=0.90,
        ),
        _light(
            LightRole.RIM,
            (-0.45, 0.55, -0.40),
            color=(1.0, 0.78, 0.45),
            intensity=0.55,
            softness=0.60,
        ),
    ),
)

# Hot pink left + neon blue right.
_CYBERPUNK_NEON = LightingPresetDTO(
    name=RelightingPresetName.CYBERPUNK_NEON,
    description="Two-point neon contrast: hot pink left + neon blue right.",
    color_temperature_k=7500,
    ambient_rgb=(0.06, 0.02, 0.10),
    ambient_intensity=0.14,
    background_rgb=(12, 8, 24),
    shadow_blur_px=14,
    shadow_angle_deg=22.0,
    shadow_opacity=0.60,
    cast_length=0.40,
    lights=(
        _light(
            LightRole.KEY,
            (-0.85, 0.20, 0.45),
            color=(1.0, 0.18, 0.62),
            intensity=1.70,
            softness=0.42,
        ),
        _light(
            LightRole.ACCENT,
            (0.85, 0.25, 0.40),
            color=(0.15, 0.72, 1.0),
            intensity=1.65,
            softness=0.42,
        ),
        _light(
            LightRole.RIM,
            (0.0, 0.70, -0.55),
            color=(0.55, 0.20, 1.0),
            intensity=0.75,
            softness=0.50,
        ),
    ),
)

# Single top spotlight, dark backdrop, hard softbox.
_DRAMATIC_STUDIO = LightingPresetDTO(
    name=RelightingPresetName.DRAMATIC_STUDIO,
    description="Single overhead spotlight with dark backdrop and hard softbox falloff.",
    color_temperature_k=5600,
    ambient_rgb=(0.03, 0.03, 0.04),
    ambient_intensity=0.06,
    background_rgb=(18, 18, 20),
    shadow_blur_px=10,
    shadow_angle_deg=8.0,
    shadow_opacity=0.72,
    cast_length=0.22,
    lights=(
        _light(
            LightRole.SPOT,
            (0.05, 0.95, 0.25),
            color=(1.0, 0.98, 0.94),
            intensity=2.20,
            softness=0.18,
        ),
        _light(
            LightRole.FILL,
            (-0.20, 0.10, 0.80),
            color=(0.55, 0.60, 0.75),
            intensity=0.12,
            softness=0.55,
        ),
    ),
)

# Classic shadowless marketplace catalog light.
_SOFT_COMMERCIAL = LightingPresetDTO(
    name=RelightingPresetName.SOFT_COMMERCIAL,
    description="Classic shadow-free commercial studio light for marketplaces.",
    color_temperature_k=5500,
    ambient_rgb=(0.18, 0.18, 0.20),
    ambient_intensity=0.42,
    background_rgb=(248, 248, 250),
    shadow_blur_px=22,
    shadow_angle_deg=12.0,
    shadow_opacity=0.18,
    cast_length=0.12,
    lights=(
        _light(
            LightRole.KEY,
            (0.35, 0.55, 0.75),
            color=(1.0, 0.99, 0.97),
            intensity=1.15,
            softness=0.88,
        ),
        _light(
            LightRole.FILL,
            (-0.45, 0.40, 0.70),
            color=(0.96, 0.98, 1.0),
            intensity=0.85,
            softness=0.92,
        ),
        _light(
            LightRole.RIM,
            (0.0, 0.65, -0.50),
            color=(1.0, 1.0, 1.0),
            intensity=0.40,
            softness=0.75,
        ),
    ),
)

LIGHTING_PRESETS: Final[dict[RelightingPresetName, LightingPresetDTO]] = {
    RelightingPresetName.GOLDEN_HOUR: _GOLDEN_HOUR,
    RelightingPresetName.CYBERPUNK_NEON: _CYBERPUNK_NEON,
    RelightingPresetName.DRAMATIC_STUDIO: _DRAMATIC_STUDIO,
    RelightingPresetName.SOFT_COMMERCIAL: _SOFT_COMMERCIAL,
}


def get_lighting_preset(name: RelightingPresetName | str) -> LightingPresetDTO:
    """Resolve a lighting preset by enum or string name."""

    if isinstance(name, RelightingPresetName):
        return LIGHTING_PRESETS[name]
    try:
        key = RelightingPresetName(str(name).strip().lower())
    except ValueError as exc:
        allowed = ", ".join(p.value for p in RelightingPresetName)
        raise ValueError(
            f"Unknown lighting preset {name!r}. Allowed: {allowed}."
        ) from exc
    return LIGHTING_PRESETS[key]


__all__ = [
    "LIGHTING_PRESETS",
    "get_lighting_preset",
]
