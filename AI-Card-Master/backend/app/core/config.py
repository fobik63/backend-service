"""Application configuration loaded from environment variables.

The settings class is intentionally strict because security-sensitive values
must be validated at startup rather than failing later at runtime.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import (
    AliasChoices,
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

    # Hidden admin API gate. Empty value disables /api/v1/admin for everyone.
    admin_allowed_user_id: str = Field(default="", alias="ADMIN_ALLOWED_USER_ID")

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
    midjourney_generation_cost_usd: Decimal = Field(
        default=Decimal("0"),
        alias="MIDJOURNEY_GENERATION_COST_USD",
    )
    face_fix_api_key: SecretStr | None = Field(default=None, alias="FACE_FIX_API_KEY")
    face_fix_base_url: str = Field(default="", alias="FACE_FIX_BASE_URL")
    face_fix_path: str = Field(default="/v1/face-fix", alias="FACE_FIX_PATH")
    face_fix_model_name: str = Field(default="face-fix-auto", alias="FACE_FIX_MODEL_NAME")
    face_fix_timeout_seconds: float = Field(default=45.0, alias="FACE_FIX_TIMEOUT_SECONDS")
    face_fix_connect_timeout_seconds: float = Field(
        default=8.0,
        alias="FACE_FIX_CONNECT_TIMEOUT_SECONDS",
    )
    face_fix_max_connections: int = Field(default=80, alias="FACE_FIX_MAX_CONNECTIONS")
    face_fix_max_retries: int = Field(default=2, alias="FACE_FIX_MAX_RETRIES")
    face_fix_cost_usd: Decimal = Field(default=Decimal("0"), alias="FACE_FIX_COST_USD")

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
    generation_fast_cost_coins: int = Field(default=1, alias="GENERATION_FAST_COST_COINS")
    generation_hd_face_fix_cost_coins: int = Field(
        default=3,
        alias="GENERATION_HD_FACE_FIX_COST_COINS",
    )
    daily_bonus_coins: int = Field(default=1, alias="DAILY_BONUS_COINS")
    referral_bonus_coins: int = Field(default=10, alias="REFERRAL_BONUS_COINS")
    workspace_max_managers: int = Field(default=3, alias="WORKSPACE_MAX_MANAGERS")

    # Churn Prevention / Win-back
    winback_inactivity_days: int = Field(default=10, alias="WINBACK_INACTIVITY_DAYS")
    winback_free_generations: int = Field(default=5, alias="WINBACK_FREE_GENERATIONS")
    winback_discount_percent: int = Field(default=30, alias="WINBACK_DISCOUNT_PERCENT")
    winback_offer_ttl_hours: int = Field(default=72, alias="WINBACK_OFFER_TTL_HOURS")
    winback_inactivity_scan_seconds: float = Field(
        default=3600.0,
        alias="WINBACK_INACTIVITY_SCAN_SECONDS",
    )
    winback_style_update_scan_seconds: float = Field(
        default=86400.0,
        alias="WINBACK_STYLE_UPDATE_SCAN_SECONDS",
    )
    winback_style_campaign_key: str = Field(
        default="luxury_loft_update_v1",
        alias="WINBACK_STYLE_CAMPAIGN_KEY",
    )

    # Bulk Generation (ZIP of 1–20 products → background preset run)
    bulk_generation_max_products: int = Field(
        default=20,
        alias="BULK_GENERATION_MAX_PRODUCTS",
    )
    bulk_generation_max_zip_bytes: int = Field(
        default=200 * 1024 * 1024,
        alias="BULK_GENERATION_MAX_ZIP_BYTES",
    )
    bulk_generation_poll_seconds: float = Field(
        default=15.0,
        alias="BULK_GENERATION_POLL_SECONDS",
    )
    bulk_generation_poll_batch_size: int = Field(
        default=50,
        alias="BULK_GENERATION_POLL_BATCH_SIZE",
    )

    # Smart Variant Sync (1 photo → N fabric color variants)
    smart_variant_max_colors: int = Field(
        default=10,
        alias="SMART_VARIANT_MAX_COLORS",
    )
    smart_variant_poll_seconds: float = Field(
        default=15.0,
        alias="SMART_VARIANT_POLL_SECONDS",
    )
    smart_variant_poll_batch_size: int = Field(
        default=50,
        alias="SMART_VARIANT_POLL_BATCH_SIZE",
    )

    # Direct Export (WB / Ozon / Amazon seller drafts)
    marketplace_credentials_secret: SecretStr = Field(
        default=SecretStr(""),
        alias="MARKETPLACE_CREDENTIALS_SECRET",
    )
    marketplace_export_timeout_seconds: float = Field(
        default=30.0,
        alias="MARKETPLACE_EXPORT_TIMEOUT_SECONDS",
    )
    wildberries_content_api_base_url: str = Field(
        default="https://content-api.wildberries.ru",
        alias="WILDBERRIES_CONTENT_API_BASE_URL",
    )
    wildberries_statistics_api_base_url: str = Field(
        default="https://statistics-api.wildberries.ru",
        alias="WILDBERRIES_STATISTICS_API_BASE_URL",
    )
    ozon_seller_api_base_url: str = Field(
        default="https://api-seller.ozon.ru",
        alias="OZON_SELLER_API_BASE_URL",
    )
    amazon_sp_api_base_url: str = Field(
        default="https://sellingpartnerapi-eu.amazon.com",
        alias="AMAZON_SP_API_BASE_URL",
    )
    marketplace_bridge_timeout_seconds: float = Field(
        default=45.0,
        alias="MARKETPLACE_BRIDGE_TIMEOUT_SECONDS",
    )

    # Isolated stock parser (WB/Ozon mobile JSON endpoints — no Selenium).
    # STOCK_PARSER_PROXY_URLS: comma/semicolon separated http(s)/socks5 URLs.
    stock_parser_proxy_urls: str = Field(
        default="",
        alias="STOCK_PARSER_PROXY_URLS",
    )
    stock_parser_timeout_seconds: float = Field(
        default=20.0,
        alias="STOCK_PARSER_TIMEOUT_SECONDS",
    )
    stock_parser_circuit_breaker_threshold: int = Field(
        default=5,
        alias="STOCK_PARSER_CIRCUIT_BREAKER_THRESHOLD",
    )
    stock_parser_wb_card_base_url: str = Field(
        default="https://card.wb.ru",
        alias="STOCK_PARSER_WB_CARD_BASE_URL",
    )
    stock_parser_wb_dest: int = Field(
        default=-1257786,
        alias="STOCK_PARSER_WB_DEST",
    )
    stock_parser_ozon_api_base_url: str = Field(
        default="https://api.ozon.ru",
        alias="STOCK_PARSER_OZON_API_BASE_URL",
    )
    # Celery Beat nightly scrape (UTC). Chunk size caps RAM / soft time limits.
    stock_parser_chunk_size: int = Field(
        default=100,
        alias="STOCK_PARSER_CHUNK_SIZE",
    )
    stock_parser_beat_hour_utc: int = Field(
        default=3,
        alias="STOCK_PARSER_BEAT_HOUR_UTC",
    )
    stock_parser_beat_minute_utc: int = Field(
        default=0,
        alias="STOCK_PARSER_BEAT_MINUTE_UTC",
    )

    # Manual competitor-link audit (plan §77): deep scrape via Celery.
    competitor_audit_proxy_urls: str = Field(
        default="",
        alias="COMPETITOR_AUDIT_PROXY_URLS",
    )
    competitor_audit_timeout_seconds: float = Field(
        default=25.0,
        alias="COMPETITOR_AUDIT_TIMEOUT_SECONDS",
    )
    competitor_audit_redis_ttl_seconds: int = Field(
        default=3600,
        alias="COMPETITOR_AUDIT_REDIS_TTL_SECONDS",
    )
    competitor_audit_max_reviews: int = Field(
        default=50,
        alias="COMPETITOR_AUDIT_MAX_REVIEWS",
    )
    competitor_audit_wb_content_base_url: str = Field(
        default="https://wbx-content-v2.wbstatic.net",
        alias="COMPETITOR_AUDIT_WB_CONTENT_BASE_URL",
    )
    competitor_audit_max_vision_images: int = Field(
        default=5,
        alias="COMPETITOR_AUDIT_MAX_VISION_IMAGES",
    )
    competitor_audit_image_timeout_seconds: float = Field(
        default=20.0,
        alias="COMPETITOR_AUDIT_IMAGE_TIMEOUT_SECONDS",
    )

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
    # User-facing Telegram bot for win-back / style-update triggers.
    # Falls back to TELEGRAM_ERROR_BOT_TOKEN when unset.
    telegram_user_bot_token: SecretStr | None = Field(
        default=None,
        alias="TELEGRAM_USER_BOT_TOKEN",
    )
    telegram_user_timeout_seconds: float = Field(
        default=5.0,
        alias="TELEGRAM_USER_TIMEOUT_SECONDS",
    )

    # Claude 4.7 Opus Vision & Reasoning Integration Layer
    claude_47_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("CLAUDE_47_API_KEY", "ANTHROPIC_API_KEY"),
    )
    claude_47_base_url: str = Field(
        default="https://api.anthropic.com",
        alias="CLAUDE_47_BASE_URL",
    )
    claude_47_model: str = Field(
        default="claude-opus-4-7",
        alias="CLAUDE_47_MODEL",
    )
    claude_47_api_version: str = Field(
        default="2023-06-01",
        alias="CLAUDE_47_API_VERSION",
    )
    claude_47_structured_outputs_beta: str = Field(
        default="",
        alias="CLAUDE_47_STRUCTURED_OUTPUTS_BETA",
    )
    claude_47_timeout_seconds: float = Field(
        default=120.0,
        alias="CLAUDE_47_TIMEOUT_SECONDS",
    )
    claude_47_max_connections: int = Field(
        default=40,
        alias="CLAUDE_47_MAX_CONNECTIONS",
    )
    claude_47_max_keepalive_connections: int = Field(
        default=20,
        alias="CLAUDE_47_MAX_KEEPALIVE_CONNECTIONS",
    )
    claude_47_max_retries: int = Field(default=2, alias="CLAUDE_47_MAX_RETRIES")
    claude_47_base_retry_delay_seconds: float = Field(
        default=0.5,
        alias="CLAUDE_47_BASE_RETRY_DELAY_SECONDS",
    )
    # Kept for legacy env compatibility; Opus 4.7 rejects temperature in requests.
    claude_47_temperature: float = Field(
        default=0.2,
        alias="CLAUDE_47_TEMPERATURE",
    )
    claude_47_effort: Literal["low", "medium", "high", "xhigh", "max"] = Field(
        default="high",
        alias="CLAUDE_47_EFFORT",
    )
    claude_47_vision_max_tokens: int = Field(
        default=4096,
        alias="CLAUDE_47_VISION_MAX_TOKENS",
    )
    claude_47_reasoning_max_tokens: int = Field(
        default=4096,
        alias="CLAUDE_47_REASONING_MAX_TOKENS",
    )
    claude_47_max_images_per_request: int = Field(
        default=5,
        alias="CLAUDE_47_MAX_IMAGES_PER_REQUEST",
    )
    claude_47_stage_cache_ttl_seconds: int = Field(
        default=3600,
        alias="CLAUDE_47_STAGE_CACHE_TTL_SECONDS",
    )
    claude_47_processing_timeout_seconds: int = Field(
        default=900,
        alias="CLAUDE_47_PROCESSING_TIMEOUT_SECONDS",
    )
    claude_47_outbox_batch_size: int = Field(
        default=100,
        alias="CLAUDE_47_OUTBOX_BATCH_SIZE",
    )
    claude_47_recovery_batch_size: int = Field(
        default=50,
        alias="CLAUDE_47_RECOVERY_BATCH_SIZE",
    )
    claude_47_input_1k_tokens_cost_usd: Decimal = Field(
        default=Decimal("0"),
        alias="CLAUDE_47_INPUT_1K_TOKENS_COST_USD",
    )
    claude_47_output_1k_tokens_cost_usd: Decimal = Field(
        default=Decimal("0"),
        alias="CLAUDE_47_OUTPUT_1K_TOKENS_COST_USD",
    )

    # Intelligent visual audit (Brand Dominant filter → Rising Stars)
    visual_audit_top_n: int = Field(default=50, alias="VISUAL_AUDIT_TOP_N")
    visual_audit_brand_dominant_soft_reviews: int = Field(
        default=5000,
        alias="VISUAL_AUDIT_BRAND_DOMINANT_SOFT_REVIEWS",
    )
    visual_audit_brand_dominant_hard_reviews: int = Field(
        default=7000,
        alias="VISUAL_AUDIT_BRAND_DOMINANT_HARD_REVIEWS",
    )
    visual_audit_rising_min_reviews: int = Field(
        default=50,
        alias="VISUAL_AUDIT_RISING_MIN_REVIEWS",
    )
    visual_audit_rising_max_reviews: int = Field(
        default=1500,
        alias="VISUAL_AUDIT_RISING_MAX_REVIEWS",
    )
    visual_audit_min_sales_growth_ratio: float = Field(
        default=0.30,
        alias="VISUAL_AUDIT_MIN_SALES_GROWTH_RATIO",
    )
    visual_audit_min_review_velocity_per_day: float = Field(
        default=3.0,
        alias="VISUAL_AUDIT_MIN_REVIEW_VELOCITY_PER_DAY",
    )
    visual_audit_max_rising_stars_for_vision: int = Field(
        default=12,
        alias="VISUAL_AUDIT_MAX_RISING_STARS_FOR_VISION",
    )

    # Parser ↔ «Глаз Бога» bridge (sales spike +30% / 3d → Claude Vision)
    eye_of_god_enabled: bool = Field(default=True, alias="EYE_OF_GOD_ENABLED")
    eye_of_god_recent_window_days: int = Field(
        default=3,
        alias="EYE_OF_GOD_RECENT_WINDOW_DAYS",
    )
    eye_of_god_baseline_window_days: int = Field(
        default=7,
        alias="EYE_OF_GOD_BASELINE_WINDOW_DAYS",
    )
    eye_of_god_min_growth_ratio: float = Field(
        default=0.30,
        alias="EYE_OF_GOD_MIN_GROWTH_RATIO",
    )
    eye_of_god_min_baseline_daily_sales: float = Field(
        default=1.0,
        alias="EYE_OF_GOD_MIN_BASELINE_DAILY_SALES",
    )
    eye_of_god_min_recent_reliable_days: int = Field(
        default=2,
        alias="EYE_OF_GOD_MIN_RECENT_RELIABLE_DAYS",
    )
    eye_of_god_cooldown_hours: int = Field(
        default=24,
        alias="EYE_OF_GOD_COOLDOWN_HOURS",
    )
    eye_of_god_lookback_days: int = Field(
        default=21,
        alias="EYE_OF_GOD_LOOKBACK_DAYS",
    )
    eye_of_god_max_images: int = Field(default=3, alias="EYE_OF_GOD_MAX_IMAGES")
    eye_of_god_image_timeout_seconds: float = Field(
        default=20.0,
        alias="EYE_OF_GOD_IMAGE_TIMEOUT_SECONDS",
    )

    # Market Gap & Trend Prediction (The Oracle)
    oracle_min_query_growth_ratio: float = Field(
        default=0.25,
        alias="ORACLE_MIN_QUERY_GROWTH_RATIO",
    )
    oracle_min_recent_query_volume: int = Field(
        default=500,
        alias="ORACLE_MIN_RECENT_QUERY_VOLUME",
    )
    oracle_max_top_cards_for_gap: int = Field(
        default=3,
        alias="ORACLE_MAX_TOP_CARDS_FOR_GAP",
    )
    oracle_min_gap_score: float = Field(
        default=40.0,
        alias="ORACLE_MIN_GAP_SCORE",
    )
    oracle_max_alerts: int = Field(default=10, alias="ORACLE_MAX_ALERTS")
    oracle_top_rank_ceiling: int = Field(
        default=50,
        alias="ORACLE_TOP_RANK_CEILING",
    )

    # Strategic Killer Recommendations (AI Strategy)
    ai_strategy_min_ctr_lift_pct: float = Field(
        default=5.0,
        alias="AI_STRATEGY_MIN_CTR_LIFT_PCT",
    )
    ai_strategy_min_absolute_ctr_gap: float = Field(
        default=0.5,
        alias="AI_STRATEGY_MIN_ABSOLUTE_CTR_GAP",
    )
    ai_strategy_max_recommendations: int = Field(
        default=7,
        alias="AI_STRATEGY_MAX_RECOMMENDATIONS",
    )
    ai_strategy_require_leader_ctr_advantage: bool = Field(
        default=True,
        alias="AI_STRATEGY_REQUIRE_LEADER_CTR_ADVANTAGE",
    )

    # Automated A/B Testing (3 creatives → CTR week → keep winner)
    ab_test_duration_days: int = Field(default=7, alias="AB_TEST_DURATION_DAYS")
    ab_test_min_impressions: int = Field(
        default=100,
        alias="AB_TEST_MIN_IMPRESSIONS",
    )
    ab_test_min_ctr_gap_pct: float = Field(
        default=0.05,
        alias="AB_TEST_MIN_CTR_GAP_PCT",
    )
    ab_test_auto_delete_losers: bool = Field(
        default=True,
        alias="AB_TEST_AUTO_DELETE_LOSERS",
    )
    ab_test_auto_promote_winner: bool = Field(
        default=True,
        alias="AB_TEST_AUTO_PROMOTE_WINNER",
    )
    ab_test_poll_seconds: float = Field(
        default=3600.0,
        alias="AB_TEST_POLL_SECONDS",
    )
    ab_test_poll_batch_size: int = Field(
        default=50,
        alias="AB_TEST_POLL_BATCH_SIZE",
    )
    ab_test_ads_timeout_seconds: float = Field(
        default=30.0,
        alias="AB_TEST_ADS_TIMEOUT_SECONDS",
    )
    ab_test_allow_ads_fallback: bool = Field(
        default=True,
        alias="AB_TEST_ALLOW_ADS_FALLBACK",
    )
    wildberries_advert_api_base_url: str = Field(
        default="https://advert-api.wildberries.ru",
        alias="WILDBERRIES_ADVERT_API_BASE_URL",
    )
    ozon_performance_api_base_url: str = Field(
        default="https://api-performance.ozon.ru",
        alias="OZON_PERFORMANCE_API_BASE_URL",
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
        "daily_bonus_coins",
        "referral_bonus_coins",
        "workspace_max_managers",
        "winback_inactivity_days",
        "winback_free_generations",
        "winback_discount_percent",
        "winback_offer_ttl_hours",
        "bulk_generation_max_products",
        "bulk_generation_max_zip_bytes",
        "bulk_generation_poll_batch_size",
        "smart_variant_max_colors",
        "smart_variant_poll_batch_size",
        "generation_fast_cost_coins",
        "generation_hd_face_fix_cost_coins",
        "style_cache_ttl_seconds",
        "stable_diffusion_max_connections",
        "stable_diffusion_max_keepalive_connections",
        "stable_diffusion_max_parallel_requests",
        "stable_diffusion_cfg_scale",
        "stable_diffusion_steps",
        "face_fix_max_connections",
        "face_fix_max_retries",
        "claude_47_max_connections",
        "claude_47_max_keepalive_connections",
        "claude_47_vision_max_tokens",
        "claude_47_reasoning_max_tokens",
        "claude_47_max_images_per_request",
        "claude_47_stage_cache_ttl_seconds",
        "claude_47_processing_timeout_seconds",
        "claude_47_outbox_batch_size",
        "claude_47_recovery_batch_size",
        "visual_audit_top_n",
        "visual_audit_brand_dominant_soft_reviews",
        "visual_audit_brand_dominant_hard_reviews",
        "visual_audit_rising_min_reviews",
        "visual_audit_rising_max_reviews",
        "visual_audit_max_rising_stars_for_vision",
        "eye_of_god_recent_window_days",
        "eye_of_god_baseline_window_days",
        "eye_of_god_min_recent_reliable_days",
        "eye_of_god_cooldown_hours",
        "eye_of_god_lookback_days",
        "eye_of_god_max_images",
        "oracle_min_recent_query_volume",
        "oracle_max_alerts",
        "oracle_top_rank_ceiling",
        "ai_strategy_max_recommendations",
        "stock_parser_circuit_breaker_threshold",
        "stock_parser_chunk_size",
        "competitor_audit_redis_ttl_seconds",
        "competitor_audit_max_reviews",
        "competitor_audit_max_vision_images",
    )
    @classmethod
    def validate_generation_positive_ints(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Generation and queue numeric settings must be positive.")
        return value

    @field_validator("stock_parser_beat_hour_utc")
    @classmethod
    def validate_stock_parser_beat_hour(cls, value: int) -> int:
        if not 0 <= value <= 23:
            raise ValueError("STOCK_PARSER_BEAT_HOUR_UTC must be in [0, 23].")
        return value

    @field_validator("stock_parser_beat_minute_utc")
    @classmethod
    def validate_stock_parser_beat_minute(cls, value: int) -> int:
        if not 0 <= value <= 59:
            raise ValueError("STOCK_PARSER_BEAT_MINUTE_UTC must be in [0, 59].")
        return value

    @field_validator(
        "stable_diffusion_timeout_seconds",
        "stable_diffusion_connect_timeout_seconds",
        "stable_diffusion_keepalive_expiry_seconds",
        "stable_diffusion_base_retry_delay_seconds",
        "midjourney_timeout_seconds",
        "midjourney_poll_interval_seconds",
        "face_fix_timeout_seconds",
        "face_fix_connect_timeout_seconds",
        "telegram_error_timeout_seconds",
        "telegram_user_timeout_seconds",
        "marketplace_export_timeout_seconds",
        "marketplace_bridge_timeout_seconds",
        "stock_parser_timeout_seconds",
        "competitor_audit_timeout_seconds",
        "competitor_audit_image_timeout_seconds",
        "winback_inactivity_scan_seconds",
        "winback_style_update_scan_seconds",
        "bulk_generation_poll_seconds",
        "smart_variant_poll_seconds",
        "claude_47_timeout_seconds",
        "claude_47_base_retry_delay_seconds",
        "eye_of_god_image_timeout_seconds",
    )
    @classmethod
    def validate_positive_floats(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Timeout/retry settings must be positive.")
        return value

    @field_validator("claude_47_max_retries")
    @classmethod
    def validate_claude_retries(cls, value: int) -> int:
        if value < 0:
            raise ValueError("CLAUDE_47_MAX_RETRIES cannot be negative.")
        return value

    @field_validator("claude_47_temperature")
    @classmethod
    def validate_claude_temperature(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("CLAUDE_47_TEMPERATURE must be in [0, 1].")
        return value

    @field_validator(
        "visual_audit_min_sales_growth_ratio",
        "visual_audit_min_review_velocity_per_day",
        "eye_of_god_min_growth_ratio",
        "eye_of_god_min_baseline_daily_sales",
        "oracle_min_query_growth_ratio",
        "oracle_min_gap_score",
        "ai_strategy_min_ctr_lift_pct",
        "ai_strategy_min_absolute_ctr_gap",
    )
    @classmethod
    def validate_visual_audit_non_negative_floats(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Visual audit ratio/velocity settings cannot be negative.")
        return value

    @field_validator("oracle_max_top_cards_for_gap")
    @classmethod
    def validate_oracle_max_top_cards(cls, value: int) -> int:
        if value < 0:
            raise ValueError("ORACLE_MAX_TOP_CARDS_FOR_GAP cannot be negative.")
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

    @field_validator(
        "midjourney_generation_cost_usd",
        "face_fix_cost_usd",
        "claude_47_input_1k_tokens_cost_usd",
        "claude_47_output_1k_tokens_cost_usd",
    )
    @classmethod
    def validate_non_negative_costs(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("Provider cost settings cannot be negative.")
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
