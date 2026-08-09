"""Loader for niche style preset formulas (perfume / clothing / electronics)."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

STYLE_PRESETS_PATH = Path(__file__).resolve().parent / "style_presets.json"


class StylePresetsError(Exception):
    """Raised when style presets cannot be loaded or resolved."""


class StyleSlidePreset(BaseModel):
    """Strict schema for one marketplace slide formula."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    style: str = Field(min_length=1, max_length=500)
    prompt_formula: str = Field(min_length=1, max_length=8000)
    overlay_style: str = Field(min_length=1, max_length=64)
    default_overlay_text: str = Field(min_length=1, max_length=300)


class NicheStylePreset(BaseModel):
    """Strict schema for one product niche."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    title: str = Field(min_length=1, max_length=128)
    aliases: list[str] = Field(min_length=1)
    negative_prompt: str = Field(min_length=1, max_length=4000)
    color_palette: list[str] = Field(min_length=1)
    lifestyle_scene: str = Field(min_length=1, max_length=4000)
    slides: dict[str, StyleSlidePreset]


class StylePresetCatalog(BaseModel):
    """Validated source-of-truth JSON catalog."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: int = Field(ge=1)
    description: str = Field(min_length=1, max_length=1000)
    niches: dict[str, NicheStylePreset]


@lru_cache(maxsize=1)
def load_style_presets() -> dict[str, Any]:
    """Load and cache ``style_presets.json``."""

    if not STYLE_PRESETS_PATH.is_file():
        raise StylePresetsError(f"Style presets file not found: {STYLE_PRESETS_PATH}")
    try:
        raw = STYLE_PRESETS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise StylePresetsError(f"Failed to load style presets: {exc}") from exc
    try:
        catalog = StylePresetCatalog.model_validate(data)
    except ValidationError as exc:
        raise StylePresetsError(f"style_presets.json schema is invalid: {exc}") from exc
    return catalog.model_dump(mode="python")


@lru_cache(maxsize=1)
def style_preset_content_version() -> str:
    """Content hash used to invalidate Redis keys after JSON changes."""

    try:
        digest = hashlib.sha256(STYLE_PRESETS_PATH.read_bytes()).hexdigest()
    except OSError as exc:
        raise StylePresetsError(f"Failed to hash style presets: {exc}") from exc
    return digest[:16]


def resolve_niche_key(product_category: str | None) -> str | None:
    """Map a free-form category string to a niche key in style_presets.json."""

    if not product_category:
        return None

    normalized = product_category.strip().lower()
    presets = load_style_presets()
    niches: dict[str, Any] = presets.get("niches") or {}

    if normalized in niches:
        return normalized

    for niche_key, niche_data in niches.items():
        aliases = niche_data.get("aliases") or []
        alias_set = {str(a).strip().lower() for a in aliases}
        if normalized in alias_set or normalized == str(niche_data.get("title", "")).lower():
            return niche_key
    return None


def get_niche_preset(product_category: str | None) -> dict[str, Any] | None:
    """Return niche preset dict or None if category is unknown."""

    niche_key = resolve_niche_key(product_category)
    if niche_key is None:
        return None
    niches = load_style_presets().get("niches") or {}
    preset = niches.get(niche_key)
    return preset if isinstance(preset, dict) else None


async def get_niche_preset_cached(
    product_category: str | None,
) -> dict[str, Any] | None:
    """Resolve through Redis, falling back to the validated local JSON."""

    # Lazy import keeps the source-of-truth loader independent at startup and
    # avoids a config -> infrastructure import cycle.
    from app.infrastructure.style_cache import get_style_cache

    return await get_style_cache().get_niche(product_category)
