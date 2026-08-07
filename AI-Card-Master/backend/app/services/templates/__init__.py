"""Server-side template canvas rendering (Pillow)."""

from app.services.templates.fonts import FontRegistry, get_font_registry
from app.services.templates.font_manager import (
    DEFAULT_FALLBACK_FAMILY,
    DEFAULT_SYSTEM_FAMILIES,
    FontManagerService,
    FontResolveResult,
    FontValidationError,
    get_font_manager_service,
)
from app.services.templates.image_cache import (
    ImageAssetCache,
    ImageAssetCacheError,
    get_image_asset_cache,
)
from app.services.templates.renderer import (
    DEFAULT_EXPORT_HEIGHT,
    DEFAULT_EXPORT_WIDTH,
    PREVIEW_HEIGHT,
    PREVIEW_WIDTH,
    CanvasRenderError,
    CanvasRenderValidationError,
    CanvasServerRenderer,
    OutputFormat,
    RenderedCanvas,
    get_canvas_server_renderer,
)

__all__ = [
    "DEFAULT_EXPORT_HEIGHT",
    "DEFAULT_EXPORT_WIDTH",
    "DEFAULT_FALLBACK_FAMILY",
    "DEFAULT_SYSTEM_FAMILIES",
    "PREVIEW_HEIGHT",
    "PREVIEW_WIDTH",
    "CanvasRenderError",
    "CanvasRenderValidationError",
    "CanvasServerRenderer",
    "FontManagerService",
    "FontRegistry",
    "FontResolveResult",
    "FontValidationError",
    "ImageAssetCache",
    "ImageAssetCacheError",
    "OutputFormat",
    "RenderedCanvas",
    "get_canvas_server_renderer",
    "get_font_manager_service",
    "get_font_registry",
    "get_image_asset_cache",
]
