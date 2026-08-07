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
    # Geo tag for regional failover (plan §36), e.g. eu-nl / eu-de / us-east.
    region: str = Field(default="", max_length=64)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("https://", "http://")):
            raise ValueError("Provider base_url must be an absolute HTTP(S) URL.")
        return normalized

    @field_validator("region")
    @classmethod
    def normalize_region(cls, value: str) -> str:
        return value.strip().lower()


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
    # ALLOWED_ORIGINS is preferred; CORS_ORIGINS kept for backward compatibility.
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        validation_alias=AliasChoices("ALLOWED_ORIGINS", "CORS_ORIGINS"),
    )
    # Explicit allowlists — never use wildcard methods/headers in production.
    cors_allow_methods: str = Field(
        default="GET,POST,PUT,PATCH,DELETE,OPTIONS",
        alias="CORS_ALLOW_METHODS",
    )
    cors_allow_headers: str = Field(
        default=(
            "Authorization,Content-Type,Accept,Origin,X-Request-Id,"
            "X-Visitor-Id,Idempotency-Key,X-Idempotency-Key,X-API-Key,"
            "X-Webhook-Token,X-Webhook-Signature"
        ),
        alias="CORS_ALLOW_HEADERS",
    )
    cors_expose_headers: str = Field(
        default="X-Request-Id,Retry-After,X-Idempotency-Replayed",
        alias="CORS_EXPOSE_HEADERS",
    )

    # Public legal / GDPR operator identity (shown in Terms & Privacy pages).
    # Replace placeholders before production launch / payment acceptance.
    service_display_name: str = Field(
        default="AI-Card-Master",
        alias="SERVICE_DISPLAY_NAME",
    )
    public_site_url: str = Field(
        default="https://ai-card-master.example",
        alias="PUBLIC_SITE_URL",
    )
    legal_operator_name: str = Field(
        default="[УКАЖИТЕ ЮРИДИЧЕСКОЕ НАИМЕНОВАНИЕ ОПЕРАТОРА]",
        alias="LEGAL_OPERATOR_NAME",
    )
    legal_operator_address: str = Field(
        default="[УКАЖИТЕ ЮРИДИЧЕСКИЙ АДРЕС ОПЕРАТОРА]",
        alias="LEGAL_OPERATOR_ADDRESS",
    )
    legal_jurisdiction: str = Field(
        default="Российская Федерация",
        alias="LEGAL_JURISDICTION",
    )
    support_email: str = Field(
        default="support@example.com",
        alias="SUPPORT_EMAIL",
    )
    privacy_email: str = Field(
        default="privacy@example.com",
        alias="PRIVACY_EMAIL",
    )
    legal_documents_effective_date: str = Field(
        default="2026-08-07",
        alias="LEGAL_DOCUMENTS_EFFECTIVE_DATE",
    )
    cors_allow_credentials: bool = Field(default=True, alias="CORS_ALLOW_CREDENTIALS")

    # Hidden admin API gate. Empty value disables /api/v1/admin for everyone.
    admin_allowed_user_id: str = Field(default="", alias="ADMIN_ALLOWED_USER_ID")

    # --- Security layer (plan §14 + Great Wall §61) ---
    security_suspicious_middleware_enabled: bool = Field(
        default=True,
        alias="SECURITY_SUSPICIOUS_MIDDLEWARE_ENABLED",
    )
    security_input_sanitization_enabled: bool = Field(
        default=True,
        alias="SECURITY_INPUT_SANITIZATION_ENABLED",
    )
    security_reject_prompt_injection: bool = Field(
        default=True,
        alias="SECURITY_REJECT_PROMPT_INJECTION",
    )
    security_xss_protection_enabled: bool = Field(
        default=True,
        alias="SECURITY_XSS_PROTECTION_ENABLED",
        description="Reject XSS probes in path/query/JSON (Great Wall §61).",
    )
    security_rate_limit_per_minute: int = Field(
        default=120,
        alias="SECURITY_RATE_LIMIT_PER_MINUTE",
        description="Per-IP Redis rate limit window budget (Great Wall §61).",
    )
    # Cascading slowapi + Redis limits (public / auth / generations).
    slowapi_enabled: bool = Field(
        default=True,
        alias="SLOWAPI_ENABLED",
        description="Enable slowapi cascading rate limits (Redis-backed).",
    )
    slowapi_global_per_minute: int = Field(
        default=100,
        alias="SLOWAPI_GLOBAL_PER_MINUTE",
        description="Default per-IP budget for public endpoints (slowapi).",
    )
    slowapi_auth_per_minute: int = Field(
        default=5,
        alias="SLOWAPI_AUTH_PER_MINUTE",
        description="Shared per-IP budget for /auth login+register (brute-force).",
    )
    slowapi_generations_per_minute: int = Field(
        default=10,
        alias="SLOWAPI_GENERATIONS_PER_MINUTE",
        description="Shared per-user_id budget for /generations/* endpoints.",
    )
    slowapi_three_d_per_minute: int = Field(
        default=2,
        alias="SLOWAPI_THREE_D_PER_MINUTE",
        description="Per-user_id budget for POST /api/v1/3d/generate.",
    )
    # Redis idempotency for coin charges / generation task creation.
    idempotency_middleware_enabled: bool = Field(
        default=True,
        alias="IDEMPOTENCY_MIDDLEWARE_ENABLED",
        description=(
            "Enable Redis idempotency for POST/PUT generation and charge routes "
            "when X-Idempotency-Key is present."
        ),
    )
    idempotency_processing_ttl_seconds: int = Field(
        default=60,
        alias="IDEMPOTENCY_PROCESSING_TTL_SECONDS",
        description="TTL for in-flight PROCESSING markers (concurrent → 409).",
    )
    idempotency_response_ttl_seconds: int = Field(
        default=900,
        alias="IDEMPOTENCY_RESPONSE_TTL_SECONDS",
        description="TTL for cached successful responses (15 minutes).",
    )
    security_api_key_rate_limit_per_minute: int = Field(
        default=300,
        alias="SECURITY_API_KEY_RATE_LIMIT_PER_MINUTE",
        description=(
            "Per API-key / Bearer fingerprint Redis budget. "
            "0 disables the API-key bucket."
        ),
    )
    security_rate_limit_auto_ban_enabled: bool = Field(
        default=True,
        alias="SECURITY_RATE_LIMIT_AUTO_BAN_ENABLED",
        description="Auto-ban IP (and API key) when Redis rate limit is exceeded.",
    )
    security_telegram_ban_alerts_enabled: bool = Field(
        default=True,
        alias="SECURITY_TELEGRAM_BAN_ALERTS_ENABLED",
        description="Notify operator Telegram chat on auto-ban events.",
    )
    security_auto_block_threat_score: int = Field(
        default=5,
        alias="SECURITY_AUTO_BLOCK_THREAT_SCORE",
    )
    security_ip_block_ttl_seconds: int = Field(
        default=3600,
        alias="SECURITY_IP_BLOCK_TTL_SECONDS",
    )
    security_max_json_body_bytes: int = Field(
        default=1_048_576,
        alias="SECURITY_MAX_JSON_BODY_BYTES",
    )
    # Network-level payload gate (Content-Length + streamed body).
    security_payload_size_limiter_enabled: bool = Field(
        default=True,
        alias="SECURITY_PAYLOAD_SIZE_LIMITER_ENABLED",
    )
    security_max_payload_bytes: int = Field(
        default=5 * 1024 * 1024,
        alias="SECURITY_MAX_PAYLOAD_BYTES",
        description="Default max request body size (5 MiB).",
    )
    security_max_upload_payload_bytes: int = Field(
        default=10 * 1024 * 1024,
        alias="SECURITY_MAX_UPLOAD_PAYLOAD_BYTES",
        description="Max body size for image upload routes (10 MiB).",
    )
    # Security & Status admin dashboard (plan §62).
    security_status_rps_window_seconds: int = Field(
        default=5,
        alias="SECURITY_STATUS_RPS_WINDOW_SECONDS",
        description="Rolling window (seconds) for live RPS estimate.",
    )
    security_status_ws_interval_seconds: float = Field(
        default=2.0,
        alias="SECURITY_STATUS_WS_INTERVAL_SECONDS",
        description="WebSocket push interval for Security & Status snapshots.",
    )
    security_status_api_balance_cache_seconds: float = Field(
        default=60.0,
        alias="SECURITY_STATUS_API_BALANCE_CACHE_SECONDS",
        description="Cache TTL for Midjourney/Claude balance probes.",
    )
    security_status_api_probe_timeout_seconds: float = Field(
        default=5.0,
        alias="SECURITY_STATUS_API_PROBE_TIMEOUT_SECONDS",
    )
    # AI Cost Dashboard & Resource Analytics (plan §80).
    cost_daily_limit_usd: Decimal = Field(
        default=Decimal("50"),
        alias="COST_DAILY_LIMIT_USD",
        description="Telegram alert when today's AI spend exceeds this USD amount.",
    )
    cost_generation_spike_ratio: float = Field(
        default=2.0,
        alias="COST_GENERATION_SPIKE_RATIO",
        description="Alert when avg generation cost ≥ ratio × previous-week baseline.",
    )
    cost_latency_spike_ratio: float = Field(
        default=2.0,
        alias="COST_LATENCY_SPIKE_RATIO",
        description="Alert when avg API latency ≥ ratio × previous-week baseline.",
    )
    cost_latency_warn_ms: float = Field(
        default=15000.0,
        alias="COST_LATENCY_WARN_MS",
        description="Absolute avg latency threshold (ms) for slow-API alerts.",
    )
    cost_generation_sale_price_usd: Decimal = Field(
        default=Decimal("0"),
        alias="COST_GENERATION_SALE_PRICE_USD",
        description="Known sale price per generation for profitability (0 = unknown).",
    )
    cost_alerts_enabled: bool = Field(
        default=True,
        alias="COST_ALERTS_ENABLED",
    )
    cost_alert_cooldown_seconds: float = Field(
        default=3600.0,
        alias="COST_ALERT_COOLDOWN_SECONDS",
    )
    # Enterprise Audit Log & Event Tracking (plan §81).
    audit_log_enabled: bool = Field(
        default=True,
        alias="AUDIT_LOG_ENABLED",
        description="Persist enterprise audit events for user/admin/system actions.",
    )
    audit_log_retention_days: int = Field(
        default=90,
        alias="AUDIT_LOG_RETENTION_DAYS",
        description="Move audit rows older than this many days into audit_log_archives.",
    )
    audit_log_archive_enabled: bool = Field(
        default=True,
        alias="AUDIT_LOG_ARCHIVE_ENABLED",
    )
    audit_log_archive_batch_size: int = Field(
        default=1000,
        alias="AUDIT_LOG_ARCHIVE_BATCH_SIZE",
    )
    audit_log_archive_scan_seconds: float = Field(
        default=86400.0,
        alias="AUDIT_LOG_ARCHIVE_SCAN_SECONDS",
        description="Celery beat interval for automatic audit archival.",
    )
    audit_log_admin_access_enabled: bool = Field(
        default=True,
        alias="AUDIT_LOG_ADMIN_ACCESS_ENABLED",
        description="Auto-record admin.endpoint_access for /api/v1/admin hits.",
    )
    audit_log_structured_export_enabled: bool = Field(
        default=True,
        alias="AUDIT_LOG_STRUCTURED_EXPORT_ENABLED",
        description="Emit structured logs suitable for ELK / Grafana Loki ingestion.",
    )
    audit_request_id_header: str = Field(
        default="X-Request-Id",
        alias="AUDIT_REQUEST_ID_HEADER",
    )
    midjourney_balance_path: str = Field(
        default="",
        alias="MIDJOURNEY_BALANCE_PATH",
        description="Optional provider-relative path for balance JSON (e.g. /account).",
    )
    midjourney_balance_low_threshold: float = Field(
        default=5.0,
        alias="MIDJOURNEY_BALANCE_LOW_THRESHOLD",
        description="Balance at/below this value is reported as status=low.",
    )
    # Behavioral generation rate limit by visitorId (plan §35) → CAPTCHA_REQUIRED.
    security_behavioral_rate_enabled: bool = Field(
        default=True,
        alias="SECURITY_BEHAVIORAL_RATE_ENABLED",
    )
    security_generation_requests_per_minute: int = Field(
        default=8,
        alias="SECURITY_GENERATION_REQUESTS_PER_MINUTE",
    )
    security_generation_rate_window_seconds: int = Field(
        default=60,
        alias="SECURITY_GENERATION_RATE_WINDOW_SECONDS",
    )
    security_captcha_block_ttl_seconds: int = Field(
        default=900,
        alias="SECURITY_CAPTCHA_BLOCK_TTL_SECONDS",
    )
    captcha_provider: str = Field(
        default="auto",
        alias="CAPTCHA_PROVIDER",
        description="auto | turnstile | recaptcha",
    )
    turnstile_secret_key: SecretStr | None = Field(
        default=None,
        alias="TURNSTILE_SECRET_KEY",
    )
    recaptcha_secret_key: SecretStr | None = Field(
        default=None,
        alias="RECAPTCHA_SECRET_KEY",
    )
    captcha_verify_timeout_seconds: float = Field(
        default=8.0,
        alias="CAPTCHA_VERIFY_TIMEOUT_SECONDS",
    )
    captcha_bypass_when_unconfigured: bool = Field(
        default=False,
        alias="CAPTCHA_BYPASS_WHEN_UNCONFIGURED",
        description="Dev-only: accept tokens when provider secrets are missing.",
    )
    trusted_proxy_cidrs: str = Field(
        default="",
        alias="TRUSTED_PROXY_CIDRS",
    )

    # Cloudflare edge protection (DDoS + hide origin IP).
    cloudflare_enabled: bool = Field(default=False, alias="CLOUDFLARE_ENABLED")
    cloudflare_enforce_edge: bool = Field(
        default=False,
        alias="CLOUDFLARE_ENFORCE_EDGE",
    )
    cloudflare_trust_headers: bool = Field(
        default=True,
        alias="CLOUDFLARE_TRUST_HEADERS",
    )
    cloudflare_auto_ban_enabled: bool = Field(
        default=False,
        alias="CLOUDFLARE_AUTO_BAN_ENABLED",
    )
    cloudflare_api_token: SecretStr | None = Field(
        default=None,
        alias="CLOUDFLARE_API_TOKEN",
    )
    cloudflare_zone_id: str = Field(default="", alias="CLOUDFLARE_ZONE_ID")
    cloudflare_account_id: str = Field(default="", alias="CLOUDFLARE_ACCOUNT_ID")
    cloudflare_api_base_url: str = Field(
        default="https://api.cloudflare.com",
        alias="CLOUDFLARE_API_BASE_URL",
    )
    cloudflare_timeout_seconds: float = Field(
        default=10.0,
        alias="CLOUDFLARE_TIMEOUT_SECONDS",
    )

    # Private tunnel / VPN gateway (plan §37). Admin & SSH stay off the public net.
    vpn_gateway_cidrs: str = Field(
        default="10.8.0.0/24,10.7.0.0/24,fd42:42:42::/64",
        alias="VPN_GATEWAY_CIDRS",
        description="WireGuard / private CIDRs allowed during Dead Man's lockdown.",
    )
    ssh_allow_cidrs: str = Field(
        default="",
        alias="SSH_ALLOW_CIDRS",
        description="Comma-separated CIDRs permitted to reach SSH (host firewall).",
    )

    # Dead Man's Switch — DB password brute-force → lock external traffic (plan §37).
    dead_mans_switch_enabled: bool = Field(
        default=True,
        alias="DEAD_MANS_SWITCH_ENABLED",
    )
    dead_mans_switch_fail_threshold: int = Field(
        default=5,
        alias="DEAD_MANS_SWITCH_FAIL_THRESHOLD",
    )
    dead_mans_switch_window_seconds: int = Field(
        default=60,
        alias="DEAD_MANS_SWITCH_WINDOW_SECONDS",
    )
    dead_mans_switch_redis_key: str = Field(
        default="security:dead_mans_switch",
        alias="DEAD_MANS_SWITCH_REDIS_KEY",
    )
    dead_mans_switch_cloudflare_under_attack: bool = Field(
        default=True,
        alias="DEAD_MANS_SWITCH_CLOUDFLARE_UNDER_ATTACK",
    )
    dead_mans_switch_run_host_lockdown: bool = Field(
        default=False,
        alias="DEAD_MANS_SWITCH_RUN_HOST_LOCKDOWN",
        description="If true, invoke deploy/lockdown.sh on trigger (needs host mount).",
    )
    dead_mans_switch_lockdown_script: str = Field(
        default="/opt/ai-card-master/deploy/lockdown.sh",
        alias="DEAD_MANS_SWITCH_LOCKDOWN_SCRIPT",
    )
    dead_mans_switch_unlock_script: str = Field(
        default="/opt/ai-card-master/deploy/unlock.sh",
        alias="DEAD_MANS_SWITCH_UNLOCK_SCRIPT",
    )

    # Isolated admin microservice (AES-GCM encrypted service token).
    admin_panel_token_secret: SecretStr = Field(
        default=SecretStr(""),
        alias="ADMIN_PANEL_TOKEN_SECRET",
    )
    admin_panel_bind_host: str = Field(
        default="127.0.0.1",
        alias="ADMIN_PANEL_BIND_HOST",
    )
    admin_panel_port: int = Field(default=8100, alias="ADMIN_PANEL_PORT")
    admin_panel_cors_origins: str = Field(
        default="",
        alias="ADMIN_PANEL_CORS_ORIGINS",
    )

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
        description="Deprecated alias: prefer AI_CIRCUIT_BREAKER_FAILURE_THRESHOLD.",
    )
    midjourney_circuit_breaker_ttl_seconds: int = Field(
        default=180,
        alias="MIDJOURNEY_CIRCUIT_BREAKER_TTL_SECONDS",
        description="Deprecated alias: prefer AI_CIRCUIT_BREAKER_OPEN_DURATION_SECONDS.",
    )
    # Shared Circuit Breaker for Anthropic / Midjourney / Vision / SD.
    # 3 trip-worthy failures (429/500/502/503/timeout) in 60s → OPEN for 180s.
    ai_circuit_breaker_failure_threshold: int = Field(
        default=3,
        alias="AI_CIRCUIT_BREAKER_FAILURE_THRESHOLD",
    )
    ai_circuit_breaker_failure_window_seconds: int = Field(
        default=60,
        alias="AI_CIRCUIT_BREAKER_FAILURE_WINDOW_SECONDS",
    )
    ai_circuit_breaker_open_duration_seconds: int = Field(
        default=180,
        alias="AI_CIRCUIT_BREAKER_OPEN_DURATION_SECONDS",
    )
    ai_circuit_breaker_probe_lock_seconds: int = Field(
        default=30,
        alias="AI_CIRCUIT_BREAKER_PROBE_LOCK_SECONDS",
    )
    midjourney_generation_cost_usd: Decimal = Field(
        default=Decimal("0"),
        alias="MIDJOURNEY_GENERATION_COST_USD",
    )
    # Preferred neural geo-region; empty = no preference (plan §36).
    neural_preferred_region: str = Field(
        default="",
        alias="NEURAL_PREFERRED_REGION",
    )
    # Comma-separated failover order after preferred, e.g. eu-de,us-east
    neural_failover_regions: str = Field(
        default="",
        alias="NEURAL_FAILOVER_REGIONS",
    )
    # Redis key written by failover_watchdog / read by ai_engine provider pool.
    neural_active_region_redis_key: str = Field(
        default="geo:neural_active_region",
        alias="NEURAL_ACTIVE_REGION_REDIS_KEY",
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

    # 3D generation engine (Adapter Pattern — app/services/three_d).
    # Default "mock" keeps local/dev and CI free of Meshy/Tripo/RunPod deps.
    # Feature toggle: when False, /api/v1/3d routers and 3D Celery beat are off.
    enable_three_d: bool = Field(
        default=True,
        alias="ENABLE_THREE_D",
        description="Register /api/v1/3d HTTP+WS routers and 3D Celery workers/beat.",
    )
    three_d_provider: Literal["mock", "meshy", "tripo", "runpod"] = Field(
        default="mock",
        alias="THREE_D_PROVIDER",
    )
    three_d_mock_duration_seconds: float = Field(
        default=2.0,
        alias="THREE_D_MOCK_DURATION_SECONDS",
        description="Total simulated GPU/API latency for MockThreeDEngineAdapter.",
    )
    three_d_mock_queue_delay_seconds: float = Field(
        default=0.05,
        alias="THREE_D_MOCK_QUEUE_DELAY_SECONDS",
        description="Initial QUEUED dwell before PROCESSING in the mock adapter.",
    )
    three_d_mock_ticks_per_stage: int = Field(
        default=3,
        ge=1,
        alias="THREE_D_MOCK_TICKS_PER_STAGE",
        description="Progress ticks per mock stage (drafting_mesh / textures / baking).",
    )
    three_d_cost_coins: int = Field(
        default=5,
        ge=0,
        alias="THREE_D_COST_COINS",
        description=(
            "Legacy flat AI-coin hold when create_task is called without mode. "
            "API generate uses Pricing Matrix (draft=10 / standard=30 / hd=60)."
        ),
    )
    three_d_delivery_mode: Literal["poll", "webhook"] = Field(
        default="poll",
        alias="THREE_D_DELIVERY_MODE",
        description=(
            "poll: Celery worker polls the provider until terminal. "
            "webhook: worker submits then waits for provider callbacks / beat poll."
        ),
    )
    three_d_poll_interval_seconds: float = Field(
        default=2.0,
        gt=0,
        alias="THREE_D_POLL_INTERVAL_SECONDS",
    )
    three_d_poll_batch_size: int = Field(
        default=50,
        ge=1,
        alias="THREE_D_POLL_BATCH_SIZE",
    )
    three_d_poll_seconds: float = Field(
        default=5.0,
        gt=0,
        alias="THREE_D_POLL_SECONDS",
        description="Celery beat interval for three_d.poll_active_tasks.",
    )
    three_d_task_timeout_seconds: int = Field(
        default=1800,
        ge=30,
        alias="THREE_D_TASK_TIMEOUT_SECONDS",
    )
    three_d_max_download_bytes: int = Field(
        default=200 * 1024 * 1024,
        ge=1024,
        alias="THREE_D_MAX_DOWNLOAD_BYTES",
    )
    three_d_webhook_secret: SecretStr = Field(
        default=SecretStr(""),
        alias="THREE_D_WEBHOOK_SECRET",
        description="HMAC-SHA256 secret for /api/v1/3d/webhook/{provider_name}.",
    )
    three_d_progress_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        alias="THREE_D_PROGRESS_TTL_SECONDS",
    )
    three_d_ws_poll_interval_seconds: float = Field(
        default=1.0,
        gt=0,
        alias="THREE_D_WS_POLL_INTERVAL_SECONDS",
        description="Fallback WebSocket poll interval when Redis pub/sub is quiet.",
    )
    three_d_gpu_rental_provider: str = Field(
        default="stub",
        alias="THREE_D_GPU_RENTAL_PROVIDER",
        description="Provider label stored on gpu_rental_sessions (stub until wired).",
    )
    three_d_gpu_rental_instance_type: str = Field(
        default="gpu.stub.1x",
        alias="THREE_D_GPU_RENTAL_INSTANCE_TYPE",
        description="Default GPU instance type for rental start stub.",
    )
    three_d_gpu_rental_coins_per_minute: int = Field(
        default=1,
        ge=0,
        alias="THREE_D_GPU_RENTAL_COINS_PER_MINUTE",
        description="AI-coins charged per minute when a GPU rental session is stopped.",
    )

    # Redis, Celery, and durable generation workflow.
    # Cache/broker Redis uses volatile-lru + mandatory TTLs in compose.
    # Security Redis (rate limits, bans, CAPTCHA, DMS) uses noeviction.
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    redis_security_url: str | None = Field(
        default=None,
        alias="REDIS_SECURITY_URL",
        description=(
            "Dedicated Redis for security keys (noeviction). "
            "Falls back to REDIS_URL when unset (local/tests)."
        ),
    )
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

    # Signup trial (5 free coins) + multi-layer anti-abuse on /auth/register
    signup_trial_enabled: bool = Field(default=True, alias="SIGNUP_TRIAL_ENABLED")
    signup_trial_coins: int = Field(default=5, alias="SIGNUP_TRIAL_COINS")
    signup_trial_subnet_max_accounts: int = Field(
        default=3,
        alias="SIGNUP_TRIAL_SUBNET_MAX_ACCOUNTS",
        description="Max auto-trial grants per IPv4 /24 (or IPv6 /64) within the TTL window.",
    )
    signup_trial_subnet_ttl_seconds: int = Field(
        default=86_400,
        alias="SIGNUP_TRIAL_SUBNET_TTL_SECONDS",
    )
    signup_trial_fingerprint_ttl_seconds: int = Field(
        default=90 * 24 * 3600,
        alias="SIGNUP_TRIAL_FINGERPRINT_TTL_SECONDS",
        description="Redis TTL for exhausted device fingerprint hashes (Postgres is durable).",
    )
    signup_trial_proxy_check_enabled: bool = Field(
        default=True,
        alias="SIGNUP_TRIAL_PROXY_CHECK_ENABLED",
    )
    signup_trial_ip_api_enabled: bool = Field(
        default=True,
        alias="SIGNUP_TRIAL_IP_API_ENABLED",
        description="Optional open ip-api.com proxy/hosting probe (non-commercial).",
    )
    signup_trial_proxy_timeout_seconds: float = Field(
        default=2.5,
        alias="SIGNUP_TRIAL_PROXY_TIMEOUT_SECONDS",
    )

    # Silent ban (shadow restrictions for fingerprint / subnet abusers)
    silent_ban_enabled: bool = Field(
        default=True,
        alias="SILENT_BAN_ENABLED",
        description="Route flagged users to shadow generation + tight IP rate limits.",
    )
    silent_ban_flagged_ip_ttl_seconds: int = Field(
        default=90 * 24 * 3600,
        alias="SILENT_BAN_FLAGGED_IP_TTL_SECONDS",
        description="Redis TTL for flagged client IPs (1 req / 5 min bucket).",
    )
    silent_ban_flagged_ip_rate_limit: int = Field(
        default=1,
        alias="SILENT_BAN_FLAGGED_IP_RATE_LIMIT",
        description="Max requests per window for silently flagged IPs.",
    )
    silent_ban_flagged_ip_window_seconds: int = Field(
        default=300,
        alias="SILENT_BAN_FLAGGED_IP_WINDOW_SECONDS",
        description="Rate-limit window for silently flagged IPs (default 5 minutes).",
    )
    silent_ban_shadow_delay_min_seconds: int = Field(
        default=45,
        alias="SILENT_BAN_SHADOW_DELAY_MIN_SECONDS",
        description="Min fake load delay before shadow generation fails.",
    )
    silent_ban_shadow_delay_max_seconds: int = Field(
        default=180,
        alias="SILENT_BAN_SHADOW_DELAY_MAX_SECONDS",
        description="Max fake load delay before shadow generation fails.",
    )
    silent_ban_emulate_http_timeout: bool = Field(
        default=False,
        alias="SILENT_BAN_EMULATE_HTTP_TIMEOUT",
        description=(
            "When true, flagged generation requests sleep a random inflated "
            "timeout and return HTTP 504 instead of enqueueing work."
        ),
    )

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

    # Zero-Knowledge source retention (heavy ZIP + originals → deleted after N hours)
    source_retention_hours: int = Field(default=24, alias="SOURCE_RETENTION_HOURS")
    source_retention_scan_seconds: float = Field(
        default=900.0,
        alias="SOURCE_RETENTION_SCAN_SECONDS",
    )
    source_retention_batch_size: int = Field(
        default=200,
        alias="SOURCE_RETENTION_BATCH_SIZE",
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

    # Custom Brand LoRA (enterprise style training)
    brand_lora_min_references: int = Field(
        default=20,
        alias="BRAND_LORA_MIN_REFERENCES",
    )
    brand_lora_max_references: int = Field(
        default=30,
        alias="BRAND_LORA_MAX_REFERENCES",
    )
    brand_lora_training_cost_coins: int = Field(
        default=50,
        alias="BRAND_LORA_TRAINING_COST_COINS",
    )
    brand_lora_poll_seconds: float = Field(
        default=20.0,
        alias="BRAND_LORA_POLL_SECONDS",
    )
    brand_lora_poll_batch_size: int = Field(
        default=50,
        alias="BRAND_LORA_POLL_BATCH_SIZE",
    )
    brand_lora_auto_activate: bool = Field(
        default=True,
        alias="BRAND_LORA_AUTO_ACTIVATE",
    )
    brand_lora_prefer_replicate: bool = Field(
        default=True,
        alias="BRAND_LORA_PREFER_REPLICATE",
    )

    # Plan §58 — BrandDNA learned from successful seller generations.
    brand_dna_enabled: bool = Field(
        default=True,
        alias="BRAND_DNA_ENABLED",
    )
    brand_dna_sample_limit: int = Field(
        default=25,
        alias="BRAND_DNA_SAMPLE_LIMIT",
    )
    brand_dna_min_samples: int = Field(
        default=1,
        alias="BRAND_DNA_MIN_SAMPLES",
    )
    replicate_api_token: SecretStr | None = Field(
        default=None,
        alias="REPLICATE_API_TOKEN",
    )
    replicate_api_base_url: str = Field(
        default="https://api.replicate.com/v1",
        alias="REPLICATE_API_BASE_URL",
    )
    replicate_timeout_seconds: float = Field(
        default=60.0,
        alias="REPLICATE_TIMEOUT_SECONDS",
    )
    replicate_lora_destination: str = Field(
        default="",
        alias="REPLICATE_LORA_DESTINATION",
    )
    replicate_lora_dataset_url_override: str = Field(
        default="",
        alias="REPLICATE_LORA_DATASET_URL_OVERRIDE",
    )
    replicate_lora_trainer_model: str = Field(
        default="ostris/flux-dev-lora-trainer",
        alias="REPLICATE_LORA_TRAINER_MODEL",
    )
    replicate_lora_trainer_version: str = Field(
        default="latest",
        alias="REPLICATE_LORA_TRAINER_VERSION",
    )
    replicate_lora_training_steps: int = Field(
        default=1000,
        alias="REPLICATE_LORA_TRAINING_STEPS",
    )
    replicate_lora_use_model_trainings_endpoint: bool = Field(
        default=False,
        alias="REPLICATE_LORA_USE_MODEL_TRAININGS_ENDPOINT",
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

    # Plan §59 — Fail-Safe Export sandbox (photo weight, forbidden words, category).
    fail_safe_export_enabled: bool = Field(
        default=True,
        alias="FAIL_SAFE_EXPORT_ENABLED",
    )
    fail_safe_export_claude_fix_enabled: bool = Field(
        default=True,
        alias="FAIL_SAFE_EXPORT_CLAUDE_FIX_ENABLED",
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
    # Keyset pagination batch when listing active SKUs (id > last); keep 200–500.
    stock_parser_keyset_batch_size: int = Field(
        default=300,
        alias="STOCK_PARSER_KEYSET_BATCH_SIZE",
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

    # Plan §57 — Zero-Hallucination OCR ↔ description dual check.
    zero_hallucination_enabled: bool = Field(
        default=True,
        alias="ZERO_HALLUCINATION_ENABLED",
    )
    zero_hallucination_max_vision_images: int = Field(
        default=5,
        alias="ZERO_HALLUCINATION_MAX_VISION_IMAGES",
    )

    smart_inpainting_edge_pass_enabled: bool = Field(
        default=False,
        alias="SMART_INPAINTING_EDGE_PASS_ENABLED",
    )
    style_cache_ttl_seconds: int = Field(default=86400, alias="STYLE_CACHE_TTL_SECONDS")
    style_cache_version: str = Field(default="v1", alias="STYLE_CACHE_VERSION")

    # Highload caches (plan §16): history pages + static catalog responses.
    generation_history_cache_ttl_seconds: int = Field(
        default=30,
        alias="GENERATION_HISTORY_CACHE_TTL_SECONDS",
    )
    static_cache_ttl_seconds: int = Field(
        default=3600,
        alias="STATIC_CACHE_TTL_SECONDS",
    )
    generation_status_cache_ttl_seconds: int = Field(
        default=5,
        alias="GENERATION_STATUS_CACHE_TTL_SECONDS",
    )
    generation_status_terminal_cache_ttl_seconds: int = Field(
        default=60,
        alias="GENERATION_STATUS_TERMINAL_CACHE_TTL_SECONDS",
    )

    # Production pool / logging knobs.
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    db_pool_size: int = Field(default=20, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_pool_timeout_seconds: int = Field(default=30, alias="DB_POOL_TIMEOUT_SECONDS")
    db_pool_recycle_seconds: int = Field(default=1800, alias="DB_POOL_RECYCLE_SECONDS")
    telegram_error_logging_enabled: bool = Field(
        default=True,
        alias="TELEGRAM_ERROR_LOGGING_ENABLED",
    )
    telegram_error_alert_cooldown_seconds: int = Field(
        default=60,
        alias="TELEGRAM_ERROR_ALERT_COOLDOWN_SECONDS",
    )

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
    yookassa_max_retries: int = Field(default=2, alias="YOOKASSA_MAX_RETRIES")
    yookassa_base_retry_delay_seconds: float = Field(
        default=0.5,
        alias="YOOKASSA_BASE_RETRY_DELAY_SECONDS",
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

    # Sentry error tracking (optional; disabled when DSN is empty).
    sentry_dsn: str | None = Field(default=None, alias="SENTRY_DSN")
    sentry_release: str | None = Field(default=None, alias="SENTRY_RELEASE")
    sentry_traces_sample_rate: float = Field(
        default=0.0,
        alias="SENTRY_TRACES_SAMPLE_RATE",
    )
    sentry_profiles_sample_rate: float = Field(
        default=0.0,
        alias="SENTRY_PROFILES_SAMPLE_RATE",
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
    # Alternate Anthropic-compatible proxy used when the primary circuit is OPEN.
    claude_fallback_base_url: str = Field(
        default="",
        alias="CLAUDE_FALLBACK_BASE_URL",
    )
    claude_47_model: str = Field(
        default="claude-opus-4-7",
        alias="CLAUDE_47_MODEL",
    )
    # Plan §55 — cheap model for simple text analytics (Smart Reasoning Routing).
    # Also used as Circuit Breaker fallback when Opus/Sonnet primary is OPEN.
    claude_35_haiku_model: str = Field(
        default="claude-3-5-haiku-20241022",
        alias="CLAUDE_35_HAIKU_MODEL",
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
        default=86400,
        alias="CLAUDE_47_STAGE_CACHE_TTL_SECONDS",
    )
    # Plan §55 — content-addressed Claude analytics cache (24h → ~30% API savings).
    claude_analytics_cache_ttl_seconds: int = Field(
        default=86400,
        alias="CLAUDE_ANALYTICS_CACHE_TTL_SECONDS",
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

    # Plan §69 — AI Token & Resource Governor (Economy 2.0)
    token_governor_enabled: bool = Field(
        default=True,
        alias="TOKEN_GOVERNOR_ENABLED",
    )
    token_governor_soft_input_tokens: int = Field(
        default=6_000,
        alias="TOKEN_GOVERNOR_SOFT_INPUT_TOKENS",
    )
    token_governor_hard_input_tokens: int = Field(
        default=24_000,
        alias="TOKEN_GOVERNOR_HARD_INPUT_TOKENS",
    )
    token_governor_always_semantic_filter: bool = Field(
        default=True,
        alias="TOKEN_GOVERNOR_ALWAYS_SEMANTIC_FILTER",
    )
    token_governor_prefer_local: bool = Field(
        default=True,
        alias="TOKEN_GOVERNOR_PREFER_LOCAL",
    )
    token_governor_snapshot_ttl_seconds: int = Field(
        default=604_800,
        alias="TOKEN_GOVERNOR_SNAPSHOT_TTL_SECONDS",
    )
    # Local LLM (Ollama / Llama 3) for routine classification & text prep.
    ollama_enabled: bool = Field(default=False, alias="OLLAMA_ENABLED")
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434",
        alias="OLLAMA_BASE_URL",
    )
    ollama_model: str = Field(
        default="llama3",
        alias="OLLAMA_MODEL",
    )
    ollama_timeout_seconds: float = Field(
        default=60.0,
        alias="OLLAMA_TIMEOUT_SECONDS",
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
        "ai_circuit_breaker_failure_threshold",
        "ai_circuit_breaker_failure_window_seconds",
        "ai_circuit_breaker_open_duration_seconds",
        "ai_circuit_breaker_probe_lock_seconds",
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
        "source_retention_hours",
        "source_retention_batch_size",
        "audit_log_retention_days",
        "audit_log_archive_batch_size",
        "bulk_generation_max_products",
        "bulk_generation_max_zip_bytes",
        "bulk_generation_poll_batch_size",
        "smart_variant_max_colors",
        "smart_variant_poll_batch_size",
        "brand_lora_min_references",
        "brand_lora_max_references",
        "brand_lora_training_cost_coins",
        "brand_lora_poll_batch_size",
        "brand_dna_sample_limit",
        "brand_dna_min_samples",
        "replicate_lora_training_steps",
        "generation_fast_cost_coins",
        "generation_hd_face_fix_cost_coins",
        "style_cache_ttl_seconds",
        "generation_history_cache_ttl_seconds",
        "static_cache_ttl_seconds",
        "generation_status_cache_ttl_seconds",
        "generation_status_terminal_cache_ttl_seconds",
        "db_pool_size",
        "db_max_overflow",
        "db_pool_timeout_seconds",
        "db_pool_recycle_seconds",
        "telegram_error_alert_cooldown_seconds",
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
        "claude_analytics_cache_ttl_seconds",
        "claude_47_processing_timeout_seconds",
        "claude_47_outbox_batch_size",
        "claude_47_recovery_batch_size",
        "token_governor_soft_input_tokens",
        "token_governor_hard_input_tokens",
        "token_governor_snapshot_ttl_seconds",
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
        "stock_parser_keyset_batch_size",
        "competitor_audit_redis_ttl_seconds",
        "competitor_audit_max_reviews",
        "competitor_audit_max_vision_images",
        "zero_hallucination_max_vision_images",
        "security_rate_limit_per_minute",
        "slowapi_global_per_minute",
        "slowapi_auth_per_minute",
        "slowapi_generations_per_minute",
        "slowapi_three_d_per_minute",
        "idempotency_processing_ttl_seconds",
        "idempotency_response_ttl_seconds",
        "security_auto_block_threat_score",
        "security_ip_block_ttl_seconds",
        "security_max_json_body_bytes",
        "security_max_payload_bytes",
        "security_max_upload_payload_bytes",
        "security_generation_requests_per_minute",
        "security_generation_rate_window_seconds",
        "security_captcha_block_ttl_seconds",
        "security_status_rps_window_seconds",
        "admin_panel_port",
        "dead_mans_switch_fail_threshold",
        "dead_mans_switch_window_seconds",
    )
    @classmethod
    def validate_generation_positive_ints(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Generation and queue numeric settings must be positive.")
        return value

    @field_validator("security_api_key_rate_limit_per_minute")
    @classmethod
    def validate_api_key_rate_limit_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError(
                "SECURITY_API_KEY_RATE_LIMIT_PER_MINUTE must be >= 0 (0 disables)."
            )
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
        "source_retention_scan_seconds",
        "audit_log_archive_scan_seconds",
        "bulk_generation_poll_seconds",
        "smart_variant_poll_seconds",
        "brand_lora_poll_seconds",
        "replicate_timeout_seconds",
        "claude_47_timeout_seconds",
        "claude_47_base_retry_delay_seconds",
        "ollama_timeout_seconds",
        "yookassa_timeout_seconds",
        "yookassa_base_retry_delay_seconds",
        "eye_of_god_image_timeout_seconds",
        "cloudflare_timeout_seconds",
        "captcha_verify_timeout_seconds",
        "security_status_ws_interval_seconds",
        "security_status_api_probe_timeout_seconds",
    )
    @classmethod
    def validate_positive_floats(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Timeout/retry settings must be positive.")
        return value

    @field_validator(
        "security_status_api_balance_cache_seconds",
        "midjourney_balance_low_threshold",
        "cost_latency_warn_ms",
        "cost_alert_cooldown_seconds",
    )
    @classmethod
    def validate_non_negative_security_status_floats(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Security status numeric settings must be >= 0.")
        return value

    @field_validator("cost_generation_spike_ratio", "cost_latency_spike_ratio")
    @classmethod
    def validate_cost_spike_ratios(cls, value: float) -> float:
        if value < 1.0:
            raise ValueError("Cost spike ratios must be >= 1.0.")
        return value

    @field_validator("captcha_provider")
    @classmethod
    def validate_captcha_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"auto", "turnstile", "recaptcha"}:
            raise ValueError("CAPTCHA_PROVIDER must be auto, turnstile, or recaptcha.")
        return normalized

    @field_validator("three_d_delivery_mode", mode="before")
    @classmethod
    def normalize_three_d_delivery_mode(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("three_d_provider", mode="before")
    @classmethod
    def normalize_three_d_provider(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator(
        "three_d_mock_duration_seconds",
        "three_d_mock_queue_delay_seconds",
    )
    @classmethod
    def validate_three_d_mock_delays(cls, value: float) -> float:
        if value < 0:
            raise ValueError("THREE_D mock delay settings must be >= 0.")
        return value

    @field_validator("claude_47_max_retries", "yookassa_max_retries")
    @classmethod
    def validate_claude_retries(cls, value: int) -> int:
        if value < 0:
            raise ValueError("Retry count cannot be negative.")
        return value

    @field_validator("claude_47_temperature")
    @classmethod
    def validate_claude_temperature(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("CLAUDE_47_TEMPERATURE must be in [0, 1].")
        return value

    @field_validator("sentry_traces_sample_rate", "sentry_profiles_sample_rate")
    @classmethod
    def validate_sentry_sample_rates(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("Sentry sample rates must be in [0, 1].")
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
        "cost_daily_limit_usd",
        "cost_generation_sale_price_usd",
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

    @field_validator("redis_security_url")
    @classmethod
    def validate_redis_security_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if not normalized.startswith(("redis://", "rediss://")):
            raise ValueError(
                "REDIS_SECURITY_URL must start with redis:// or rediss://."
            )
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

    @model_validator(mode="after")
    def validate_production_security_invariants(self) -> "Settings":
        """Fail-fast production gates for captcha bypass, admin secret, pepper."""

        if self.app_env != "production":
            return self

        if self.captcha_bypass_when_unconfigured:
            raise ValueError(
                "CAPTCHA_BYPASS_WHEN_UNCONFIGURED must be false in production."
            )

        admin_secret = self.admin_panel_token_secret.get_secret_value().strip()
        jwt_secret = self.jwt_secret_key.get_secret_value()
        if not admin_secret:
            raise ValueError(
                "ADMIN_PANEL_TOKEN_SECRET must be set explicitly in production "
                "(JWT_SECRET_KEY fallback is forbidden)."
            )
        if admin_secret == jwt_secret:
            raise ValueError(
                "ADMIN_PANEL_TOKEN_SECRET must not equal JWT_SECRET_KEY in production."
            )
        if len(admin_secret) < 32:
            raise ValueError(
                "ADMIN_PANEL_TOKEN_SECRET must contain at least 32 characters "
                "in production."
            )

        pepper = self.password_pepper.get_secret_value()
        if len(pepper) < 32:
            raise ValueError(
                "PASSWORD_PEPPER must contain at least 32 characters in production."
            )

        origins = self.cors_origins_list
        if not origins:
            raise ValueError(
                "ALLOWED_ORIGINS (or CORS_ORIGINS) must list explicit frontend "
                "origins in production."
            )
        if any(origin == "*" for origin in origins):
            raise ValueError(
                "Wildcard CORS origin (*) is forbidden in production."
            )
        if any(method.strip() == "*" for method in self.cors_allow_methods.split(",")):
            raise ValueError(
                "CORS_ALLOW_METHODS must not contain '*' in production."
            )
        if any(header.strip() == "*" for header in self.cors_allow_headers.split(",")):
            raise ValueError(
                "CORS_ALLOW_HEADERS must not contain '*' in production."
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
    def cors_allow_methods_list(self) -> list[str]:
        """Parse allowed CORS HTTP methods (no wildcards in production)."""

        return [
            method.strip().upper()
            for method in self.cors_allow_methods.split(",")
            if method.strip()
        ]

    @property
    def cors_allow_headers_list(self) -> list[str]:
        """Parse allowed CORS request headers."""

        return [
            header.strip()
            for header in self.cors_allow_headers.split(",")
            if header.strip()
        ]

    @property
    def cors_expose_headers_list(self) -> list[str]:
        """Parse CORS response headers exposed to the browser."""

        return [
            header.strip()
            for header in self.cors_expose_headers.split(",")
            if header.strip()
        ]

    @property
    def effective_celery_broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def effective_redis_security_url(self) -> str:
        """Security Redis URL; defaults to REDIS_URL for single-instance local/dev."""

        if self.redis_security_url:
            return self.redis_security_url
        return self.redis_url

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

    @property
    def neural_failover_regions_list(self) -> tuple[str, ...]:
        """Ordered neural geo failover chain after the preferred region (§36)."""

        return tuple(
            region.strip().lower()
            for region in self.neural_failover_regions.split(",")
            if region.strip()
        )

    @property
    def admin_panel_cors_origins_list(self) -> list[str]:
        """Parse admin-microservice CORS origins (empty = no browser CORS)."""

        return [
            origin.strip()
            for origin in self.admin_panel_cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def effective_admin_panel_token_secret(self) -> str:
        """Admin panel secret; JWT fallback is allowed only outside production."""

        explicit = self.admin_panel_token_secret.get_secret_value().strip()
        if explicit:
            return explicit
        if self.app_env == "production":
            raise RuntimeError(
                "ADMIN_PANEL_TOKEN_SECRET must be set explicitly in production; "
                "JWT_SECRET_KEY fallback is forbidden."
            )
        return self.jwt_secret_key.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get a cached settings instance."""

    return Settings()  # type: ignore[call-arg]
