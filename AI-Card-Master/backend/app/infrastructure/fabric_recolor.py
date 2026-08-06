"""Stable Diffusion adapter for fabric recolor (texture/shadow preserving)."""

from __future__ import annotations

from app.domain.smart_variant import ColorSpec, build_recolor_prompt
from app.services.ai_engine import get_ai_engine


class StableDiffusionFabricRecolor:
    """Img2img recolor: change fabric color, keep weave, folds, and shadows."""

    async def recolor_fabric(
        self,
        *,
        source_image: bytes,
        color: ColorSpec,
        product_category: str | None,
    ) -> bytes:
        prompt = build_recolor_prompt(color, product_category=product_category)
        return await get_ai_engine().generate_product_image(
            product_image=source_image,
            selected_style=(
                "marketplace product fabric recolor, preserve texture shadows seams"
            ),
            user_text=prompt,
        )
