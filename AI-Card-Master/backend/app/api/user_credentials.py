"""CRUD API for encrypted WB / Ozon seller credentials on the user model."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.application.marketplace_publish_service import MarketplacePublishService
from app.domain.marketplace_publish import (
    MarketplacePublishNotFoundError,
    MarketplacePublishValidationError,
    UserMarketplaceCredentialsInput,
    UserMarketplaceCredentialsView,
)
from app.infrastructure.marketplace_publish_factory import build_marketplace_publish_service
from app.models.database import get_db_session
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/user/credentials", tags=["user-credentials"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SaveUserCredentialsRequest(StrictAPIModel):
    """Save one or more seller API secrets (encrypted at rest on the user row)."""

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


class UserCredentialsResponse(StrictAPIModel):
    wb_configured: bool
    ozon_configured: bool
    wb_valid: bool | None = None
    ozon_valid: bool | None = None
    wb_validation_message: str | None = None
    ozon_validation_message: str | None = None
    updated_at: datetime | None = None


async def get_marketplace_publish_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> MarketplacePublishService:
    return build_marketplace_publish_service(db_session)


@router.get("", response_model=UserCredentialsResponse)
async def get_user_credentials(
    current_user: User = Depends(get_current_user),
    service: MarketplacePublishService = Depends(get_marketplace_publish_service),
) -> UserCredentialsResponse:
    """Return which marketplace keys are configured (secrets are never returned)."""

    view = await service.get_credentials(current_user.id)
    return _to_response(view)


@router.put("", response_model=UserCredentialsResponse)
async def save_user_credentials(
    body: SaveUserCredentialsRequest,
    current_user: User = Depends(get_current_user),
    service: MarketplacePublishService = Depends(get_marketplace_publish_service),
) -> UserCredentialsResponse:
    """Encrypt and store wb_api_token / ozon_client_id / ozon_api_key on the user."""

    try:
        view = await service.save_credentials(
            user_id=current_user.id,
            payload=UserMarketplaceCredentialsInput(
                wb_api_token=body.wb_api_token,
                ozon_client_id=body.ozon_client_id,
                ozon_api_key=body.ozon_api_key,
                validate_credentials=body.validate_credentials,
            ),
        )
    except MarketplacePublishValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except MarketplacePublishNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to save user marketplace credentials")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save marketplace credentials.",
        ) from exc

    from app.domain.audit_log import AuditEventStatus, AuditEventType
    from app.services.audit_events import record_audit_event

    await record_audit_event(
        event_type=AuditEventType.SETTINGS_CHANGED,
        status=AuditEventStatus.SUCCESS,
        user_id=current_user.id,
        telegram_id=current_user.telegram_id,
        actor_type="user",
        message="Marketplace seller credentials updated",
        metadata={
            "setting": "user_marketplace_credentials",
            "wb": body.wb_api_token is not None,
            "ozon": body.ozon_client_id is not None or body.ozon_api_key is not None,
        },
    )
    return _to_response(view)


@router.post("/validate", response_model=UserCredentialsResponse)
async def validate_user_credentials(
    current_user: User = Depends(get_current_user),
    service: MarketplacePublishService = Depends(get_marketplace_publish_service),
) -> UserCredentialsResponse:
    """Probe WB Content API and Ozon Seller API with stored credentials."""

    view = await service.validate_stored_credentials(current_user.id)
    return _to_response(view)


@router.delete("", response_model=UserCredentialsResponse)
async def delete_user_credentials(
    current_user: User = Depends(get_current_user),
    service: MarketplacePublishService = Depends(get_marketplace_publish_service),
    clear_wb: bool = Query(default=False),
    clear_ozon: bool = Query(default=False),
) -> UserCredentialsResponse:
    """Clear encrypted WB and/or Ozon credential columns on the user."""

    try:
        view = await service.delete_credentials(
            user_id=current_user.id,
            clear_wb=clear_wb,
            clear_ozon=clear_ozon,
        )
    except MarketplacePublishValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except MarketplacePublishNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(view)


def _to_response(view: UserMarketplaceCredentialsView) -> UserCredentialsResponse:
    return UserCredentialsResponse(
        wb_configured=view.wb_configured,
        ozon_configured=view.ozon_configured,
        wb_valid=view.wb_valid,
        ozon_valid=view.ozon_valid,
        wb_validation_message=view.wb_validation_message,
        ozon_validation_message=view.ozon_validation_message,
        updated_at=view.updated_at,
    )
