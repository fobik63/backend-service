"""Compatibility alias — canvas rendering lives in ``renderer.py``."""

from app.services.templates.renderer import *  # noqa: F403
from app.services.templates.renderer import (  # noqa: F401
    BADGE_FONT_HEIGHT_RATIO,
    CANVAS_SUPERSAMPLE_SCALE,
    DEFAULT_BADGE_FONT_FAMILY,
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
