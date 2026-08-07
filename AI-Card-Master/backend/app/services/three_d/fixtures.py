"""Prepared fixture URLs returned by the mock 3D engine."""

from __future__ import annotations

# Static CDN-style fixtures for local/dev and automated tests.
# Real adapters replace these with provider-hosted artifact URLs.
MOCK_FIXTURE_BASE = "https://fixtures.ai-card-master.local/3d"

MOCK_RESULT_URLS: dict[str, str] = {
    "glb": f"{MOCK_FIXTURE_BASE}/sample_product.glb",
    "usdz": f"{MOCK_FIXTURE_BASE}/sample_product.usdz",
    "obj": f"{MOCK_FIXTURE_BASE}/sample_product.obj",
    "preview": f"{MOCK_FIXTURE_BASE}/sample_product_preview.png",
    "preview_thumbnail": f"{MOCK_FIXTURE_BASE}/sample_product_preview_thumb.webp",
}
