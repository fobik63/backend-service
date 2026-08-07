"""Parallel generator for 5 marketplace product slides.

The module builds a deterministic set of slide tasks and executes all neural
generation calls concurrently from a single source product image.

Extended with automatic text overlay for each of the 5 slides (Pillow),
ZIP packaging of the 5 images, Selectel S3 upload, and presigned download URLs.
"""

from __future__ import annotations

import asyncio
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, Mapping

from app.config.style_presets import get_niche_preset, get_niche_preset_cached
from app.models.enums import SubscriptionStatus
from app.services.ai_engine import (
    AIEngineError,
    generate_product_image_for_tariff,
)
from app.services.infographic_service import (
    InfographicService,
    InfographicServiceError,
    get_overlay_service,
)
from app.services.image_optimizer import (
    ImageOptimizationError,
    detect_image_format,
    optimize_image_lossless,
)
from app.services.s3_storage import (
    S3StorageError,
    SelectelS3Storage,
    get_s3_storage,
)


PER_SLIDE_TIMEOUT_SECONDS: Final[float] = 120.0
# Cap concurrent Midjourney/SD calls to avoid RAM + credit spikes (audit M2).
SERIES_SLIDE_CONCURRENCY: Final[int] = 3


# Default Russian overlay texts for the 5 marketplace slides.
DEFAULT_SLIDE_OVERLAY_TEXTS: Final[dict[str, str]] = {
    "cover": "Хит продаж сезона",
    "macro": "Премиальная текстура",
    "lifestyle": "Идеально в интерьере",
    "technical": "Ключевые характеристики",
    "trust": "Гарантия качества",
}


SLIDE_OVERLAY_STYLES: Final[dict[str, Literal["Minimal", "Bold", "Luxury"]]] = {
    "cover": "Bold",
    "macro": "Minimal",
    "lifestyle": "Luxury",
    "technical": "Minimal",
    "trust": "Bold",
}


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
    overlay_text: str | None = None
    mime_type: str = "image/png"
    extension: str = ".png"


@dataclass(frozen=True, slots=True)
class SeriesArchiveResult:
    """ZIP archive of 5 slides uploaded to Selectel S3 with a temporary URL."""

    object_key: str
    bucket: str
    presigned_url: str
    slide_filenames: tuple[str, ...]
    archive_size_bytes: int
    local_zip_path: str | None = None


def build_series_tasks(product_category: str | None = None) -> list[SeriesTask]:
    """Build a fixed list of 5 slide tasks for the neural engine.

    Args:
        product_category: Optional product hint (`perfume`, `clothing`,
            `electronics`, etc.) used to refine prompts via style_presets.json.

    Returns:
        List of 5 deterministic slide tasks in marketplace order.
    """

    niche = get_niche_preset(product_category)
    if niche is not None:
        return _build_tasks_from_niche_preset(niche)

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


async def build_series_tasks_cached(product_category: str | None = None) -> list[SeriesTask]:
    """Build tasks through the Redis-backed preset adapter with local fallback."""

    niche = await get_niche_preset_cached(product_category)
    if niche is not None:
        return _build_tasks_from_niche_preset(niche)
    return build_series_tasks(product_category)


def _build_tasks_from_niche_preset(niche: Mapping[str, object]) -> list[SeriesTask]:
    """Build the 5 slide tasks from a niche block in style_presets.json."""

    lifestyle_scene = str(niche.get("lifestyle_scene") or "premium interior scene")
    slides_raw = niche.get("slides")
    if not isinstance(slides_raw, dict):
        raise SeriesGenerationError("Niche preset is missing a valid 'slides' object.")

    tasks: list[SeriesTask] = []
    for slide_key in ("cover", "macro", "lifestyle", "technical", "trust"):
        slide = slides_raw.get(slide_key)
        if not isinstance(slide, dict):
            raise SeriesGenerationError(
                f"Niche preset is missing slide definition for '{slide_key}'."
            )
        formula = str(slide.get("prompt_formula") or "").strip()
        if not formula:
            raise SeriesGenerationError(
                f"Niche preset slide '{slide_key}' has an empty prompt_formula."
            )
        prompt = formula.replace("{lifestyle_scene}", lifestyle_scene)
        style = str(slide.get("style") or slide_key)
        tasks.append(
            SeriesTask(
                slide_key=slide_key,
                selected_style=style,
                user_text=prompt,
            )
        )
    return tasks


async def generate_slide_series(
    product_image: bytes,
    product_category: str | None = None,
    *,
    subscription_status: SubscriptionStatus | str = SubscriptionStatus.FREE,
    apply_text_overlays: bool = False,
    overlay_texts: Mapping[str, str] | None = None,
    optimize_images: bool = True,
) -> list[SeriesResult]:
    """Generate all 5 slide images in parallel from one input image.

    The function intentionally runs all generation tasks concurrently to reduce
    end-to-end latency for batch slide production.

    Args:
        product_image: Source product photo bytes.
        product_category: Optional niche hint for lifestyle scene.
        subscription_status: User tariff — Free uses SD, Pro prefers Midjourney.
        apply_text_overlays: When True, overlay default (or custom) text on each slide.
        overlay_texts: Optional per-slide_key text overrides.
    """

    if not isinstance(product_image, (bytes, bytearray)):
        raise SeriesGenerationError("product_image must be bytes.")
    if not product_image:
        raise SeriesGenerationError("product_image cannot be empty.")

    tasks = build_series_tasks(product_category)
    semaphore = asyncio.Semaphore(SERIES_SLIDE_CONCURRENCY)

    async def _limited(task: SeriesTask) -> SeriesResult:
        async with semaphore:
            return await _generate_single_slide(
                product_image,
                task,
                subscription_status=subscription_status,
            )

    # Bounded parallelism: at most SERIES_SLIDE_CONCURRENCY in-flight generations.
    async_jobs: list[asyncio.Task[SeriesResult]] = [
        asyncio.create_task(_limited(task)) for task in tasks
    ]

    raw_results = await asyncio.gather(*async_jobs, return_exceptions=True)

    final_results: list[SeriesResult] = []
    errors: list[str] = []

    # Keep output order exactly equal to task order for predictable frontend mapping.
    for index, result in enumerate(raw_results):
        if isinstance(result, BaseException):
            errors.append(f"{tasks[index].slide_key}: {result}")
            continue
        final_results.append(result)

    if errors:
        raise SeriesGenerationError(
            "One or more slide generations failed. " + " | ".join(errors)
        )

    if apply_text_overlays:
        niche_overlay_defaults = _niche_overlay_texts(product_category)
        merged_overlays = {
            **DEFAULT_SLIDE_OVERLAY_TEXTS,
            **niche_overlay_defaults,
            **(dict(overlay_texts) if overlay_texts else {}),
        }
        final_results = await apply_text_overlays_to_series(
            final_results,
            overlay_texts=merged_overlays,
        )
    if optimize_images:
        final_results = await optimize_series_images(final_results)

    return final_results


async def optimize_series_images(slides: list[SeriesResult]) -> list[SeriesResult]:
    """Losslessly optimise slide bytes and preserve their actual media type."""

    optimized_payloads = await asyncio.gather(
        *(optimize_image_lossless(slide.image_bytes) for slide in slides)
    )
    return [
        SeriesResult(
            slide_key=slide.slide_key,
            selected_style=slide.selected_style,
            prompt_used=slide.prompt_used,
            image_bytes=optimized.image_bytes,
            overlay_text=slide.overlay_text,
            mime_type=optimized.mime_type,
            extension=optimized.extension,
        )
        for slide, optimized in zip(slides, optimized_payloads, strict=True)
    ]


def _niche_overlay_texts(product_category: str | None) -> dict[str, str]:
    """Pull default overlay texts from style_presets.json for a niche."""

    niche = get_niche_preset(product_category)
    if niche is None:
        return {}
    slides = niche.get("slides")
    if not isinstance(slides, dict):
        return {}
    texts: dict[str, str] = {}
    for slide_key, slide in slides.items():
        if isinstance(slide, dict):
            text = slide.get("default_overlay_text")
            if isinstance(text, str) and text.strip():
                texts[str(slide_key)] = text.strip()
    return texts


async def apply_text_overlays_to_series(
    slides: list[SeriesResult],
    overlay_texts: Mapping[str, str] | None = None,
) -> list[SeriesResult]:
    """Apply automatic text overlays to each of the 5 generated slides.

    Uses InfographicService placement + Pillow rendering. Missing custom texts
    fall back to DEFAULT_SLIDE_OVERLAY_TEXTS.
    """

    if not slides:
        raise SeriesGenerationError("Cannot apply overlays to an empty slide list.")

    texts = {**DEFAULT_SLIDE_OVERLAY_TEXTS, **(dict(overlay_texts) if overlay_texts else {})}
    service = get_overlay_service()

    overlay_jobs = [
        asyncio.create_task(_overlay_single_slide(service, slide, texts))
        for slide in slides
    ]
    raw_results = await asyncio.gather(*overlay_jobs, return_exceptions=True)

    final_results: list[SeriesResult] = []
    errors: list[str] = []

    for index, result in enumerate(raw_results):
        if isinstance(result, BaseException):
            errors.append(f"{slides[index].slide_key}: {result}")
            continue
        final_results.append(result)

    if errors:
        raise SeriesGenerationError(
            "One or more text overlays failed. " + " | ".join(errors)
        )

    return final_results


async def _overlay_single_slide(
    service: InfographicService,
    slide: SeriesResult,
    texts: Mapping[str, str],
) -> SeriesResult:
    """Overlay text on one slide and return an updated SeriesResult."""

    overlay_text = texts.get(slide.slide_key) or DEFAULT_SLIDE_OVERLAY_TEXTS.get(
        slide.slide_key,
        "AI-Card-Master",
    )
    style_name = SLIDE_OVERLAY_STYLES.get(slide.slide_key, "Bold")

    try:
        overlayed = await service.overlay_text_on_image(
            product_image=slide.image_bytes,
            text=overlay_text,
            style_name=style_name,
        )
        return SeriesResult(
            slide_key=slide.slide_key,
            selected_style=slide.selected_style,
            prompt_used=slide.prompt_used,
            image_bytes=overlayed,
            overlay_text=overlay_text,
            mime_type="image/png",
            extension=".png",
        )
    except InfographicServiceError as exc:
        raise SeriesGenerationError(
            f"Text overlay failed for slide '{slide.slide_key}': {exc}"
        ) from exc


async def _generate_single_slide(
    product_image: bytes,
    task: SeriesTask,
    *,
    subscription_status: SubscriptionStatus | str = SubscriptionStatus.FREE,
) -> SeriesResult:
    """Generate one slide using the shared AI engine wrapper (tariff-aware)."""

    try:
        image_bytes = await asyncio.wait_for(
            generate_product_image_for_tariff(
                product_image=product_image,
                selected_style=task.selected_style,
                user_text=task.user_text,
                subscription_status=subscription_status,
            ),
            timeout=PER_SLIDE_TIMEOUT_SECONDS,
        )
        mime_type, extension = detect_image_format(image_bytes)
        return SeriesResult(
            slide_key=task.slide_key,
            selected_style=task.selected_style,
            prompt_used=task.user_text,
            image_bytes=image_bytes,
            mime_type=mime_type,
            extension=extension,
        )
    except asyncio.TimeoutError as exc:
        raise SeriesGenerationError(
            f"Generation timeout after {PER_SLIDE_TIMEOUT_SECONDS} seconds."
        ) from exc
    except AIEngineError as exc:
        raise SeriesGenerationError(f"AI engine request failed: {exc}") from exc
    except ImageOptimizationError as exc:
        raise SeriesGenerationError(f"Generated image format is invalid: {exc}") from exc
    except Exception as exc:
        raise SeriesGenerationError("Unexpected error during slide generation.") from exc


def _resolve_lifestyle_scene(product_category: str | None) -> str:
    """Map product category to contextual lifestyle scene guidance."""

    niche = get_niche_preset(product_category)
    if niche is not None:
        scene = niche.get("lifestyle_scene")
        if isinstance(scene, str) and scene.strip():
            return scene.strip()

    if not product_category:
        return "minimal interior with table or shelf"

    normalized = product_category.strip().lower()

    perfume_aliases = {"perfume", "fragrance", "parfum", "парфюм", "духи", "парфюмерия"}
    cosmetics_aliases = {"cosmetics", "cosmetic", "skincare", "makeup", "косметика"}
    clothing_aliases = {"clothing", "apparel", "fashion", "одежда", "худи", "платье"}
    electronics_aliases = {
        "electronics",
        "gadgets",
        "tech",
        "электроника",
        "гаджет",
        "наушники",
    }

    if normalized in perfume_aliases:
        return "stylish table or shelf, premium home interior"

    if normalized in cosmetics_aliases:
        return "clean bathroom environment with mirror and soft daylight"

    if normalized in clothing_aliases:
        return "bright minimal loft apartment or clean urban street"

    if normalized in electronics_aliases:
        return "modern desk setup with soft LED accent light"

    return "premium interior scene on table or shelf"


def build_series_zip_to_path(
    slides: list[SeriesResult],
    zip_path: Path,
) -> tuple[str, ...]:
    """Stream-pack exactly 5 slides into a ZIP on disk (no full archive in RAM)."""

    if len(slides) != 5:
        raise SeriesGenerationError(
            f"Expected exactly 5 slides for ZIP packaging, got {len(slides)}."
        )

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    filenames: list[str] = []

    with zipfile.ZipFile(
        zip_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for index, slide in enumerate(slides, start=1):
            if not slide.image_bytes:
                raise SeriesGenerationError(
                    f"Slide '{slide.slide_key}' has empty image bytes."
                )
            filename = f"{index:02d}_{slide.slide_key}{slide.extension}"
            filenames.append(filename)
            archive.writestr(filename, slide.image_bytes)

    return tuple(filenames)


def build_series_zip_bytes(slides: list[SeriesResult]) -> tuple[bytes, tuple[str, ...]]:
    """Pack exactly 5 slide images into a ZIP archive.

    Prefer ``build_series_zip_to_path`` / ``package_series_archive_to_s3`` for
    production paths so the archive never resides fully in RAM. Kept for
    callers that still need in-memory bytes (tests / small tools).
    """

    with tempfile.TemporaryDirectory(prefix="series_zip_bytes_") as tmp:
        zip_path = Path(tmp) / "card_series.zip"
        filenames = build_series_zip_to_path(slides, zip_path)
        return zip_path.read_bytes(), filenames


async def save_series_images_locally(
    slides: list[SeriesResult],
    *,
    destination_dir: Path,
) -> list[Path]:
    """Persist the 5 slide PNGs to a local directory (optional staging step)."""

    if len(slides) != 5:
        raise SeriesGenerationError(
            f"Expected exactly 5 slides to save, got {len(slides)}."
        )

    destination_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    for index, slide in enumerate(slides, start=1):
        path = destination_dir / f"{index:02d}_{slide.slide_key}{slide.extension}"
        await asyncio.to_thread(path.write_bytes, slide.image_bytes)
        saved.append(path)

    return saved


async def package_series_archive_to_s3(
    slides: list[SeriesResult],
    *,
    user_id: str | None = None,
    storage: SelectelS3Storage | None = None,
    local_staging_dir: Path | None = None,
    keep_local_zip: bool = False,
) -> SeriesArchiveResult:
    """Save 5 images, stream-pack a ZIP on disk, multipart-upload to Selectel S3.

    Steps:
    1) Optionally stage PNG files on disk.
    2) Stream-write ZIP to a temp/staging path (never hold the full ZIP in RAM).
    3) Upload via S3 multipart ``upload_file``.
    4) Return a time-limited Presigned URL for the frontend download.
    """

    if len(slides) != 5:
        raise SeriesGenerationError(
            f"ZIP packaging requires exactly 5 slides, got {len(slides)}."
        )

    if local_staging_dir is not None:
        await save_series_images_locally(slides, destination_dir=local_staging_dir)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    owner = (user_id or "anonymous").replace("/", "_")
    object_key = f"series/{owner}/{stamp}_{uuid.uuid4().hex[:12]}/card_series.zip"

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if keep_local_zip and local_staging_dir is not None:
        zip_path = local_staging_dir / "card_series.zip"
    else:
        temp_dir = tempfile.TemporaryDirectory(prefix="series_zip_")
        zip_path = Path(temp_dir.name) / "card_series.zip"

    try:
        filenames = await asyncio.to_thread(build_series_zip_to_path, slides, zip_path)
        archive_size = await asyncio.to_thread(lambda: zip_path.stat().st_size)

        try:
            s3 = storage or get_s3_storage()
            uploaded = await s3.upload_file(
                object_key=object_key,
                file_path=zip_path,
                content_type="application/zip",
                presign=True,
            )
        except S3StorageError as exc:
            raise SeriesGenerationError(
                f"Failed to upload series ZIP to S3: {exc}"
            ) from exc

        if not uploaded.presigned_url:
            raise SeriesGenerationError(
                "S3 upload succeeded but presigned URL is empty."
            )

        local_zip_path: str | None = None
        if keep_local_zip and local_staging_dir is not None:
            local_zip_path = str(zip_path)

        return SeriesArchiveResult(
            object_key=uploaded.object_key,
            bucket=uploaded.bucket,
            presigned_url=uploaded.presigned_url,
            slide_filenames=filenames,
            archive_size_bytes=archive_size,
            local_zip_path=local_zip_path,
        )
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


async def generate_slide_series_archive(
    product_image: bytes,
    product_category: str | None = None,
    *,
    subscription_status: SubscriptionStatus | str = SubscriptionStatus.FREE,
    apply_text_overlays: bool = False,
    overlay_texts: Mapping[str, str] | None = None,
    user_id: str | None = None,
    local_staging_dir: Path | None = None,
) -> tuple[list[SeriesResult], SeriesArchiveResult]:
    """Generate 5 slides and immediately package them to Selectel S3.

    Convenience orchestration used by higher-level API/workers.
    """

    slides = await generate_slide_series(
        product_image,
        product_category,
        subscription_status=subscription_status,
        apply_text_overlays=apply_text_overlays,
        overlay_texts=overlay_texts,
    )
    archive = await package_series_archive_to_s3(
        slides,
        user_id=user_id,
        local_staging_dir=local_staging_dir,
    )
    return slides, archive
