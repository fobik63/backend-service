"""Automatic product background removal (rembg / ONNX)."""

from app.services.bg_removal.dto import BgRemovalJobResultDTO, BgRemovalResultDTO
from app.services.bg_removal.engine import (
    BackgroundRemovalEngine,
    BackgroundRemovalEngineError,
    remove_background,
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
    "remove_background",
]
