"""Infographic service: LLM copywriting + smart text placement + Pillow previews.

Responsibilities:
1) accept a short Russian thesis from user,
2) expand thesis into a professional advertising headline via LLM,
3) provide three predefined text styles (Minimal / Bold / Luxury),
4) detect free background area that avoids product overlap,
5) render test text overlays with Pillow.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import random
from dataclasses import dataclass
from typing import Final, Literal

import httpx
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


logger = logging.getLogger(__name__)


LLMProvider = Literal["openai", "anthropic"]


TRANSIENT_HTTP_CODES: Final[set[int]] = {408, 425, 429, 500, 502, 503, 504}


try:
    LANCZOS_RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # pragma: no cover - Pillow backward compatibility
    LANCZOS_RESAMPLE = Image.LANCZOS


class InfographicServiceError(Exception):
    """Base exception for infographic service failures."""


class InfographicValidationError(InfographicServiceError):
    """Raised when user input is invalid."""


class LLMIntegrationError(InfographicServiceError):
    """Raised when LLM request/response cycle fails."""


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Runtime config for OpenAI/Anthropic integration."""

    provider: LLMProvider
    api_key: str
    model: str
    base_url: str
    timeout_seconds: float = 25.0
    max_connections: int = 80
    max_keepalive_connections: int = 40
    max_retries: int = 2
    base_retry_delay_seconds: float = 0.35

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Build config from environment variables.

        Required:
        - LLM_API_KEY

        Optional:
        - LLM_PROVIDER=openai|anthropic
        - LLM_MODEL
        - LLM_BASE_URL
        - LLM_TIMEOUT_SECONDS
        - LLM_MAX_CONNECTIONS
        - LLM_MAX_KEEPALIVE_CONNECTIONS
        - LLM_MAX_RETRIES
        - LLM_BASE_RETRY_DELAY_SECONDS
        """

        provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
        if provider not in {"openai", "anthropic"}:
            raise LLMIntegrationError("LLM_PROVIDER must be either 'openai' or 'anthropic'.")

        api_key = os.getenv("LLM_API_KEY", "").strip()
        if not api_key:
            raise LLMIntegrationError("LLM_API_KEY is required.")

        default_base_url = (
            "https://api.openai.com" if provider == "openai" else "https://api.anthropic.com"
        )
        default_model = "gpt-4.1-mini" if provider == "openai" else "claude-3-7-sonnet-latest"

        timeout_seconds = _env_float("LLM_TIMEOUT_SECONDS", 25.0)
        max_connections = _env_int("LLM_MAX_CONNECTIONS", 80)
        max_keepalive_connections = _env_int("LLM_MAX_KEEPALIVE_CONNECTIONS", 40)
        max_retries = _env_int("LLM_MAX_RETRIES", 2)
        base_retry_delay_seconds = _env_float("LLM_BASE_RETRY_DELAY_SECONDS", 0.35)

        if timeout_seconds <= 0:
            raise LLMIntegrationError("LLM_TIMEOUT_SECONDS must be > 0.")
        if max_connections <= 0 or max_keepalive_connections <= 0:
            raise LLMIntegrationError("LLM connection limits must be > 0.")
        if max_retries < 0:
            raise LLMIntegrationError("LLM_MAX_RETRIES cannot be negative.")
        if base_retry_delay_seconds <= 0:
            raise LLMIntegrationError("LLM_BASE_RETRY_DELAY_SECONDS must be > 0.")

        return cls(
            provider=provider,
            api_key=api_key,
            model=os.getenv("LLM_MODEL", default_model).strip(),
            base_url=os.getenv("LLM_BASE_URL", default_base_url).strip(),
            timeout_seconds=timeout_seconds,
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
            max_retries=max_retries,
            base_retry_delay_seconds=base_retry_delay_seconds,
        )


@dataclass(frozen=True, slots=True)
class TextStylePreset:
    """Style metadata used for text rendering preview."""

    name: Literal["Minimal", "Bold", "Luxury"]
    description: str
    font_candidates: tuple[str, ...]
    text_color_rgba: tuple[int, int, int, int]
    stroke_color_rgba: tuple[int, int, int, int] | None
    stroke_width: int
    panel_color_rgba: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class TextPlacement:
    """Suggested text box on image that minimizes product overlap."""

    x: int
    y: int
    width: int
    height: int
    foreground_overlap_ratio: float


@dataclass(frozen=True, slots=True)
class InfographicVariant:
    """Single style variant with rendered preview."""

    style_name: str
    style_description: str
    headline: str
    placement: TextPlacement
    preview_image_png: bytes


@dataclass(frozen=True, slots=True)
class InfographicPackage:
    """Final generated package for infographic text overlay."""

    source_thesis: str
    generated_headline: str
    variants: list[InfographicVariant]


class InfographicService:
    """Main service class for copy generation and visual text placement."""

    def __init__(self, llm_config: LLMConfig | None = None) -> None:
        self._llm_config = llm_config or LLMConfig.from_env()

        self._client = httpx.AsyncClient(
            base_url=self._llm_config.base_url.rstrip("/"),
            timeout=httpx.Timeout(self._llm_config.timeout_seconds),
            limits=httpx.Limits(
                max_connections=self._llm_config.max_connections,
                max_keepalive_connections=self._llm_config.max_keepalive_connections,
                keepalive_expiry=30.0,
            ),
            http2=True,
        )

    async def aclose(self) -> None:
        """Close underlying HTTP resources."""

        await self._client.aclose()

    async def generate_infographic_package(
        self,
        product_image: bytes,
        thesis_ru: str,
    ) -> InfographicPackage:
        """Generate full infographic package from one image and a short Russian thesis.

        Steps:
        1) ask LLM to expand thesis into professional ad headline,
        2) detect free background area on image,
        3) render 3 style previews in parallel.
        """

        self._validate_input(product_image=product_image, thesis_ru=thesis_ru)

        headline = await self._expand_thesis_to_headline(thesis_ru)
        placement = await asyncio.to_thread(self._detect_free_text_area, product_image)

        style_presets = self._get_style_presets()
        preview_jobs = [
            asyncio.to_thread(
                self._render_preview_with_style,
                product_image,
                headline,
                placement,
                preset,
            )
            for preset in style_presets
        ]

        try:
            preview_images = await asyncio.gather(*preview_jobs)
        except Exception as exc:
            raise InfographicServiceError(
                "Failed to render one or more Pillow text overlay previews."
            ) from exc

        variants: list[InfographicVariant] = []
        for preset, preview_png in zip(style_presets, preview_images, strict=True):
            variants.append(
                InfographicVariant(
                    style_name=preset.name,
                    style_description=preset.description,
                    headline=headline,
                    placement=placement,
                    preview_image_png=preview_png,
                )
            )

        return InfographicPackage(
            source_thesis=thesis_ru.strip(),
            generated_headline=headline,
            variants=variants,
        )

    def _validate_input(self, product_image: bytes, thesis_ru: str) -> None:
        """Validate request payload before external calls."""

        if not isinstance(product_image, (bytes, bytearray)):
            raise InfographicValidationError("product_image must be bytes.")
        if not product_image:
            raise InfographicValidationError("product_image cannot be empty.")
        if not isinstance(thesis_ru, str):
            raise InfographicValidationError("thesis_ru must be a string.")
        if not thesis_ru.strip():
            raise InfographicValidationError("thesis_ru cannot be empty.")
        if len(thesis_ru.strip()) > 400:
            raise InfographicValidationError("thesis_ru is too long; max length is 400 chars.")

    async def _expand_thesis_to_headline(self, thesis_ru: str) -> str:
        """Use selected LLM provider to transform thesis into ad headline."""

        try:
            if self._llm_config.provider == "openai":
                raw_headline = await self._call_openai(thesis_ru)
            else:
                raw_headline = await self._call_anthropic(thesis_ru)
        except Exception as exc:
            if isinstance(exc, LLMIntegrationError):
                raise
            raise LLMIntegrationError("LLM headline generation failed.") from exc

        normalized = _normalize_headline(raw_headline)
        if not normalized:
            raise LLMIntegrationError("LLM returned empty headline.")

        return normalized

    async def _call_openai(self, thesis_ru: str) -> str:
        """Generate headline using OpenAI chat completions API."""

        headers = {
            "Authorization": f"Bearer {self._llm_config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._llm_config.model,
            "temperature": 0.7,
            "max_tokens": 120,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a senior Russian advertising copywriter for e-commerce visuals. "
                        "Expand short theses into one polished headline in Russian."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Transform the Russian thesis into one professional ad headline in Russian. "
                        "Rules: 8-16 words, persuasive and premium tone, factual, no emoji, "
                        "no exclamation marks, no markdown, output headline only.\n"
                        f"Thesis: {thesis_ru.strip()}"
                    ),
                },
            ],
        }

        response = await self._post_with_retry(
            endpoint="/v1/chat/completions",
            headers=headers,
            payload=payload,
        )

        try:
            response_json = response.json()
        except ValueError as exc:
            raise LLMIntegrationError("OpenAI response is not valid JSON.") from exc

        try:
            choices = response_json["choices"]
            first_choice = choices[0]
            message = first_choice["message"]
            content = message.get("content", "")
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMIntegrationError("Unexpected OpenAI response shape.") from exc

        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            ]
            merged = " ".join(segment.strip() for segment in text_parts if segment.strip())
            if merged:
                return merged

        raise LLMIntegrationError("OpenAI did not return headline text.")

    async def _call_anthropic(self, thesis_ru: str) -> str:
        """Generate headline using Anthropic Messages API."""

        headers = {
            "x-api-key": self._llm_config.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self._llm_config.model,
            "max_tokens": 120,
            "temperature": 0.7,
            "system": (
                "You are a senior Russian advertising copywriter for e-commerce visuals. "
                "Expand short theses into one polished headline in Russian."
            ),
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Transform the Russian thesis into one professional ad headline in Russian. "
                        "Rules: 8-16 words, persuasive and premium tone, factual, no emoji, "
                        "no exclamation marks, no markdown, output headline only.\n"
                        f"Thesis: {thesis_ru.strip()}"
                    ),
                }
            ],
        }

        response = await self._post_with_retry(
            endpoint="/v1/messages",
            headers=headers,
            payload=payload,
        )

        try:
            response_json = response.json()
        except ValueError as exc:
            raise LLMIntegrationError("Anthropic response is not valid JSON.") from exc

        try:
            content = response_json["content"]
            first_item = content[0]
            text = first_item["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMIntegrationError("Unexpected Anthropic response shape.") from exc

        if not isinstance(text, str):
            raise LLMIntegrationError("Anthropic did not return text output.")

        return text

    async def _post_with_retry(
        self,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, object],
    ) -> httpx.Response:
        """POST request with retry on transient failures."""

        attempts = self._llm_config.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.post(endpoint, headers=headers, json=payload)

                if response.status_code in TRANSIENT_HTTP_CODES and attempt < attempts:
                    await asyncio.sleep(self._compute_retry_delay(attempt, response))
                    continue

                if response.is_error:
                    raise LLMIntegrationError(
                        f"LLM API error {response.status_code}: {_extract_http_error(response)}"
                    )

                return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                await asyncio.sleep(self._compute_retry_delay(attempt, response=None))

        raise LLMIntegrationError("LLM request failed after retries.") from last_error

    def _compute_retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        """Exponential backoff with jitter and Retry-After support."""

        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    parsed = float(retry_after)
                    if parsed > 0:
                        return min(parsed, 10.0)
                except ValueError:
                    logger.debug("Ignoring non-numeric Retry-After value: %s", retry_after)

        delay = self._llm_config.base_retry_delay_seconds * (2 ** (attempt - 1))
        jitter = random.uniform(0.0, 0.35)
        return min(delay + jitter, 10.0)

    def _get_style_presets(self) -> list[TextStylePreset]:
        """Return three required style variants for infographic text."""

        return [
            TextStylePreset(
                name="Minimal",
                description="Clean sans-serif style with subtle panel and restrained contrast.",
                font_candidates=("DejaVuSans.ttf", "Arial.ttf"),
                text_color_rgba=(26, 26, 26, 255),
                stroke_color_rgba=None,
                stroke_width=0,
                panel_color_rgba=(255, 255, 255, 185),
            ),
            TextStylePreset(
                name="Bold",
                description="High-contrast visual accent with strong typography impact.",
                font_candidates=("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "Arial.ttf"),
                text_color_rgba=(255, 255, 255, 255),
                stroke_color_rgba=(12, 12, 12, 255),
                stroke_width=2,
                panel_color_rgba=(0, 0, 0, 170),
            ),
            TextStylePreset(
                name="Luxury",
                description="Elegant serif mood with warm premium color accents.",
                font_candidates=("DejaVuSerif.ttf", "Times New Roman.ttf", "Arial.ttf"),
                text_color_rgba=(245, 212, 133, 255),
                stroke_color_rgba=(33, 24, 12, 255),
                stroke_width=1,
                panel_color_rgba=(24, 19, 14, 165),
            ),
        ]

    def _detect_free_text_area(self, product_image: bytes) -> TextPlacement:
        """Locate the best free background box for text placement.

        The method estimates foreground mask from color difference against
        dominant border background and then searches for a low-overlap region.
        """

        try:
            with Image.open(io.BytesIO(product_image)) as image:
                source = image.convert("RGB")
        except Exception as exc:
            raise InfographicValidationError("product_image is not a valid image file.") from exc

        analysis = source.copy()
        analysis.thumbnail((512, 512), LANCZOS_RESAMPLE)

        foreground_mask = self._build_foreground_mask(analysis)
        box_x, box_y, box_w, box_h, overlap = self._find_best_free_box(foreground_mask)

        scale_x = source.width / analysis.width
        scale_y = source.height / analysis.height

        x = int(box_x * scale_x)
        y = int(box_y * scale_y)
        width = int(box_w * scale_x)
        height = int(box_h * scale_y)

        # Clamp coordinates to source image bounds for rendering safety.
        x = max(0, min(x, source.width - 1))
        y = max(0, min(y, source.height - 1))
        width = max(40, min(width, source.width - x))
        height = max(30, min(height, source.height - y))

        return TextPlacement(
            x=x,
            y=y,
            width=width,
            height=height,
            foreground_overlap_ratio=round(overlap, 4),
        )

    def _build_foreground_mask(self, image: Image.Image) -> Image.Image:
        """Create binary foreground mask by subtracting dominant border background."""

        bg_r, bg_g, bg_b = _estimate_background_color(image)
        bg_image = Image.new("RGB", image.size, (bg_r, bg_g, bg_b))

        diff = ImageChops.difference(image, bg_image).convert("L")

        border_noise = _estimate_border_noise(diff)
        threshold = max(22, min(64, int(border_noise * 2.1 + 20)))

        mask = diff.point(lambda value: 255 if value > threshold else 0, mode="L")

        # Expand foreground regions slightly to keep text away from product edges.
        mask = mask.filter(ImageFilter.MaxFilter(size=9))
        return mask

    def _find_best_free_box(self, foreground_mask: Image.Image) -> tuple[int, int, int, int, float]:
        """Search candidate boxes and pick one with minimal foreground overlap."""

        width, height = foreground_mask.size
        margin = max(4, min(width, height) // 30)

        # Candidate box presets are tuned for common e-commerce card layouts.
        if width >= height:
            box_presets = [(0.46, 0.27), (0.40, 0.23), (0.34, 0.2)]
        else:
            box_presets = [(0.78, 0.18), (0.72, 0.22), (0.66, 0.26)]

        product_bbox = foreground_mask.getbbox()
        best_score = float("inf")
        best_result: tuple[int, int, int, int, float] | None = None

        for width_ratio, height_ratio in box_presets:
            box_width = max(40, min(int(width * width_ratio), width - (margin * 2)))
            box_height = max(30, min(int(height * height_ratio), height - (margin * 2)))
            if box_width <= 0 or box_height <= 0:
                continue

            step_x = max(6, box_width // 8)
            step_y = max(6, box_height // 8)

            max_x = width - box_width - margin
            max_y = height - box_height - margin
            if max_x < margin or max_y < margin:
                continue

            for top in range(margin, max_y + 1, step_y):
                for left in range(margin, max_x + 1, step_x):
                    overlap_ratio = _mask_overlap_ratio(
                        foreground_mask,
                        left,
                        top,
                        box_width,
                        box_height,
                    )
                    bbox_overlap_ratio = _bbox_overlap_ratio(
                        (left, top, left + box_width, top + box_height),
                        product_bbox,
                    )
                    center_penalty = _center_penalty(
                        image_width=width,
                        image_height=height,
                        box_left=left,
                        box_top=top,
                        box_width=box_width,
                        box_height=box_height,
                    )

                    score = (overlap_ratio * 0.78) + (bbox_overlap_ratio * 0.17) + (center_penalty * 0.05)
                    if score < best_score:
                        best_score = score
                        best_result = (left, top, box_width, box_height, overlap_ratio)

        if best_result is not None:
            return best_result

        # Fallback: upper region with conservative dimensions.
        fallback_width = max(40, int(width * 0.45))
        fallback_height = max(30, int(height * 0.22))
        fallback_left = max(margin, width - fallback_width - margin)
        fallback_top = margin
        fallback_overlap = _mask_overlap_ratio(
            foreground_mask,
            fallback_left,
            fallback_top,
            fallback_width,
            fallback_height,
        )
        return fallback_left, fallback_top, fallback_width, fallback_height, fallback_overlap

    def _render_preview_with_style(
        self,
        product_image: bytes,
        headline: str,
        placement: TextPlacement,
        preset: TextStylePreset,
    ) -> bytes:
        """Render text overlay preview using Pillow."""

        try:
            with Image.open(io.BytesIO(product_image)) as image:
                canvas = image.convert("RGBA")
        except Exception as exc:
            raise InfographicValidationError("Failed to read product image for preview.") from exc

        draw = ImageDraw.Draw(canvas)

        panel_left = placement.x
        panel_top = placement.y
        panel_right = placement.x + placement.width
        panel_bottom = placement.y + placement.height

        radius = max(10, min(placement.width, placement.height) // 10)
        try:
            draw.rounded_rectangle(
                (panel_left, panel_top, panel_right, panel_bottom),
                radius=radius,
                fill=preset.panel_color_rgba,
            )
        except AttributeError:
            draw.rectangle(
                (panel_left, panel_top, panel_right, panel_bottom),
                fill=preset.panel_color_rgba,
            )

        padding = max(10, min(placement.width, placement.height) // 10)
        max_text_width = max(20, placement.width - (padding * 2))
        max_text_height = max(20, placement.height - (padding * 2))

        text, font, spacing = self._fit_text_to_box(
            draw=draw,
            text=headline,
            max_width=max_text_width,
            max_height=max_text_height,
            preset=preset,
        )

        text_bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align="left")
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        text_x = panel_left + padding
        text_y = panel_top + padding + max(0, (max_text_height - text_height) // 2)

        draw.multiline_text(
            (text_x, text_y),
            text,
            font=font,
            fill=preset.text_color_rgba,
            spacing=spacing,
            align="left",
            stroke_width=preset.stroke_width,
            stroke_fill=preset.stroke_color_rgba,
        )

        output = io.BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        return output.getvalue()

    def _fit_text_to_box(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        max_width: int,
        max_height: int,
        preset: TextStylePreset,
    ) -> tuple[str, ImageFont.ImageFont, int]:
        """Find best fitting wrapped text + font size for target box."""

        min_font_size = 14
        start_font_size = min(78, max(min(max_height // 2, max_width // 9), 26))

        for size in range(start_font_size, min_font_size - 1, -2):
            font = _load_font(preset.font_candidates, size)
            spacing = max(4, size // 6)
            wrapped = _wrap_text_to_width(draw, text, font, max_width)

            bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=spacing, align="left")
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            if width <= max_width and height <= max_height:
                return wrapped, font, spacing

        fallback_font = _load_font(preset.font_candidates, min_font_size)
        fallback_spacing = max(3, min_font_size // 6)
        fallback_text = _wrap_text_to_width(draw, text, fallback_font, max_width)
        return fallback_text, fallback_font, fallback_spacing


def _estimate_background_color(image: Image.Image) -> tuple[int, int, int]:
    """Estimate dominant background color using border samples."""

    width, height = image.size
    pixels = image.load()
    step = max(1, min(width, height) // 64)

    samples: list[tuple[int, int, int]] = []

    for x in range(0, width, step):
        samples.append(pixels[x, 0])
        samples.append(pixels[x, height - 1])
    for y in range(0, height, step):
        samples.append(pixels[0, y])
        samples.append(pixels[width - 1, y])

    if not samples:
        return 245, 245, 245

    # Mean is sufficient because border sample count is intentionally large.
    red = int(sum(sample[0] for sample in samples) / len(samples))
    green = int(sum(sample[1] for sample in samples) / len(samples))
    blue = int(sum(sample[2] for sample in samples) / len(samples))
    return red, green, blue


def _estimate_border_noise(diff_gray: Image.Image) -> float:
    """Estimate background noise level from grayscale difference image borders."""

    width, height = diff_gray.size
    pixels = diff_gray.load()
    step = max(1, min(width, height) // 80)

    values: list[int] = []
    for x in range(0, width, step):
        values.append(int(pixels[x, 0]))
        values.append(int(pixels[x, height - 1]))
    for y in range(0, height, step):
        values.append(int(pixels[0, y]))
        values.append(int(pixels[width - 1, y]))

    if not values:
        return 8.0

    return float(sum(values) / len(values))


def _mask_overlap_ratio(mask: Image.Image, left: int, top: int, width: int, height: int) -> float:
    """Calculate share of non-background pixels inside candidate box."""

    crop = mask.crop((left, top, left + width, top + height))
    hist = crop.histogram()
    area = max(1, width * height)
    foreground_pixels = sum(hist[1:])
    return foreground_pixels / area


def _bbox_overlap_ratio(
    candidate_box: tuple[int, int, int, int],
    product_box: tuple[int, int, int, int] | None,
) -> float:
    """Compute overlap ratio between candidate text box and product bounding box."""

    if product_box is None:
        return 0.0

    c_left, c_top, c_right, c_bottom = candidate_box
    p_left, p_top, p_right, p_bottom = product_box

    inter_left = max(c_left, p_left)
    inter_top = max(c_top, p_top)
    inter_right = min(c_right, p_right)
    inter_bottom = min(c_bottom, p_bottom)

    if inter_right <= inter_left or inter_bottom <= inter_top:
        return 0.0

    inter_area = (inter_right - inter_left) * (inter_bottom - inter_top)
    candidate_area = max(1, (c_right - c_left) * (c_bottom - c_top))
    return inter_area / candidate_area


def _center_penalty(
    image_width: int,
    image_height: int,
    box_left: int,
    box_top: int,
    box_width: int,
    box_height: int,
) -> float:
    """Penalty for placing text too close to image center (where product usually sits)."""

    center_x = box_left + (box_width / 2)
    center_y = box_top + (box_height / 2)
    image_center_x = image_width / 2
    image_center_y = image_height / 2

    dist = ((center_x - image_center_x) ** 2 + (center_y - image_center_y) ** 2) ** 0.5
    max_dist = ((image_center_x**2) + (image_center_y**2)) ** 0.5
    if max_dist == 0:
        return 0.0

    normalized_distance = min(1.0, dist / max_dist)
    return 1.0 - normalized_distance


def _wrap_text_to_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int = 4,
) -> str:
    """Word-wrap text for target width with graceful truncation."""

    words = text.split()
    if not words:
        return ""

    lines: list[str] = []
    current_words: list[str] = []

    for word in words:
        # If one token is too long, split it first to keep layout stable.
        token_parts = _split_long_token(draw, word, font, max_width)
        for token in token_parts:
            trial_words = current_words + [token]
            trial_line = " ".join(trial_words)

            bbox = draw.textbbox((0, 0), trial_line, font=font)
            line_width = bbox[2] - bbox[0]

            if line_width <= max_width or not current_words:
                current_words = trial_words
            else:
                lines.append(" ".join(current_words))
                current_words = [token]

    if current_words:
        lines.append(" ".join(current_words))

    if len(lines) <= max_lines:
        return "\n".join(lines)

    clipped = lines[: max_lines - 1]
    tail = " ".join(lines[max_lines - 1 :]).strip()
    if tail:
        tail = tail[: max(1, len(tail) - 1)] + "..."
    clipped.append(tail)
    return "\n".join(clipped)


def _split_long_token(
    draw: ImageDraw.ImageDraw,
    token: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    """Split a very long token so each chunk fits max_width."""

    if not token:
        return [token]

    bbox = draw.textbbox((0, 0), token, font=font)
    if (bbox[2] - bbox[0]) <= max_width:
        return [token]

    chunks: list[str] = []
    current = ""
    for char in token:
        trial = current + char
        trial_bbox = draw.textbbox((0, 0), trial, font=font)
        if (trial_bbox[2] - trial_bbox[0]) <= max_width or not current:
            current = trial
        else:
            chunks.append(current)
            current = char
    if current:
        chunks.append(current)

    return chunks


def _load_font(candidates: tuple[str, ...], size: int) -> ImageFont.ImageFont:
    """Load first available font from candidate list with robust fallback."""

    for font_name in candidates:
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue

    return ImageFont.load_default()


def _extract_http_error(response: httpx.Response) -> str:
    """Extract readable API error from JSON or plain text body."""

    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:400] if text else "No details provided."

    if isinstance(payload, dict):
        if isinstance(payload.get("error"), str):
            return payload["error"]
        if isinstance(payload.get("message"), str):
            return payload["message"]
        error_obj = payload.get("error")
        if isinstance(error_obj, dict):
            message = error_obj.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()

    return "No structured error details provided."


def _normalize_headline(text: str) -> str:
    """Clean and normalize LLM output to stable one-line headline."""

    normalized = text.strip().strip("`\"' ")
    normalized = " ".join(normalized.split())

    if len(normalized) > 160:
        normalized = normalized[:160].rsplit(" ", 1)[0].strip()

    return normalized


def _env_int(key: str, default: int) -> int:
    """Parse integer env value with fallback."""

    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid int in %s=%s. Using default=%s.", key, raw, default)
        return default


def _env_float(key: str, default: float) -> float:
    """Parse float env value with fallback."""

    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float in %s=%s. Using default=%s.", key, raw, default)
        return default


# Lazy singleton for app-wide reuse.
_default_infographic_service: InfographicService | None = None


def get_infographic_service() -> InfographicService:
    """Get singleton infographic service configured from environment."""

    global _default_infographic_service
    if _default_infographic_service is None:
        _default_infographic_service = InfographicService(LLMConfig.from_env())
    return _default_infographic_service


async def close_infographic_service() -> None:
    """Close singleton resources (recommended during app shutdown)."""

    global _default_infographic_service
    if _default_infographic_service is not None:
        await _default_infographic_service.aclose()
        _default_infographic_service = None


async def generate_infographic_package(product_image: bytes, thesis_ru: str) -> InfographicPackage:
    """Convenience wrapper for singleton service usage."""

    service = get_infographic_service()
    return await service.generate_infographic_package(product_image=product_image, thesis_ru=thesis_ru)
