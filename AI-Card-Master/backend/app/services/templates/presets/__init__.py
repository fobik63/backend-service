"""Ready-made commercial canvas layout presets."""

from app.services.templates.presets.ozon_top_seller import (
    OZON_TOP_SELLER_PRESET_ID,
    OzonTopSellerConfig,
    build_ozon_top_seller_assets,
    build_ozon_top_seller_canvas,
    compose_product_with_dual_shadows,
)

__all__ = [
    "OZON_TOP_SELLER_PRESET_ID",
    "OzonTopSellerConfig",
    "build_ozon_top_seller_assets",
    "build_ozon_top_seller_canvas",
    "compose_product_with_dual_shadows",
]
