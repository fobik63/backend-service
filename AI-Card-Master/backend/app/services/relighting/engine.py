"""RelightingEngineService — depth/normal maps + virtual light + shadows."""

from __future__ import annotations

import asyncio
import io
import math

import numpy as np
from PIL import Image

from app.services.relighting.depth_normal import (
    DepthNormalEstimationError,
    estimate_depth_and_normals,
    extract_product_mask,
    load_rgba,
)
from app.services.relighting.dto import (
    DepthNormalMapsDTO,
    LightingPresetDTO,
    RelightProcessResultDTO,
    RelightingPresetName,
    ShadowParamsDTO,
)
from app.services.relighting.presets import get_lighting_preset
from app.services.relighting.shadows import (
    ShadowGeneratorError,
    build_shadow_params,
    generate_shadow_layer,
)


class RelightingEngineError(ValueError):
    """Raised when the relighting pipeline fails."""


class RelightingEngineService:
    """Local photostudio relighting for marketplace product cutouts."""

    async def generate_maps(self, image_bytes: bytes) -> DepthNormalMapsDTO:
        """Async wrapper around depth / normal estimation."""

        try:
            return await asyncio.to_thread(estimate_depth_and_normals, bytes(image_bytes))
        except DepthNormalEstimationError as exc:
            raise RelightingEngineError(str(exc)) from exc

    async def process(
        self,
        image_bytes: bytes,
        *,
        preset_name: RelightingPresetName | str,
        shadow_intensity: float = 0.7,
    ) -> RelightProcessResultDTO:
        """Estimate maps, apply lighting preset, synthesize shadows → PNG."""

        try:
            preset = get_lighting_preset(preset_name)
        except ValueError as exc:
            raise RelightingEngineError(str(exc)) from exc

        intensity = max(0.0, min(1.0, float(shadow_intensity)))
        try:
            return await asyncio.to_thread(
                self._process_sync,
                bytes(image_bytes),
                preset,
                intensity,
            )
        except (DepthNormalEstimationError, ShadowGeneratorError) as exc:
            raise RelightingEngineError(str(exc)) from exc

    def _process_sync(
        self,
        image_bytes: bytes,
        preset: LightingPresetDTO,
        shadow_intensity: float,
    ) -> RelightProcessResultDTO:
        maps = estimate_depth_and_normals(image_bytes)
        rgba = load_rgba(image_bytes)
        mask = extract_product_mask(rgba)

        with Image.open(io.BytesIO(maps.normal_png)) as normal_img:
            normal_img.load()
            normals = normal_img.convert("RGB")

        lit = _apply_lighting(rgba, normals, mask, preset)
        shadow_params = build_shadow_params(
            blur_px=preset.shadow_blur_px,
            angle_deg=preset.shadow_angle_deg,
            opacity=preset.shadow_opacity,
            cast_length=preset.cast_length,
            shadow_intensity=shadow_intensity,
        )
        canvas = _compose_on_backdrop(lit, mask, preset, shadow_params)

        out = io.BytesIO()
        canvas.save(out, format="PNG", optimize=True, compress_level=6)
        return RelightProcessResultDTO(
            image_png=out.getvalue(),
            depth_png=maps.depth_png,
            normal_png=maps.normal_png,
            preset_name=preset.name,
            width=canvas.width,
            height=canvas.height,
            shadow_intensity=shadow_intensity,
        )


def _apply_lighting(
    rgba: Image.Image,
    normals: Image.Image,
    mask: Image.Image,
    preset: LightingPresetDTO,
) -> Image.Image:
    """Lambert-style relight using estimated normals + preset lights."""

    albedo = np.asarray(rgba.convert("RGB"), dtype=np.float32) / 255.0
    n_rgb = np.asarray(normals, dtype=np.float32) / 255.0
    nx = n_rgb[..., 0] * 2.0 - 1.0
    ny = n_rgb[..., 1] * 2.0 - 1.0
    nz = n_rgb[..., 2] * 2.0 - 1.0
    n_len = np.maximum(np.sqrt(nx * nx + ny * ny + nz * nz), 1e-6)
    nx /= n_len
    ny /= n_len
    nz /= n_len

    temp_rgb = np.array(_kelvin_to_rgb(preset.color_temperature_k), dtype=np.float32)
    ambient = (
        np.array(preset.ambient_rgb, dtype=np.float32)
        * preset.ambient_intensity
        * temp_rgb
    )

    lit = np.zeros_like(albedo)
    lit += ambient

    for light in preset.lights:
        direction = _normalize3(light.direction)
        # Softness expands the Lambert lobe slightly.
        ndotl = nx * direction[0] + ny * direction[1] + nz * direction[2]
        soft = max(0.05, min(1.0, light.softness))
        # Smoothstep-ish wrap lighting controlled by softness.
        wrapped = (ndotl + soft) / (1.0 + soft)
        wrapped = np.clip(wrapped, 0.0, 1.0)
        color = np.array(light.color_rgb, dtype=np.float32) * temp_rgb
        contribution = wrapped[..., None] * color * light.intensity
        lit += contribution

    # Preserve some original albedo so fabric / logo colors stay recognizable.
    shaded = albedo * np.clip(lit, 0.0, 2.5)
    shaded = np.clip(shaded, 0.0, 1.0)

    alpha = np.asarray(mask, dtype=np.float32) / 255.0
    out_rgb = (shaded * 255.0).astype(np.uint8)
    out_a = (np.clip(alpha, 0.0, 1.0) * 255.0).astype(np.uint8)
    rgba_out = np.dstack((out_rgb, out_a))
    return Image.fromarray(rgba_out, mode="RGBA")


def _compose_on_backdrop(
    lit_product: Image.Image,
    mask: Image.Image,
    preset: LightingPresetDTO,
    shadow_params: ShadowParamsDTO,
) -> Image.Image:
    canvas = Image.new("RGBA", lit_product.size, (*preset.background_rgb, 255))
    shadows = generate_shadow_layer(
        mask,
        canvas.size,
        (0, 0),
        shadow_params,
    )
    canvas.alpha_composite(shadows)
    canvas.alpha_composite(lit_product)
    return canvas.convert("RGB").convert("RGBA")


def _normalize3(vec: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = vec
    length = math.sqrt(x * x + y * y + z * z)
    if length < 1e-8:
        return (0.0, 0.0, 1.0)
    return (x / length, y / length, z / length)


def _kelvin_to_rgb(kelvin: int) -> tuple[float, float, float]:
    """Approximate black-body RGB (Tanner Helland), channels in 0..1."""

    temp = max(1000, min(12000, kelvin)) / 100.0
    if temp <= 66:
        red = 255.0
        green = 99.4708025861 * math.log(temp) - 161.1195681661
        blue = (
            0.0
            if temp <= 19
            else 138.5177312231 * math.log(temp - 10.0) - 305.0447927307
        )
    else:
        red = 329.698727446 * ((temp - 60.0) ** -0.1332047592)
        green = 288.1221695283 * ((temp - 60.0) ** -0.0755148492)
        blue = 255.0

    return (
        max(0.0, min(255.0, red)) / 255.0,
        max(0.0, min(255.0, green)) / 255.0,
        max(0.0, min(255.0, blue)) / 255.0,
    )
