"""DTOs for product background removal."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BgRemovalResultDTO(BaseModel):
    """Cutout PNG produced by the rembg engine."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    image_png: bytes = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class BgRemovalJobResultDTO(BaseModel):
    """Orchestrated result after billing + S3 upload."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    cdn_url: str = Field(min_length=1)
    object_key: str = Field(min_length=1)
    coins_charged: int = Field(ge=0)
    new_balance: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    content_type: Literal["image/png"] = "image/png"
