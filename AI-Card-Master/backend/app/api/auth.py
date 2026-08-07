"""Auth API: register, login, refresh, and current-user profile."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payments import get_current_user
from app.application.auth_service import (
    AuthConflictError,
    AuthCredentialsError,
    AuthDisposableEmailError,
    AuthNotFoundError,
    AuthRefreshError,
    AuthRegistrationBlockedError,
    AuthService,
    AuthTokenFamilyRevokedError,
    AuthTokenStoreError,
)
from app.core.rate_limit import auth_bruteforce_limit
from app.domain.auth import LoginCommand, RegisterCommand
from app.domain.signup_trial import SignupAbuseContext
from app.infrastructure.auth_factory import build_auth_service
from app.models.database import get_db_session
from app.models.user import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RegisterRequest(StrictAPIModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(StrictAPIModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)


class RefreshRequest(StrictAPIModel):
    refresh_token: str = Field(..., min_length=20, max_length=4096)


class TokenResponse(StrictAPIModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AuthUserResponse(StrictAPIModel):
    id: UUID
    email: str
    ai_coins: int
    subscription_status: str
    is_admin: bool
    created_at: datetime | None = None


class AuthSessionResponse(StrictAPIModel):
    user: AuthUserResponse
    tokens: TokenResponse


def get_auth_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> AuthService:
    return build_auth_service(db_session)


def _user_response(view) -> AuthUserResponse:
    return AuthUserResponse(
        id=view.id,
        email=view.email,
        ai_coins=view.ai_coins,
        subscription_status=view.subscription_status,
        is_admin=view.is_admin,
        created_at=view.created_at,
    )


def _session_response(view, tokens) -> AuthSessionResponse:
    return AuthSessionResponse(
        user=_user_response(view),
        tokens=TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            token_type=tokens.token_type,
        ),
    )


def _device_abuse_context(request: Request) -> SignupAbuseContext:
    """Collect IP / UA / Accept-Language / X-Device-Fingerprint for anti-abuse."""

    client_ip = getattr(request.state, "client_ip", None) or (
        request.client.host if request.client is not None else "unknown"
    )
    user_agent = getattr(request.state, "user_agent", None) or (
        (request.headers.get("user-agent") or "")[:512]
    )
    accept_language = (request.headers.get("accept-language") or "")[:128]
    device_fingerprint = (
        request.headers.get("X-Device-Fingerprint")
        or request.headers.get("x-device-fingerprint")
        or ""
    ).strip()[:512]
    return SignupAbuseContext(
        client_ip=str(client_ip),
        user_agent=user_agent or "",
        accept_language=accept_language,
        device_fingerprint=device_fingerprint,
    )


@router.post(
    "/register",
    response_model=AuthSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
@auth_bruteforce_limit
async def register(
    payload: RegisterRequest,
    request: Request,
    auth: AuthService = Depends(get_auth_service),
) -> AuthSessionResponse:
    try:
        command = RegisterCommand(email=payload.email, password=payload.password)
        view, tokens = await auth.register(
            command,
            abuse_context=_device_abuse_context(request),
        )
    except (ValueError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except AuthDisposableEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except AuthRegistrationBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except AuthConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return _session_response(view, tokens)


@router.post(
    "/login",
    response_model=AuthSessionResponse,
    summary="Login and obtain JWT access/refresh tokens",
)
@auth_bruteforce_limit
async def login(
    payload: LoginRequest,
    request: Request,
    auth: AuthService = Depends(get_auth_service),
) -> AuthSessionResponse:
    try:
        command = LoginCommand(email=payload.email, password=payload.password)
        view, tokens = await auth.login(
            command,
            abuse_context=_device_abuse_context(request),
        )
    except (ValueError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except AuthCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return _session_response(view, tokens)


@router.post(
    "/refresh",
    response_model=AuthSessionResponse,
    summary="Rotate refresh token (RTR) and obtain a new JWT pair",
)
@auth_bruteforce_limit
async def refresh(
    payload: RefreshRequest,
    request: Request,
    auth: AuthService = Depends(get_auth_service),
) -> AuthSessionResponse:
    try:
        view, tokens = await auth.refresh(payload.refresh_token)
    except AuthTokenFamilyRevokedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except (AuthRefreshError, AuthNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AuthCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AuthTokenStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return _session_response(view, tokens)


@router.get(
    "/me",
    response_model=AuthUserResponse,
    summary="Return the authenticated user profile",
)
async def me(
    current_user: User = Depends(get_current_user),
    auth: AuthService = Depends(get_auth_service),
) -> AuthUserResponse:
    try:
        view = await auth.get_profile(current_user.id)
    except AuthNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AuthCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    return _user_response(view)
