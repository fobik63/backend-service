"""Unit tests for Dead Man's Switch + private tunnel helpers (plan §37)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.dead_mans_switch_middleware import DeadMansSwitchMiddleware
from app.services.dead_mans_switch import (
    AuthFailureEvent,
    DeadMansSwitchService,
    extract_source_ip,
    looks_like_db_auth_failure,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = BACKEND_ROOT / "deploy"


def _load(name: str, filename: str):
    path = DEPLOY_DIR / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_looks_like_db_auth_failure() -> None:
    assert looks_like_db_auth_failure(
        'FATAL:  password authentication failed for user "ai_card"'
    )
    assert looks_like_db_auth_failure(
        "no pg_hba.conf entry for host \"203.0.113.9\""
    )
    assert not looks_like_db_auth_failure("LOG:  checkpoint starting")


def test_extract_source_ip_from_postgres_line() -> None:
    line = (
        'FATAL:  password authentication failed for user "ai_card" '
        "Connection matched pg_hba.conf line 99 for host 203.0.113.44"
    )
    # Prefer first parseable non-loopback IP in the line
    assert extract_source_ip(
        'connection for user "x" from 198.51.100.7 port 54321 failed'
    ) == "198.51.100.7"
    assert "203.0.113" in extract_source_ip(line) or extract_source_ip(line) == "unknown"


def test_vpn_allowlist() -> None:
    settings = SimpleNamespace(vpn_gateway_cidrs="10.8.0.0/24,fd42::/64")
    svc = DeadMansSwitchService(settings=settings)  # type: ignore[arg-type]
    assert svc.peer_is_vpn_allowlisted("10.8.0.5") is True
    assert svc.peer_is_vpn_allowlisted("127.0.0.1") is True
    assert svc.peer_is_vpn_allowlisted("8.8.8.8") is False


@pytest.mark.asyncio
async def test_record_auth_failure_triggers_at_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store: dict[str, str] = {}
    counters: dict[str, int] = {}

    class _FakeRedis:
        async def incr(self, key: str) -> int:
            counters[key] = counters.get(key, 0) + 1
            return counters[key]

        async def expire(self, key: str, _ttl: int) -> bool:
            return True

        async def get(self, key: str) -> str | None:
            return store.get(key)

        async def set(self, key: str, value: str, ex: int | None = None) -> bool:
            store[key] = value
            return True

        async def delete(self, *keys: str) -> int:
            removed = 0
            for key in keys:
                if key in store:
                    del store[key]
                    removed += 1
            return removed

    settings = SimpleNamespace(
        dead_mans_switch_enabled=True,
        dead_mans_switch_fail_threshold=3,
        dead_mans_switch_window_seconds=60,
        dead_mans_switch_redis_key="security:dead_mans_switch",
        dead_mans_switch_cloudflare_under_attack=False,
        dead_mans_switch_run_host_lockdown=False,
        dead_mans_switch_lockdown_script="",
        dead_mans_switch_unlock_script="",
        vpn_gateway_cidrs="10.8.0.0/24",
        cloudflare_enabled=False,
    )

    monkeypatch.setattr(
        "app.services.dead_mans_switch.get_security_redis_client",
        lambda: _FakeRedis(),
    )

    async def _no_tg(_: str) -> None:
        return None

    monkeypatch.setattr(
        "app.services.dead_mans_switch.send_operator_telegram",
        _no_tg,
    )

    svc = DeadMansSwitchService(settings=settings)  # type: ignore[arg-type]
    event = AuthFailureEvent(source_ip="203.0.113.9", raw_line="password authentication failed")

    state = await svc.record_auth_failure(event)
    assert state.active is False
    state = await svc.record_auth_failure(event)
    assert state.active is False
    state = await svc.record_auth_failure(event)
    assert state.active is True
    assert state.fail_count == 3
    assert "brute-force" in (state.reason or "").lower() or "password" in (
        state.reason or ""
    ).lower()


@pytest.mark.asyncio
async def test_middleware_blocks_public_when_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeDms:
        async def is_active(self) -> bool:
            return True

        def peer_is_vpn_allowlisted(self, peer_ip: str | None) -> bool:
            return peer_ip in {"10.8.0.2", "127.0.0.1"}

        async def get_state(self):
            return SimpleNamespace(triggered_at="2026-08-07T00:00:00+00:00")

    monkeypatch.setattr(
        "app.core.dead_mans_switch_middleware.get_dead_mans_switch",
        lambda: _FakeDms(),
    )
    monkeypatch.setattr(
        "app.core.dead_mans_switch_middleware.get_settings",
        lambda: SimpleNamespace(dead_mans_switch_enabled=True),
    )

    app = FastAPI()
    app.add_middleware(DeadMansSwitchMiddleware)

    @app.get("/api/v1/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "1"}

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app)
    blocked = client.get("/api/v1/ping")
    assert blocked.status_code == 503
    assert blocked.json()["code"] == "DEAD_MANS_SWITCH_ACTIVE"

    live = client.get("/health/live")
    assert live.status_code == 200


def test_watchdog_detects_patterns() -> None:
    watchdog = _load("dead_mans_watchdog_mod", "dead_mans_watchdog.py")
    assert watchdog.looks_like_auth_failure(
        "FATAL: password authentication failed for user \"ai_card\""
    )
    assert not watchdog.looks_like_auth_failure("LOG: duration: 1.2 ms")


def test_private_tunnel_artifacts_exist() -> None:
    assert (DEPLOY_DIR / "PRIVATE_TUNNEL.md").is_file()
    assert (DEPLOY_DIR / "harden_host.sh").is_file()
    assert (DEPLOY_DIR / "lockdown.sh").is_file()
    assert (DEPLOY_DIR / "unlock.sh").is_file()
    assert (DEPLOY_DIR / "docker-compose.tunnel.yml").is_file()
    tunnel = (DEPLOY_DIR / "docker-compose.tunnel.yml").read_text(encoding="utf-8")
    assert "cloudflared" in tunnel
    assert "CLOUDFLARE_TUNNEL_TOKEN" in tunnel
