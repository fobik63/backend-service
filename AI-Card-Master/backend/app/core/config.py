"""Application configuration loaded from environment variables.

The settings class is intentionally strict because security-sensitive values
must be validated at startup rather than failing later at runtime.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class MidjourneyProviderSettings(BaseModel):
    """Configuration for one provider-neutral asynchronous image adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: SecretStr
    imagine_path: str = "/jobs/imagine"
    status_path_template: str = "/jobs/{job_id}"
    authorization_scheme: Literal["bearer", "token", "api-key"] = "bearer"
    webhook_token: SecretStr | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("https://", "http://")):
            raise ValueError("Provider base_url must be an absolute HTTP(S) URL.")
        return normalized


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

    # Comma-separated origins for Next.js / local frontends (CORS).
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        alias="CORS_ORIGINS",
    )
    cors_allow_credentials: bool = Field(default=True, alias="CORS_ALLOW_CREDENTIALS")

    # Stable Diffusion immediate/fallback provider.
    stable_diffusion_api_key: SecretStr | None = Field(
        default=None,
        alias="STABLE_DIFFUSION_API_KEY",
    )
    stable_diffusion_base_url: str = Field(
        default="https://api.stability.ai",
        alias="STABLE_DIFFUSION_BASE_URL",
    )
    stable_diffusion_engine_id: str = Field(
        default="stable-diffusion-xl-1024-v1-0",
        alias="STABLE_DIFFUSION_ENGINE_ID",
    )
    stable_diffusion_timeout_seconds: float = Field(
        default=60.0,
        alias="STABLE_DIFFUSION_TIMEOUT_SECONDS",
    )
    stable_diffusion_connect_timeout_seconds: float = Field(
        default=8.0,
        alias="STABLE_DIFFUSION_CONNECT_TIMEOUT_SECONDS",
    )
    stable_diffusion_max_connections: int = Field(
        default=300,
        alias="STABLE_DIFFUSION_MAX_CONNECTIONS",
    )
    stable_diffusion_max_keepalive_connections: int = Field(
        default=120,
        alias="STABLE_DIFFUSION_MAX_KEEPALIVE_CONNECTIONS",
    )
    stable_diffusion_keepalive_expiry_seconds: float = Field(
        default=30.0,
        alias="STABLE_DIFFUSION_KEEPALIVE_EXPIRY_SECONDS",
    )
    stable_diffusion_max_parallel_requests: int = Field(
        default=200,
        alias="STABLE_DIFFUSION_MAX_PARALLEL_REQUESTS",
    )
    stable_diffusion_max_retries: int = Field(
        default=3,
        alias="STABLE_DIFFUSION_MAX_RETRIES",
    )
    stable_diffusion_base_retry_delay_seconds: float = Field(
        default=0.35,
        alias="STABLE_DIFFUSION_BASE_RETRY_DELAY_SECONDS",
    )
    stable_diffusion_image_strength: float = Field(
        default=0.35,
        alias="STABLE_DIFFUSION_IMAGE_STRENGTH",
    )
    stable_diffusion_cfg_scale: int = Field(default=8, alias="STABLE_DIFFUSION_CFG_SCALE")
    stable_diffusion_steps: int = Field(default=30, alias="STABLE_DIFFUSION_STEPS")

    # Legacy Midjourney proxy API. Kept for compatibility; the disabled
    # useapi.net endpoint is deliberately not a default.
    midjourney_api_key: SecretStr | None = Field(default=None, alias="MIDJOURNEY_API_KEY")
    midjourney_base_url: str = Field(default="", alias="MIDJOURNEY_BASE_URL")
    midjourney_timeout_seconds: float = Field(
        default=180.0,
        alias="MIDJOURNEY_TIMEOUT_SECONDS",
    )
    midjourney_poll_interval_seconds: float = Field(
        default=3.0,
        alias="MIDJOURNEY_POLL_INTERVAL_SECONDS",
    )
    midjourney_max_poll_attempts: int = Field(
        default=60,
        alias="MIDJOURNEY_MAX_POLL_ATTEMPTS",
    )
    midjourney_providers: tuple[MidjourneyProviderSettings, ...] = Field(
        default_factory=tuple,
        alias="MIDJOURNEY_PROVIDERS",
    )
    midjourney_callback_base_url: str = Field(
        default="",
        alias="MIDJOURNEY_CALLBACK_BASE_URL",
    )
    midjourney_webhook_token: SecretStr = Field(
        default=SecretStr(""),
        alias="MIDJOURNEY_WEBHOOK_TOKEN",
    )
    midjourney_reply_ref_secret: SecretStr = Field(
        default=SecretStr(""),
        alias="MIDJOURNEY_REPLY_REF_SECRET",
    )
    midjourney_callback_timeout_seconds: int = Field(
        default=600,
        alias="MIDJOURNEY_CALLBACK_TIMEOUT_SECONDS",
    )
    midjourney_circuit_breaker_failures: int = Field(
        default=3,
        alias="MIDJOURNEY_CIRCUIT_BREAKER_FAILURES",
    )
    midjourney_circuit_breaker_ttl_seconds: int = Field(
        default=120,
        alias="MIDJOURNEY_CIRCUIT_BREAKER_TTL_SECONDS",
    )

    # Redis, Celery, and durable generation workflow.
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str | None = Field(default=None, alias="CELERY_BROKER_URL")
    celery_result_backend: str | None = Field(default=None, alias="CELERY_RESULT_BACKEND")
    celery_task_always_eager: bool = Field(default=False, alias="CELERY_TASK_ALWAYS_EAGER")
    celery_outbox_batch_size: int = Field(default=100, alias="CELERY_OUTBOX_BATCH_SIZE")
    generation_job_timeout_seconds: int = Field(
        default=1800,
        alias="GENERATION_JOB_TIMEOUT_SECONDS",
    )
    generation_max_upload_bytes: int = Field(
        default=20 * 1024 * 1024,
        alias="GENERATION_MAX_UPLOAD_BYTES",
    )
    generation_max_result_bytes: int = Field(
        default=30 * 1024 * 1024,
        alias="GENERATION_MAX_RESULT_BYTES",
    )
    generation_allowed_result_hosts: str = Field(
        default="",
        alias="GENERATION_ALLOWED_RESULT_HOSTS",
    )
    generation_charge_coins: bool = Field(default=True, alias="GENERATION_CHARGE_COINS")
    smart_inpainting_edge_pass_enabled: bool = Field(
        default=False,
        alias="SMART_INPAINTING_EDGE_PASS_ENABLED",
    )
    style_cache_ttl_seconds: int = Field(default=86400, alias="STYLE_CACHE_TTL_SECONDS")
    style_cache_version: str = Field(default="v1", alias="STYLE_CACHE_VERSION")

    # YooKassa payments
    yookassa_shop_id: str | None = Field(default=None, alias="YOOKASSA_SHOP_ID")
    yookassa_secret_key: SecretStr | None = Field(
        default=None,
        alias="YOOKASSA_SECRET_KEY",
    )
    yookassa_api_base_url: str = Field(
        default="https://api.yookassa.ru/v3",
        alias="YOOKASSA_API_BASE_URL",
    )
    yookassa_return_url: str = Field(
        default="http://localhost:3000/payments/return",
        alias="YOOKASSA_RETURN_URL",
    )
    yookassa_timeout_seconds: float = Field(
        default=30.0,
        alias="YOOKASSA_TIMEOUT_SECONDS",
    )
    # 1 = НДС не облагается (typical for digital services; adjust per your tax setup)
    yookassa_vat_code: int = Field(default=1, alias="YOOKASSA_VAT_CODE")

    # Selectel S3-compatible object storage
    s3_endpoint_url: str | None = Field(default=None, alias="S3_ENDPOINT_URL")
    s3_access_key_id: str | None = Field(default=None, alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: SecretStr | None = Field(
        default=None,
        alias="S3_SECRET_ACCESS_KEY",
    )
    s3_bucket_name: str | None = Field(default=None, alias="S3_BUCKET_NAME")
    s3_region: str = Field(default="ru-1", alias="S3_REGION")
    s3_addressing_style: Literal["path", "virtual"] = Field(
        default="path",
        alias="S3_ADDRESSING_STYLE",
    )
    s3_presign_ttl_seconds: int = Field(
        default=3600,
        alias="S3_PRESIGN_TTL_SECONDS",
    )

    # Critical 500 alerts sent to an operator-owned Telegram bot.
    telegram_error_bot_token: SecretStr | None = Field(
        default=None,
        alias="TELEGRAM_ERROR_BOT_TOKEN",
    )
    telegram_error_chat_id: str | None = Field(
        default=None,
        alias="TELEGRAM_ERROR_CHAT_ID",
    )
    telegram_error_timeout_seconds: float = Field(
        default=5.0,
        alias="TELEGRAM_ERROR_TIMEOUT_SECONDS",
    )

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

    @field_validator("s3_presign_ttl_seconds", "yookassa_vat_code")
    @classmethod
    def validate_positive_ints(cls, value: int) -> int:
        """Ensure storage / payment numeric settings stay positive."""

        if value <= 0:
            raise ValueError("Value must be greater than zero.")
        return value

    @field_validator(
        "midjourney_callback_timeout_seconds",
        "midjourney_max_poll_attempts",
        "midjourney_circuit_breaker_failures",
        "midjourney_circuit_breaker_ttl_seconds",
        "celery_outbox_batch_size",
        "generation_job_timeout_seconds",
        "generation_max_upload_bytes",
        "generation_max_result_bytes",
        "style_cache_ttl_seconds",
        "stable_diffusion_max_connections",
        "stable_diffusion_max_keepalive_connections",
        "stable_diffusion_max_parallel_requests",
        "stable_diffusion_cfg_scale",
        "stable_diffusion_steps",
    )
    @classmethod
    def validate_generation_positive_ints(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Generation and queue numeric settings must be positive.")
        return value

    @field_validator(
        "stable_diffusion_timeout_seconds",
        "stable_diffusion_connect_timeout_seconds",
        "stable_diffusion_keepalive_expiry_seconds",
        "stable_diffusion_base_retry_delay_seconds",
        "midjourney_timeout_seconds",
        "midjourney_poll_interval_seconds",
        "telegram_error_timeout_seconds",
    )
    @classmethod
    def validate_positive_floats(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Timeout/retry settings must be positive.")
        return value

    @field_validator("stable_diffusion_image_strength")
    @classmethod
    def validate_image_strength(cls, value: float) -> float:
        if not 0 < value <= 1:
            raise ValueError("STABLE_DIFFUSION_IMAGE_STRENGTH must be in (0, 1].")
        return value

    @field_validator("stable_diffusion_max_retries")
    @classmethod
    def validate_non_negative_retries(cls, value: int) -> int:
        if value < 0:
            raise ValueError("STABLE_DIFFUSION_MAX_RETRIES cannot be negative.")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith(("redis://", "rediss://")):
            raise ValueError("REDIS_URL must start with redis:// or rediss://.")
        return normalized

    @model_validator(mode="after")
    def validate_async_provider_security(self) -> "Settings":
        if not self.midjourney_providers:
            return self
        callback_base = self.midjourney_callback_base_url.strip().rstrip("/")
        if not callback_base.startswith(("https://", "http://")):
            raise ValueError(
                "MIDJOURNEY_CALLBACK_BASE_URL is required for async providers."
            )
        if self.app_env == "production" and not callback_base.startswith("https://"):
            raise ValueError("Production provider callbacks must use HTTPS.")
        shared_token = self.midjourney_webhook_token.get_secret_value().strip()
        reply_secret = self.midjourney_reply_ref_secret.get_secret_value().strip()
        if not reply_secret and not shared_token:
            raise ValueError(
                "MIDJOURNEY_REPLY_REF_SECRET or MIDJOURNEY_WEBHOOK_TOKEN is required."
            )
        for provider in self.midjourney_providers:
            provider_token = (
                provider.webhook_token.get_secret_value().strip()
                if provider.webhook_token is not None
                else shared_token
            )
            if not provider_token:
                raise ValueError(
                    f"Webhook token is required for provider '{provider.name}'."
                )
        return self

    @property
    def async_database_url(self) -> str:
        """Return SQLAlchemy async URL variant for PostgreSQL."""

        if self.database_url.startswith("postgresql+asyncpg://"):
            return self.database_url
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins into a clean list for CORSMiddleware."""

        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def effective_celery_broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def effective_celery_result_backend(self) -> str:
        if self.celery_result_backend:
            return self.celery_result_backend
        if self.redis_url.rsplit("/", 1)[-1].isdigit():
            prefix, _database = self.redis_url.rsplit("/", 1)
            return f"{prefix}/1"
        return self.redis_url

    @property
    def allowed_result_hosts(self) -> frozenset[str]:
        return frozenset(
            host.strip().lower()
            for host in self.generation_allowed_result_hosts.split(",")
            if host.strip()
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get a cached settings instance."""

    return Settings()  # type: ignore[call-arg]
