"""Composition root for auth HTTP façade."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.auth_service import AuthService
from app.infrastructure.persistence.auth_repository import AuthRepository


def build_auth_service(session: AsyncSession) -> AuthService:
    return AuthService(AuthRepository(session))
