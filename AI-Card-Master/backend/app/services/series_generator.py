"""Parallel generator for 5 marketplace product slides.

The module builds a deterministic set of slide tasks and executes all neural
generation calls concurrently from a single source product image.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Final

from app.services.ai_engine import AIEngineError, generate_product_image


PER_SLIDE_TIMEOUT_SECONDS: Final[float] = 120.0


class SeriesGenerationError(Exception):
    """Raised when one or more slide generations fail."""


@dataclass(frozen=True, slots=True)
class SeriesTask:
    """Input instruction for one slide generation."""

    slide_key: str
    selected_style: str
    user_text: str


@dataclass(frozen=True, slots=True)
class SeriesResult:
    """Generated slide payload returned to caller."""

    slide_key: str
    selected_style: str
    prompt_used: str
    image_bytes: bytes


def build_series_tasks(product_category: str | None = None) -> list[SeriesTask]:
    """Build a fixed list of 5 slide tasks for the neural engine.

    Args:
        product_category: Optional product hint (`perfume`, `cosmetics`, etc.)
            used to refine the lifestyle scene prompt.

    Returns:
        List of 5 deterministic slide tasks in marketplace order.
    """

    lifestyle_scene = _resolve_lifestyle_scene(product_category)

    return [
        SeriesTask(
            slide_key="cover",
            selected_style="studio hero cover",
            user_text=(
                "Create a cover slide for an e-commerce card. Keep the product strictly "
                "centered, use perfect studio lighting, and keep clean negative space "
                "at the top for a future headline."
            ),
        ),
        SeriesTask(
            slide_key="macro",
            selected_style="macro texture detail",
            user_text=(
                "Generate a macro slide with crop and zoom on product texture details. "
                "Focus on material quality and micro-contrast while preserving realism."
            ),
        ),
        SeriesTask(
            slide_key="lifestyle",
            selected_style="lifestyle interior",
            user_text=(
                "Place the product in a believable premium interior scene. "
                f"Scene guide: {lifestyle_scene}. Keep composition balanced and natural."
            ),
        ),
        SeriesTask(
            slide_key="technical",
            selected_style="technical neutral background",
            user_text=(
                "Create a technical slide with a neutral clean background and controlled "
                "light. Keep safe empty zones for overlaying product specifications."
            ),
        ),
        SeriesTask(
            slide_key="trust",
            selected_style="premium trust aesthetic",
            user_text=(
                "Create an aesthetic trust slide with elegant composition and clear space "
                "for a badge text: 'Гарантия качества'. Keep visual tone premium."
            ),
        ),
    ]


async def generate_slide_series(
    product_image: bytes,
    product_category: str | None = None,
) -> list[SeriesResult]:
    """Generate all 5 slide images in parallel from one input image.

    The function intentionally runs all generation tasks concurrently to reduce
    end-to-end latency for batch slide production.
    """

    if not isinstance(product_image, (bytes, bytearray)):
        raise SeriesGenerationError("product_image must be bytes.")
    if not product_image:
        raise SeriesGenerationError("product_image cannot be empty.")

    tasks = build_series_tasks(product_category)

    # Asynchronous loop: create all tasks first, then await their completion together.
    async_jobs: list[asyncio.Task[SeriesResult]] = []
    for task in tasks:
        async_jobs.append(asyncio.create_task(_generate_single_slide(product_image, task)))

    raw_results = await asyncio.gather(*async_jobs, return_exceptions=True)

    final_results: list[SeriesResult] = []
    errors: list[str] = []

    # Keep output order exactly equal to task order for predictable frontend mapping.
    for index, result in enumerate(raw_results):
        if isinstance(result, Exception):
            errors.append(f"{tasks[index].slide_key}: {result}")
            continue
        final_results.append(result)

    if errors:
        raise SeriesGenerationError(
            "One or more slide generations failed. " + " | ".join(errors)
        )

    return final_results


async def _generate_single_slide(product_image: bytes, task: SeriesTask) -> SeriesResult:
    """Generate one slide using the shared AI engine wrapper."""

    try:
        image_bytes = await asyncio.wait_for(
            generate_product_image(
                product_image=product_image,
                selected_style=task.selected_style,
                user_text=task.user_text,
            ),
            timeout=PER_SLIDE_TIMEOUT_SECONDS,
        )
        return SeriesResult(
            slide_key=task.slide_key,
            selected_style=task.selected_style,
            prompt_used=task.user_text,
            image_bytes=image_bytes,
        )
    except asyncio.TimeoutError as exc:
        raise SeriesGenerationError(
            f"Generation timeout after {PER_SLIDE_TIMEOUT_SECONDS} seconds."
        ) from exc
    except AIEngineError as exc:
        raise SeriesGenerationError(f"AI engine request failed: {exc}") from exc
    except Exception as exc:
        raise SeriesGenerationError("Unexpected error during slide generation.") from exc


def _resolve_lifestyle_scene(product_category: str | None) -> str:
    """Map product category to contextual lifestyle scene guidance."""

    if not product_category:
        return "minimal interior with table or shelf"

    normalized = product_category.strip().lower()

    perfume_aliases = {"perfume", "fragrance", "parfum", "парфюм", "духи"}
    cosmetics_aliases = {"cosmetics", "cosmetic", "skincare", "makeup", "косметика"}

    if normalized in perfume_aliases:
        return "stylish table or shelf, premium home interior"

    if normalized in cosmetics_aliases:
        return "clean bathroom environment with mirror and soft daylight"

    return "premium interior scene on table or shelf"
