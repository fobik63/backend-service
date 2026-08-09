"""Domain models for pushing infographics / SEO into WB & Ozon seller cabinets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MarketplacePublishError(Exception):
    """Base marketplace publish / credentials failure."""


class MarketplacePublishValidationError(MarketplacePublishError, ValueError):
    """Invalid client input for credentials or publish requests."""


class MarketplacePublishNotFoundError(MarketplacePublishError):
    """Required credentials or product were not found."""


class MarketplacePublishUpstreamError(MarketplacePublishError):
    """Marketplace seller API rejected or failed the publish call."""

    def __init__(self, message: str, *, error_logs: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.error_logs = error_logs


class PublishPlatform(StrEnum):
    """Supported direct-publish destinations."""

    WILDBERRIES = "wb"
    OZON = "ozon"


class PublishStatus(StrEnum):
    """Outcome of a publish attempt against a seller cabinet."""

    SUCCESS = "Success"
    PENDING = "Pending"
    FAILED = "Failed"


class DomainModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )


class UserMarketplaceCredentialsInput(DomainModel):
    """Optional seller API secrets; omit fields that should stay unchanged."""

    wb_api_token: str | None = Field(default=None, max_length=4096)
    ozon_client_id: str | None = Field(default=None, max_length=256)
    ozon_api_key: str | None = Field(default=None, max_length=4096)
    validate_credentials: bool = True

    @field_validator("wb_api_token", "ozon_client_id", "ozon_api_key", mode="before")
    @classmethod
    def _strip_optional(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @model_validator(mode="after")
    def _require_at_least_one(self) -> UserMarketplaceCredentialsInput:
        if (
            self.wb_api_token is None
            and self.ozon_client_id is None
            and self.ozon_api_key is None
        ):
            raise ValueError("Provide at least one credential field to save.")
        return self


class UserMarketplaceCredentialsView(DomainModel):
    """Public view of configured seller credentials (secrets never exposed)."""

    wb_configured: bool
    ozon_configured: bool
    wb_valid: bool | None = None
    ozon_valid: bool | None = None
    wb_validation_message: str | None = None
    ozon_validation_message: str | None = None
    updated_at: datetime | None = None


class CredentialValidationResult(DomainModel):
    """Result of probing a marketplace with stored or candidate credentials."""

    platform: PublishPlatform
    is_valid: bool
    message: str
    error_logs: tuple[str, ...] = ()


class WbPublishRequest(DomainModel):
    """Publish images + SEO text onto an existing Wildberries nomenclature."""

    nm_id: int = Field(..., gt=0, description="Wildberries nmID (nomenclature id).")
    image_urls: tuple[str, ...] = Field(..., min_length=1, max_length=30)
    seo_text: str = Field(..., min_length=1, max_length=5000)
    title: str | None = Field(default=None, max_length=100)
    vendor_code: str | None = Field(default=None, max_length=64)

    @field_validator("image_urls")
    @classmethod
    def _https_urls(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned: list[str] = []
        for raw in value:
            url = raw.strip()
            if not url.startswith("https://"):
                raise ValueError("image_urls must be public HTTPS links (S3/CDN).")
            cleaned.append(url)
        return tuple(cleaned)

    @field_validator("seo_text", "title", "vendor_code", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class OzonPublishRequest(DomainModel):
    """Publish images + description onto an existing Ozon product."""

    product_id: int = Field(..., gt=0, description="Ozon product_id.")
    image_urls: tuple[str, ...] = Field(..., min_length=1, max_length=15)
    description: str = Field(..., min_length=1, max_length=10_000)
    offer_id: str | None = Field(default=None, max_length=64)
    description_attribute_id: int = Field(
        default=4191,
        gt=0,
        description="Ozon attribute id used for rich description (default 4191).",
    )

    @field_validator("image_urls")
    @classmethod
    def _https_urls(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned: list[str] = []
        for raw in value:
            url = raw.strip()
            if not url.startswith("https://"):
                raise ValueError("image_urls must be public HTTPS links (S3/CDN).")
            cleaned.append(url)
        return tuple(cleaned)

    @field_validator("description", mode="before")
    @classmethod
    def _strip_description(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("offer_id", mode="before")
    @classmethod
    def _strip_offer_id(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value


@dataclass(frozen=True, slots=True)
class PublishResultView:
    """Detailed publish outcome returned to API clients and persisted."""

    id: UUID
    platform: PublishPlatform
    product_id: str
    status: PublishStatus
    message: str
    external_task_id: str | None = None
    error_logs: tuple[str, ...] = ()
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SellerProductView:
    """One seller-cabinet product suitable for publish target selection."""

    platform: PublishPlatform
    product_id: str
    title: str
    vendor_code: str | None = None
    brand: str | None = None
