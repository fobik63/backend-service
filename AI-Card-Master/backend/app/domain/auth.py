"""Auth domain contracts (register / login / profile)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictDomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RegisterCommand(StrictDomainModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("Invalid email address.")
        return email


class LoginCommand(StrictDomainModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class OtpRequestCommand(StrictDomainModel):
    email: str = Field(..., min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("Invalid email address.")
        return email


class OtpVerifyCommand(StrictDomainModel):
    email: str = Field(..., min_length=3, max_length=320)
    code: str = Field(..., min_length=4, max_length=8)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        code = value.strip()
        if not code.isdigit():
            raise ValueError("OTP code must be numeric.")
        return code


@dataclass(frozen=True, slots=True)
class AuthTokens:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@dataclass(frozen=True, slots=True)
class AuthUserView:
    id: UUID
    email: str
    ai_coins: int
    subscription_status: str
    is_admin: bool
    is_banned: bool
    created_at: datetime | None
