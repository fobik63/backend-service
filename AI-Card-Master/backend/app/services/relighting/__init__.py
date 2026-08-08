"""Managed photostudio relighting for product cards."""

from app.services.relighting.dto import (
    DepthNormalMapsDTO,
    LightingPresetDTO,
    RelightLightDTO,
    RelightProcessResultDTO,
    RelightingJobResultDTO,
    RelightingPresetName,
    ShadowParamsDTO,
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
    "build_shadow_params",
    "generate_shadow_layer",
    "get_lighting_preset",
]
