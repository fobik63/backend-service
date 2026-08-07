"""Template / design API routers (re-export from versioned endpoints)."""

from app.api.v1.endpoints.templates import designs_router, templates_router

__all__ = ["designs_router", "templates_router"]
