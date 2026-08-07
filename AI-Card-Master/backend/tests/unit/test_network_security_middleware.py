"""Unit tests for network-level security headers, payload limits, and CORS."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.payload_size_limiter_middleware import (
    PayloadSizeLimiterMiddleware,
    _resolve_max_bytes,
)
from app.core.security_headers import SECURITY_HEADER_VALUES, apply_security_headers
from app.core.security_headers_middleware import SecurityHeadersMiddleware
from starlette.responses import Response


def _settings(**overrides: Any) -> Settings:
    data: dict[str, Any] = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/test",
        "JWT_SECRET_KEY": "j" * 64,
        "APP_ENV": "development",
    }
    data.update(overrides)
    return Settings(**data)


def test_apply_security_headers_sets_required_values() -> None:
    response = Response(content=b"ok")
    apply_security_headers(response, path="/api/v1/health")
    for header, value in SECURITY_HEADER_VALUES.items():
        if header == "Permissions-Policy":
            continue
        assert response.headers[header] == value
    assert response.headers["Strict-Transport-Security"] == (
        "max-age=31536000; includeSubDomains"
    )
    assert response.headers["Content-Security-Policy"] == "default-src 'self'"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_security_headers_middleware_on_all_responses() -> None:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Content-Security-Policy"] == "default-src 'self'"


def test_payload_limiter_rejects_oversized_content_length(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        SECURITY_MAX_PAYLOAD_BYTES=1024,
        SECURITY_MAX_UPLOAD_PAYLOAD_BYTES=2048,
    )
    monkeypatch.setattr(
        "app.core.payload_size_limiter_middleware.get_settings",
        lambda: settings,
    )

    app = FastAPI()
    app.add_middleware(PayloadSizeLimiterMiddleware)

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        body = await request.body()
        return {"n": len(body)}

    client = TestClient(app)
    response = client.post(
        "/echo",
        content=b"x" * 64,
        headers={"Content-Length": "99999"},
    )
    assert response.status_code == 413
    assert response.json()["detail"] == "Payload Too Large"


def test_payload_limiter_rejects_oversized_actual_body(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        SECURITY_MAX_PAYLOAD_BYTES=128,
        SECURITY_MAX_UPLOAD_PAYLOAD_BYTES=256,
    )
    monkeypatch.setattr(
        "app.core.payload_size_limiter_middleware.get_settings",
        lambda: settings,
    )

    app = FastAPI()
    app.add_middleware(PayloadSizeLimiterMiddleware)

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        body = await request.body()
        return {"n": len(body)}

    client = TestClient(app)
    response = client.post("/echo", content=b"y" * 200)
    assert response.status_code == 413


def test_payload_limiter_allows_body_within_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(SECURITY_MAX_PAYLOAD_BYTES=1024)
    monkeypatch.setattr(
        "app.core.payload_size_limiter_middleware.get_settings",
        lambda: settings,
    )

    app = FastAPI()
    app.add_middleware(PayloadSizeLimiterMiddleware)

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        body = await request.body()
        return {"n": len(body)}

    client = TestClient(app)
    payload = b"z" * 100
    response = client.post("/echo", content=payload)
    assert response.status_code == 200
    assert response.json()["n"] == 100


def test_resolve_max_bytes_image_upload_vs_default() -> None:
    settings = _settings(
        SECURITY_MAX_PAYLOAD_BYTES=5 * 1024 * 1024,
        SECURITY_MAX_UPLOAD_PAYLOAD_BYTES=10 * 1024 * 1024,
    )
    assert _resolve_max_bytes("/api/v1/auth/login", settings) == 5 * 1024 * 1024
    assert _resolve_max_bytes("/api/v1/images/upload", settings) == 10 * 1024 * 1024


def test_allowed_origins_alias_preferred() -> None:
    settings = _settings(
        ALLOWED_ORIGINS="https://app.example.com,https://admin.example.com",
    )
    assert settings.cors_origins_list == [
        "https://app.example.com",
        "https://admin.example.com",
    ]


def test_cors_origins_legacy_alias_still_works() -> None:
    settings = _settings(CORS_ORIGINS="https://legacy.example.com")
    assert settings.cors_origins_list == ["https://legacy.example.com"]


def test_cors_methods_and_headers_are_explicit() -> None:
    settings = _settings()
    assert "*" not in settings.cors_allow_methods_list
    assert "*" not in settings.cors_allow_headers_list
    assert "GET" in settings.cors_allow_methods_list
    assert "Authorization" in settings.cors_allow_headers_list


def test_production_rejects_wildcard_cors_origin() -> None:
    with pytest.raises(ValidationError, match="Wildcard CORS origin"):
        _settings(
            APP_ENV="production",
            ADMIN_PANEL_TOKEN_SECRET="a" * 32,
            PASSWORD_PEPPER="p" * 32,
            CAPTCHA_BYPASS_WHEN_UNCONFIGURED=False,
            ALLOWED_ORIGINS="*",
        )


def test_production_rejects_wildcard_cors_methods() -> None:
    with pytest.raises(ValidationError, match="CORS_ALLOW_METHODS"):
        _settings(
            APP_ENV="production",
            ADMIN_PANEL_TOKEN_SECRET="a" * 32,
            PASSWORD_PEPPER="p" * 32,
            CAPTCHA_BYPASS_WHEN_UNCONFIGURED=False,
            ALLOWED_ORIGINS="https://app.example.com",
            CORS_ALLOW_METHODS="*",
        )
