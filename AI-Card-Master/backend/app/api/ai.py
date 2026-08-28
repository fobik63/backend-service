"""REST API: AI SEO description / benefits generation for WB and Ozon."""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.llm_coin_guard import require_seo_card_coins
from app.application.llm_coin_guard import LlmCoinGuard
from app.application.seo_text_service import SEO_TEXT_COST_COINS, SeoTextService
from app.domain.llm_coin_guard import InsufficientCoinsError
from app.domain.seo_text import (
    SeoTargetPlatform,
    SeoTextConfigurationError,
    SeoTextGenerateRequest,
    SeoTextUpstreamError,
    SeoTextValidationError,
)
from app.infrastructure.seo_text_factory import build_seo_text_service
from app.models.database import get_db_session
from app.models.user import User
from app.services.billing_service import BillingNotFoundError, BillingValidationError
from app.services.telegram_product_notify import notify_pack_generated

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class GenerateDescriptionRequest(StrictAPIModel):
    title: str = Field(..., min_length=1, max_length=500)
    category: str = Field(..., min_length=1, max_length=256)
    features: dict[str, Any] = Field(default_factory=dict)
    target_platform: Literal["wb", "ozon"] = Field(
        ...,
        alias="targetPlatform",
        description="Target marketplace: wb (≤5000 chars) or ozon (≤10000 chars).",
    )


class TokenUsageDTO(StrictAPIModel):
    prompt_tokens: int = Field(..., ge=0)
    completion_tokens: int = Field(..., ge=0)
    total_tokens: int = Field(..., ge=0)


class GenerateDescriptionResponse(StrictAPIModel):
    success: bool = True
    optimized_title: str = Field(..., min_length=1)
    benefits: list[str] = Field(..., min_length=4, max_length=6)
    description: str = Field(..., min_length=1)
    usage: TokenUsageDTO
    coins_charged: int = Field(..., ge=0)
    new_balance: int = Field(..., ge=0)
    cost_coins: int = Field(default=SEO_TEXT_COST_COINS, ge=0)
    target_platform: Literal["wb", "ozon"] = Field(..., alias="targetPlatform")


def _get_seo_text_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> SeoTextService:
    return build_seo_text_service(db_session)


@router.post(
    "/generate-description",
    response_model=GenerateDescriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate SEO offer, key tags, and product description (OpenAI)",
    description=(
        "Generates a selling marketplace offer (title), 4–6 key tags/USPs, "
        "and a detailed product SEO description (800–1200 chars) for WB/Ozon cards. "
        "Copy focuses on the product, not visual design of the photo. "
        f"Charges {SEO_TEXT_COST_COINS} AI-coins via LlmCoinGuard / BillingService "
        "when billing is enabled. Requires OPENAI_API_KEY (or LLM_API_KEY)."
    ),
)
async def generate_description_endpoint(
    body: GenerateDescriptionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SeoTextService, Depends(_get_seo_text_service)],
    _coin_guard: Annotated[LlmCoinGuard, Depends(require_seo_card_coins)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="X-Idempotency-Key",
            description="Optional durable billing idempotency key",
        ),
    ] = None,
) -> GenerateDescriptionResponse:
    cleaned_key = idempotency_key.strip() if idempotency_key else None
    if cleaned_key == "":
        cleaned_key = None

    domain_request = _domain_seo_request(body)

    try:
        result = await service.generate(
            user_id=current_user.id,
            request=domain_request,
            idempotency_key=cleaned_key,
        )
    except SeoTextValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except SeoTextConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except InsufficientCoinsError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=exc.to_http_detail(),
        ) from exc
    except BillingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(exc),
        ) from exc
    except BillingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except SeoTextUpstreamError as exc:
        logger.exception("SEO text upstream failure")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("SEO text generation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SEO text generation failed.",
        ) from exc

    await notify_pack_generated(
        user_id=current_user.id,
        title=result.content.optimized_title,
    )

    return GenerateDescriptionResponse(
        success=True,
        optimized_title=result.content.optimized_title,
        benefits=list(result.content.benefits),
        description=result.content.description,
        usage=TokenUsageDTO(
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            total_tokens=result.usage.total_tokens,
        ),
        coins_charged=result.coins_charged,
        new_balance=result.new_balance,
        cost_coins=service.cost_coins,
        target_platform=body.target_platform,
    )


class GenerateDescriptionBatchRequest(StrictAPIModel):
    items: list[GenerateDescriptionRequest] = Field(..., min_length=1, max_length=50)


class GenerateDescriptionBatchItemResponse(StrictAPIModel):
    optimized_title: str = Field(..., min_length=1)
    benefits: list[str] = Field(..., min_length=4, max_length=6)
    description: str = Field(..., min_length=1)
    usage: TokenUsageDTO
    coins_charged: int = Field(..., ge=0)
    target_platform: Literal["wb", "ozon"] = Field(..., alias="targetPlatform")


class GenerateDescriptionBatchResponse(StrictAPIModel):
    success: bool = True
    items: list[GenerateDescriptionBatchItemResponse]
    coins_charged: int = Field(..., ge=0)
    new_balance: int = Field(..., ge=0)
    skipped_count: int = Field(..., ge=0)
    stopped_reason: str | None = None
    cost_coins: int = Field(default=SEO_TEXT_COST_COINS, ge=0)


def _domain_seo_request(body: GenerateDescriptionRequest) -> SeoTextGenerateRequest:
    return SeoTextGenerateRequest(
        title=body.title,
        category=body.category,
        features=body.features,
        target_platform=SeoTargetPlatform(body.target_platform),
    )


@router.post(
    "/generate-description-batch",
    response_model=GenerateDescriptionBatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Batch-generate SEO copy for many WB/Ozon cards",
    description=(
        "Generates SEO artifacts for up to 50 product cards. Coins are pre-debited "
        f"per card ({SEO_TEXT_COST_COINS} coins each). If the wallet runs out mid-batch, "
        "already generated cards are kept and remaining items are skipped."
    ),
)
async def generate_description_batch_endpoint(
    body: GenerateDescriptionBatchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SeoTextService, Depends(_get_seo_text_service)],
    _coin_guard: Annotated[LlmCoinGuard, Depends(require_seo_card_coins)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="X-Idempotency-Key",
            description="Optional durable billing idempotency key",
        ),
    ] = None,
) -> GenerateDescriptionBatchResponse:
    cleaned_key = idempotency_key.strip() if idempotency_key else None
    if cleaned_key == "":
        cleaned_key = None

    domain_requests = tuple(_domain_seo_request(item) for item in body.items)

    try:
        result = await service.generate_batch(
            user_id=current_user.id,
            requests=domain_requests,
            idempotency_key=cleaned_key,
        )
    except SeoTextValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except SeoTextConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except InsufficientCoinsError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=exc.to_http_detail(),
        ) from exc
    except BillingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(exc),
        ) from exc
    except BillingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except SeoTextUpstreamError as exc:
        logger.exception("SEO batch upstream failure")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("SEO batch generation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SEO text generation failed.",
        ) from exc

    items: list[GenerateDescriptionBatchItemResponse] = []
    for generated, request in zip(result.items, domain_requests, strict=False):
        items.append(
            GenerateDescriptionBatchItemResponse(
                optimized_title=generated.content.optimized_title,
                benefits=list(generated.content.benefits),
                description=generated.content.description,
                usage=TokenUsageDTO(
                    prompt_tokens=generated.usage.prompt_tokens,
                    completion_tokens=generated.usage.completion_tokens,
                    total_tokens=generated.usage.total_tokens,
                ),
                coins_charged=generated.coins_charged,
                target_platform=request.target_platform.value,
            )
        )

    return GenerateDescriptionBatchResponse(
        success=True,
        items=items,
        coins_charged=result.coins_charged,
        new_balance=result.new_balance,
        skipped_count=result.skipped_count,
        stopped_reason=result.stopped_reason,
        cost_coins=service.cost_coins,
    )
