"""Managed photostudio relighting for product cards."""

from app.services.relighting.dto import (
    DepthNormalMapsDTO,
    LightingPresetDTO,
    RelightingJobResultDTO,
    RelightingPresetName,
    RelightLightDTO,
    RelightProcessResultDTO,
    ShadowParamsDTO,
    StudioLightDTO,
)
from app.services.relighting.engine import RelightingEngineError, RelightingEngineService
from app.services.relighting.presets import LIGHTING_PRESETS, get_lighting_preset
from app.services.relighting.service import (
    RELIGHTING_COST_COINS,
    RelightingService,
    RelightingServiceError,
    RelightingUpstreamError,
    RelightingValidationError,
)
from app.services.relighting.shadows import (
    ShadowGeneratorError,
    build_shadow_params,
    generate_shadow_layer,
)
from app.services.relighting.softbox import (
    build_softbox_shadow_params,
    parse_studio_light_instruction,
    softbox_direction,
    softbox_to_lighting_preset,
)

__all__ = [
    "DepthNormalMapsDTO",
    "LIGHTING_PRESETS",
    "LightingPresetDTO",
    "RELIGHTING_COST_COINS",
    "RelightLightDTO",
    "RelightProcessResultDTO",
    "RelightingEngineError",
    "RelightingEngineService",
    "RelightingJobResultDTO",
    "RelightingPresetName",
    "RelightingService",
    "RelightingServiceError",
    "RelightingUpstreamError",
    "RelightingValidationError",
    "ShadowGeneratorError",
    "ShadowParamsDTO",
    "StudioLightDTO",
    "build_shadow_params",
    "build_softbox_shadow_params",
    "generate_shadow_layer",
    "get_lighting_preset",
    "parse_studio_light_instruction",
    "softbox_direction",
    "softbox_to_lighting_preset",
]
