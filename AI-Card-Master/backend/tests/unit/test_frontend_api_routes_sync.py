"""Ensure frontend client.ts paths are registered on the FastAPI app."""

from __future__ import annotations

from app.main import app

# Paths used by web/lib/api/client.ts (baseURL already includes /api/v1).
REQUIRED = {
    ("post", "/api/v1/canvas/render"),
    ("post", "/api/v1/relighting/custom"),
    ("post", "/api/v1/parser/parse"),
    ("post", "/api/v1/parser/fetch"),
    ("post", "/api/parser/fetch"),
    ("post", "/api/v1/templates/prompt-to-json"),
    ("post", "/api/v1/tools/remove-bg"),
    ("post", "/api/ai/generate-description"),
    ("get", "/api/marketplaces/publish/products"),
    ("post", "/api/marketplaces/publish/wb"),
    ("post", "/api/marketplaces/publish/ozon"),
    ("get", "/api/v1/telegram/deep-link"),
    ("post", "/api/v1/telegram/webhook"),
}


def test_frontend_api_client_routes_are_registered() -> None:
    paths = app.openapi()["paths"]
    missing: list[str] = []
    for method, path in sorted(REQUIRED):
        operations = paths.get(path) or {}
        if method not in operations:
            missing.append(f"{method.upper()} {path}")
    assert not missing, f"Missing FastAPI routes for frontend client: {missing}"
