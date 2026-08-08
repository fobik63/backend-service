"""Automatic product background removal (rembg / ONNX)."""

from app.services.bg_removal.dto import BgRemovalJobResultDTO, BgRemovalResultDTO
from app.services.bg_removal.engine import (
    BackgroundRemovalEngine,
    BackgroundRemovalEngineError,
    remove_background,
)
from app.services.bg_removal.postprocess import (
    defringe_edge_colors,
    refine_alpha_edges,
    refine_cutout_rgba,
)
from app.services.bg_removal.service import (
    BG_REMOVAL_COST_COINS,
    BackgroundRemovalService,
    BackgroundRemovalServiceError,
    BackgroundRemovalUpstreamError,
    BackgroundRemovalValidationError,
)

__all__ = [
    "BG_REMOVAL_COST_COINS",
    "BackgroundRemovalEngine",
    "BackgroundRemovalEngineError",
    "BackgroundRemovalService",
    "BackgroundRemovalServiceError",
    "BackgroundRemovalUpstreamError",
    "BackgroundRemovalValidationError",
    "BgRemovalJobResultDTO",
    "BgRemovalResultDTO",
    "defringe_edge_colors",
    "refine_alpha_edges",
    "refine_cutout_rgba",
    "remove_background",
]
