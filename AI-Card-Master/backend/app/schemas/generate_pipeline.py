"""Pydantic v2 contracts for POST /api/v1/generate-pipeline (n8n bridge)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)

MarketplaceCode = Literal["wildberries", "ozon", "amazon", "other"]
BadgeVariant = Literal["solid", "glass"]

_HTTP_URL = TypeAdapter(HttpUrl)


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _require_http_url(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string URL.")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty.")
    try:
        _HTTP_URL.validate_python(cleaned)
    except Exception as exc:  # noqa: BLE001 — surface as field error
        raise ValueError(f"{field_name} must be an absolute http(s) URL.") from exc
    return cleaned


class GeneratePipelineRequest(StrictAPIModel):
    """Product parameters accepted from the frontend and forwarded to n8n."""

    product_name: str = Field(..., min_length=1, max_length=256)
    product_category: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=5000)
    image_url: str = Field(
        ...,
        min_length=8,
        max_length=2048,
        description="Public HTTP(S) URL of the source product image.",
    )
    marketplace: MarketplaceCode | None = None
    benefits: list[str] = Field(default_factory=list, max_length=24)
    style_prompt: str | None = Field(default=None, max_length=2000)
    locale: str = Field(default="ru", min_length=2, max_length=16)

    @field_validator("product_name", "product_category", "description", "style_prompt")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.strip().split())
        return cleaned or None

    @field_validator("product_name")
    @classmethod
    def _require_product_name(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("product_name is required.")
        return value.strip()

    @field_validator("image_url")
    @classmethod
    def _validate_image_url(cls, value: str) -> str:
        return _require_http_url(value, field_name="image_url")

    @field_validator("benefits")
    @classmethod
    def _clean_benefits(cls, value: list[str] | tuple[str, ...]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("Each benefit must be a string.")
            text = " ".join(item.strip().split())
            if not text:
                continue
            if len(text) > 300:
                raise ValueError("Each benefit must be at most 300 characters.")
            cleaned.append(text)
        return cleaned

    @field_validator("locale")
    @classmethod
    def _clean_locale(cls, value: str) -> str:
        cleaned = value.strip().lower().replace("_", "-")
        if not cleaned:
            raise ValueError("locale must not be empty.")
        return cleaned

    def to_n8n_payload(self, *, request_id: UUID, user_id: UUID) -> dict[str, object]:
        """Stable JSON body sent to the n8n webhook."""

        return {
            "request_id": str(request_id),
            "user_id": str(user_id),
            "product_name": self.product_name,
            "product_category": self.product_category,
            "description": self.description,
            "image_url": self.image_url,
            "marketplace": self.marketplace,
            "benefits": list(self.benefits),
            "style_prompt": self.style_prompt,
            "locale": self.locale,
        }


class PipelineLayerUrls(StrictAPIModel):
    """Raster layer URLs produced by the n8n workflow (editor layers 1–2)."""

    background_url: str = Field(..., min_length=8, max_length=2048)
    product_url: str = Field(..., min_length=8, max_length=2048)

    @field_validator("background_url", "product_url")
    @classmethod
    def _validate_layer_url(cls, value: str, info: ValidationInfo) -> str:
        return _require_http_url(value, field_name=info.field_name or "url")


class PipelineBadge(StrictAPIModel):
    """Infographic plaque / chip for editor layer 3."""

    text: str = Field(..., min_length=1, max_length=256)
    subtitle: str | None = Field(default=None, max_length=256)
    bg_color: str = Field(
        default="#1F2937",
        min_length=4,
        max_length=9,
        pattern=r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$",
    )
    text_color: str = Field(
        default="#FFFFFF",
        min_length=4,
        max_length=9,
        pattern=r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$",
    )
    icon_id: str = Field(default="sparkles", min_length=1, max_length=64)
    variant: BadgeVariant = "solid"
    x: float | None = Field(default=None, ge=0.0, le=100.0)
    y: float | None = Field(default=None, ge=0.0, le=100.0)
    width: float | None = Field(default=None, gt=0.0, le=100.0)
    height: float | None = Field(default=None, gt=0.0, le=100.0)

    @field_validator("text", "subtitle", "icon_id")
    @classmethod
    def _strip_badge_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.strip().split())
        return cleaned or None

    @field_validator("text")
    @classmethod
    def _require_badge_text(cls, value: str | None) -> str:
        if value is None or not str(value).strip():
            raise ValueError("badge text is required.")
        return str(value).strip()


class N8nPipelineResult(StrictAPIModel):
    """Validated body expected from n8n ``Respond to Webhook``."""

    layers: PipelineLayerUrls
    badges: list[PipelineBadge] = Field(default_factory=list, max_length=48)

    @model_validator(mode="before")
    @classmethod
    def _normalize_n8n_aliases(cls, value: object) -> object:
        """Accept common n8n alias keys without loosening the public API."""

        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "layers" not in data and "layer_urls" in data:
            data["layers"] = data.pop("layer_urls")
        if "badges" not in data and "plaques" in data:
            data["badges"] = data.pop("plaques")
        layers = data.get("layers")
        if isinstance(layers, dict):
            layer_data = dict(layers)
            if "background_url" not in layer_data and "background" in layer_data:
                layer_data["background_url"] = layer_data.pop("background")
            if "product_url" not in layer_data and "product" in layer_data:
                layer_data["product_url"] = layer_data.pop("product")
            data["layers"] = layer_data
        return data


class GeneratePipelineResponse(StrictAPIModel):
    """Structured JSON returned to the frontend after a successful n8n run."""

    success: bool = True
    request_id: UUID
    layers: PipelineLayerUrls
    badges: list[PipelineBadge] = Field(default_factory=list)
    product_name: str = Field(..., min_length=1, max_length=256)
