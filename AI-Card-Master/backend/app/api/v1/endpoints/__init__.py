"""Versioned REST endpoint modules under ``/api/v1``."""

from app.api.v1.endpoints.templates import designs_router, templates_router

__all__ = ["designs_router", "templates_router"]
