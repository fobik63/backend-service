"""Unit tests for geo failover watchdog and neural region ordering (plan §36)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

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


failover = _load("geo_failover_watchdog", "failover_watchdog.py")


def test_detection_window_within_30s_slo() -> None:
    cfg = failover.FailoverConfig(
        primary_health_url="http://primary/health/ready",
        secondary_health_url="http://secondary/health/ready",
        primary_origin_ip="1.1.1.1",
        secondary_origin_ip="2.2.2.2",
        dns_record_name="api",
        dns_record_type="A",
        cloudflare_zone_id="zone",
        cloudflare_api_token="token",
        cloudflare_api_base="https://api.cloudflare.com",
        poll_seconds=5.0,
        fail_threshold=3,
        recover_threshold=6,
        probe_timeout_seconds=3.0,
        auto_failback=False,
        telegram_bot_token="",
        telegram_chat_id="",
        dry_run=True,
    )
    assert failover.max_detection_seconds(cfg) <= 30.0


def test_failover_after_fail_threshold() -> None:
    state = failover.WatchState()
    for _ in range(2):
        assert (
            failover.decide_action(
                state,
                primary_ok=False,
                secondary_ok=True,
                fail_threshold=3,
                recover_threshold=6,
                auto_failback=False,
            )
            == "stay"
        )
    assert (
        failover.decide_action(
            state,
            primary_ok=False,
            secondary_ok=True,
            fail_threshold=3,
            recover_threshold=6,
            auto_failback=False,
        )
        == "failover_to_secondary"
    )


def test_no_failover_when_secondary_also_down() -> None:
    state = failover.WatchState()
    for _ in range(3):
        decision = failover.decide_action(
            state,
            primary_ok=False,
            secondary_ok=False,
            fail_threshold=3,
            recover_threshold=6,
            auto_failback=False,
        )
    assert decision == "stay"


def test_auto_failback_requires_recover_threshold() -> None:
    state = failover.WatchState(active=failover.SiteRole.SECONDARY)
    for _ in range(5):
        assert (
            failover.decide_action(
                state,
                primary_ok=True,
                secondary_ok=True,
                fail_threshold=3,
                recover_threshold=6,
                auto_failback=True,
            )
            == "stay"
        )
    assert (
        failover.decide_action(
            state,
            primary_ok=True,
            secondary_ok=True,
            fail_threshold=3,
            recover_threshold=6,
            auto_failback=True,
        )
        == "failback_to_primary"
    )


def test_failback_disabled_by_default_policy() -> None:
    state = failover.WatchState(active=failover.SiteRole.SECONDARY)
    for _ in range(10):
        assert (
            failover.decide_action(
                state,
                primary_ok=True,
                secondary_ok=True,
                fail_threshold=3,
                recover_threshold=6,
                auto_failback=False,
            )
            == "stay"
        )


def test_order_providers_by_region_prefers_nl_then_de() -> None:
    from app.services.ai_engine import order_providers_by_region

    providers = [
        SimpleNamespace(name="us1", region="us-east"),
        SimpleNamespace(name="de1", region="eu-de"),
        SimpleNamespace(name="nl1", region="eu-nl"),
        SimpleNamespace(name="orphan", region=""),
    ]
    ordered = order_providers_by_region(
        providers,  # type: ignore[arg-type]
        preferred_region="eu-nl",
        failover_regions=("eu-de", "us-east"),
    )
    assert [p.name for p in ordered] == ["nl1", "de1", "us1", "orphan"]


def test_midjourney_provider_settings_accept_region() -> None:
    from pydantic import SecretStr

    from app.core.config import MidjourneyProviderSettings

    provider = MidjourneyProviderSettings(
        name="proxy-nl",
        base_url="https://mj-nl.example/v1",
        api_key=SecretStr("secret-key"),
        region="EU-NL",
    )
    assert provider.region == "eu-nl"
