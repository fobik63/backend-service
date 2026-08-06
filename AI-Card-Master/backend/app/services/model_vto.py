"""Virtual try-on task builder for the AI Model generation mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.series_generator import SeriesTask


MODEL_VTO_SLIDE_KEY = "model"
MODEL_VTO_PRODUCT_CATEGORY = "clothing_model_vto"

BodyType = Literal["slim", "regular", "athletic", "plus_size"]
Ethnicity = Literal[
    "european",
    "asian",
    "middle_eastern",
    "african",
    "latino",
    "mixed",
]


@dataclass(frozen=True, slots=True)
class ModelTypage:
    """Provider-neutral description of the AI model body profile."""

    height_cm: int
    body_type: BodyType
    ethnicity: Ethnicity


def build_model_vto_task(
    *,
    typage: ModelTypage,
    background: str | None = None,
    pose: str | None = None,
) -> SeriesTask:
    """Build one direct VTO task that transfers clothing onto a generated model."""

    height_label = f"{typage.height_cm} cm tall"
    body_label = _body_type_prompt(typage.body_type)
    ethnicity_label = _ethnicity_prompt(typage.ethnicity)
    background_label = _clean_optional_prompt(
        background,
        fallback="clean premium marketplace studio, soft realistic shadows",
    )
    pose_label = _clean_optional_prompt(
        pose,
        fallback="natural standing catalog pose, full body visible",
    )

    return SeriesTask(
        slide_key=MODEL_VTO_SLIDE_KEY,
        selected_style="virtual try-on photorealistic fashion model",
        user_text=(
            "Virtual try-on task. Use the source image only as the garment reference. "
            "Transfer the exact clothing item onto a realistic AI fashion model. "
            "Preserve fabric texture, cut, color, seams, logos, print placement, and fit. "
            f"Model profile: {height_label}, {body_label}, {ethnicity_label}. "
            f"Pose: {pose_label}. Background: {background_label}. "
            "Generate a single photorealistic marketplace image, full outfit visible, "
            "realistic body proportions, natural garment drape, no duplicate garments, "
            "no extra text, no watermark, no brand hallucination, no distorted hands or face."
        ),
    )


def _body_type_prompt(value: BodyType) -> str:
    labels: dict[BodyType, str] = {
        "slim": "slim body build",
        "regular": "regular body build",
        "athletic": "athletic body build",
        "plus_size": "plus-size body build",
    }
    return labels[value]


def _ethnicity_prompt(value: Ethnicity) -> str:
    labels: dict[Ethnicity, str] = {
        "european": "European appearance",
        "asian": "Asian appearance",
        "middle_eastern": "Middle Eastern appearance",
        "african": "African appearance",
        "latino": "Latino appearance",
        "mixed": "mixed ethnicity appearance",
    }
    return labels[value]


def _clean_optional_prompt(value: str | None, *, fallback: str) -> str:
    if value is None:
        return fallback
    cleaned = " ".join(value.strip().split())
    return cleaned or fallback
