"""Application configuration loaded from environment variables.

The settings class is intentionally strict because security-sensitive values
must be validated at startup rather than failing later at runtime.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized application settings.

    All secrets are read from environment variables (or `.env`).
    No hardcoded cryptographic values are allowed.
    """

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "staging", "production"] = Field(
        default="development",
        alias="APP_ENV",
    )

    database_url: str = Field(..., alias="DATABASE_URL")

    jwt_secret_key: SecretStr = Field(..., alias="JWT_SECRET_KEY")
    jwt_algorithm: Literal["HS512", "HS384", "HS256"] = Field(
        default="HS512",
        alias="JWT_ALGORITHM",
    )
    jwt_access_token_ttl_minutes: int = Field(
        default=15,
        alias="JWT_ACCESS_TOKEN_TTL_MINUTES",
    )
    jwt_refresh_token_ttl_days: int = Field(
        default=30,
        alias="JWT_REFRESH_TOKEN_TTL_DAYS",
    )
    jwt_issuer: str = Field(default="ai-card-master-api", alias="JWT_ISSUER")
    jwt_audience: str = Field(default="ai-card-master-clients", alias="JWT_AUDIENCE")

    password_pepper: SecretStr = Field(default=SecretStr(""), alias="PASSWORD_PEPPER")

    # Argon2id tuning can be adapted for the deployment hardware profile.
    argon2_memory_cost_kib: int = Field(default=131072, alias="ARGON2_MEMORY_COST_KIB")
    argon2_time_cost: int = Field(default=4, alias="ARGON2_TIME_COST")
    argon2_parallelism: int = Field(default=4, alias="ARGON2_PARALLELISM")

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        """Allow only PostgreSQL URLs for this service."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("DATABASE_URL must not be empty.")
        if not normalized.startswith(("postgresql://", "postgresql+asyncpg://")):
            raise ValueError(
                "DATABASE_URL must start with postgresql:// or postgresql+asyncpg://"
            )
        return normalized

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret_key(cls, value: SecretStr) -> SecretStr:
        """Enforce strong HMAC secret length.

        64+ characters is a practical minimum for HS512 in modern deployments.
        """

        secret = value.get_secret_value()
        if len(secret) < 64:
            raise ValueError("JWT_SECRET_KEY must contain at least 64 characters.")
        return value

    @field_validator("jwt_access_token_ttl_minutes", "jwt_refresh_token_ttl_days")
    @classmethod
    def validate_positive_ttls(cls, value: int) -> int:
        """Ensure token TTL values are always positive."""

        if value <= 0:
            raise ValueError("Token TTL values must be greater than zero.")
        return value

    @field_validator("argon2_memory_cost_kib", "argon2_time_cost", "argon2_parallelism")
    @classmethod
    def validate_argon2_parameters(cls, value: int) -> int:
        """Ensure Argon2 parameters are non-zero positive integers."""

        if value <= 0:
            raise ValueError("Argon2 parameters must be greater than zero.")
        return value

    @property
    def async_database_url(self) -> str:
        """Return SQLAlchemy async URL variant for PostgreSQL."""

        if self.database_url.startswith("postgresql+asyncpg://"):
            return self.database_url
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get a cached settings instance."""

    return Settings()
