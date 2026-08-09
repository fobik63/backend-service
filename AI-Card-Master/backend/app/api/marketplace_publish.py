"""Publish generated infographics and SEO text into WB / Ozon seller cabinets."""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.api.user_credentials import get_marketplace_publish_service
from app.application.marketplace_publish_service import MarketplacePublishService
from app.domain.marketplace_publish import (
    MarketplacePublishNotFoundError,
    MarketplacePublishValidationError,
    OzonPublishRequest,
    PublishPlatform,
    PublishResultView,
    PublishStatus,
    SellerProductView,
    WbPublishRequest,
)
from app.models.database import get_db_session
from app.models.user import User
from app.services.telegram_product_notify import (
    notify_publish_error,
    notify_publish_success,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/marketplaces/publish", tags=["marketplace-publish"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PublishWbRequest(StrictAPIModel):
    """Push S3 image URLs + SEO text onto an existing Wildberries nmID."""

    nm_id: int = Field(..., gt=0, description="Wildberries nomenclature id (nmID).")
    image_urls: list[str] = Field(..., min_length=1, max_length=30)
    seo_text: str = Field(..., min_length=1, max_length=5000)
    title: str | None = Field(default=None, max_length=100)
    vendor_code: str | None = Field(default=None, max_length=64)

    @field_validator("image_urls")
    @classmethod
    def _https_urls(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in value:
            url = raw.strip()
            if not url.startswith("https://"):
                raise ValueError("image_urls must be public HTTPS links.")
            cleaned.append(url)
        return cleaned


class PublishOzonRequest(StrictAPIModel):
    """Push S3 image URLs + description onto an existing Ozon product_id."""

    product_id: int = Field(..., gt=0)
    image_urls: list[str] = Field(..., min_length=1, max_length=15)
    description: str = Field(..., min_length=1, max_length=10_000)
    offer_id: str | None = Field(default=None, max_length=64)
    description_attribute_id: int = Field(default=4191, gt=0)

    @field_validator("image_urls")
    @classmethod
    def _https_urls(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in value:
            url = raw.strip()
            if not url.startswith("https://"):
                raise ValueError("image_urls must be public HTTPS links.")
            cleaned.append(url)
        return cleaned


class PublishStatusResponse(StrictAPIModel):
    id: UUID
    platform: str
    product_id: str
    status: PublishStatus
    message: str
    external_task_id: str | None = None
    error_logs: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class SellerProductResponse(StrictAPIModel):
    platform: str
    product_id: str
    title: str
    vendor_code: str | None = None
    brand: str | None = None


class SellerProductListResponse(StrictAPIModel):
    items: list[SellerProductResponse] = Field(default_factory=list)


@router.get("/products", response_model=SellerProductListResponse)
async def list_seller_products(
    platform: Literal["wb", "ozon"] = Query(..., description="Marketplace: wb or ozon"),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: MarketplacePublishService = Depends(get_marketplace_publish_service),
) -> SellerProductListResponse:
    """List seller-cabinet articles for the publish target picker."""

    try:
        items = await service.list_seller_products(
            user_id=current_user.id,
            platform=PublishPlatform(platform),
            limit=limit,
        )
    except MarketplacePublishValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except MarketplacePublishNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected seller product list failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list seller products.",
        ) from exc
    return SellerProductListResponse(
        items=[_product_to_response(item) for item in items]
    )


@router.post("/wb", response_model=PublishStatusResponse)
async def publish_to_wildberries(
    body: PublishWbRequest,
    current_user: User = Depends(get_current_user),
    service: MarketplacePublishService = Depends(get_marketplace_publish_service),
) -> PublishStatusResponse:
    """
    Update an existing WB card: SEO via /content/v2/cards/update,
    media via /content/v3/media/save (public HTTPS links from S3).
    """

    try:
        result = await service.publish_wb(
            user_id=current_user.id,
            request=WbPublishRequest(
                nm_id=body.nm_id,
                image_urls=tuple(body.image_urls),
                seo_text=body.seo_text,
                title=body.title,
                vendor_code=body.vendor_code,
            ),
        )
    except MarketplacePublishValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except MarketplacePublishNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected WB publish failure")
        await notify_publish_error(
            user_id=current_user.id,
            platform="wb",
            product_id=str(body.nm_id),
            detail="Внутренняя ошибка сервера.",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Wildberries publish request failed.",
        ) from exc
    await _notify_publish_result(user_id=current_user.id, result=result)
    return _to_response(result)


@router.post("/ozon", response_model=PublishStatusResponse)
async def publish_to_ozon(
    body: PublishOzonRequest,
    current_user: User = Depends(get_current_user),
    service: MarketplacePublishService = Depends(get_marketplace_publish_service),
) -> PublishStatusResponse:
    """
    Update an existing Ozon product: description via /v1/product/attributes/update,
    images via /v1/product/pictures/import.
    """

    try:
        result = await service.publish_ozon(
            user_id=current_user.id,
            request=OzonPublishRequest(
                product_id=body.product_id,
                image_urls=tuple(body.image_urls),
                description=body.description,
                offer_id=body.offer_id,
                description_attribute_id=body.description_attribute_id,
            ),
        )
    except MarketplacePublishValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except MarketplacePublishNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected Ozon publish failure")
        await notify_publish_error(
            user_id=current_user.id,
            platform="ozon",
            product_id=str(body.product_id),
            detail="Внутренняя ошибка сервера.",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ozon publish request failed.",
        ) from exc
    await _notify_publish_result(user_id=current_user.id, result=result)
    return _to_response(result)


async def _notify_publish_result(*, user_id: UUID, result: PublishResultView) -> None:
    if result.status is PublishStatus.FAILED:
        await notify_publish_error(
            user_id=user_id,
            platform=result.platform.value,
            product_id=result.product_id,
            detail=result.message,
        )
        return
    await notify_publish_success(
        user_id=user_id,
        platform=result.platform.value,
        product_id=result.product_id,
    )


def _product_to_response(item: SellerProductView) -> SellerProductResponse:
    return SellerProductResponse(
        platform=item.platform.value,
        product_id=item.product_id,
        title=item.title,
        vendor_code=item.vendor_code,
        brand=item.brand,
    )


def _to_response(result: PublishResultView) -> PublishStatusResponse:
    return PublishStatusResponse(
        id=result.id,
        platform=result.platform.value,
        product_id=result.product_id,
        status=result.status,
        message=result.message,
        external_task_id=result.external_task_id,
        error_logs=list(result.error_logs),
        created_at=result.created_at,
    )


# Re-export for tests that inject a custom session dependency.
__all__ = ["router", "get_marketplace_publish_service", "get_db_session"]
