#!/usr/bin/env python3
"""Geo failover watchdog: primary health → Cloudflare origin switch ≤30s (plan §36).

Probes PRIMARY_HEALTH_URL every FAILOVER_POLL_SECONDS. After
FAILOVER_FAIL_THRESHOLD consecutive failures, updates the Cloudflare DNS A/AAAA
record (or Load Balancer origin) to the secondary IP and alerts Telegram.

Usage (from backend/ or any host that can reach both origins + Cloudflare API):
  python deploy/failover_watchdog.py
  python deploy/failover_watchdog.py --once
  python deploy/failover_watchdog.py --dry-run --once

Run this on the secondary / jump host — never only on the primary itself.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Literal

logger = logging.getLogger("failover_watchdog")


class SiteRole(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


@dataclass(frozen=True, slots=True)
class FailoverConfig:
    primary_health_url: str
    secondary_health_url: str
    primary_origin_ip: str
    secondary_origin_ip: str
    dns_record_name: str
    dns_record_type: Literal["A", "AAAA"]
    cloudflare_zone_id: str
    cloudflare_api_token: str
    cloudflare_api_base: str
    poll_seconds: float
    fail_threshold: int
    recover_threshold: int
    probe_timeout_seconds: float
    auto_failback: bool
    telegram_bot_token: str
    telegram_chat_id: str
    dry_run: bool


@dataclass(slots=True)
class WatchState:
    active: SiteRole = SiteRole.PRIMARY
    consecutive_primary_fails: int = 0
    consecutive_primary_oks: int = 0
    consecutive_secondary_oks: int = 0
    last_action: str = "init"


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    return float(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def load_config(dry_run: bool = False) -> FailoverConfig:
    return FailoverConfig(
        primary_health_url=_env(
            "FAILOVER_PRIMARY_HEALTH_URL",
            "http://127.0.0.1:8000/health/ready",
        ),
        secondary_health_url=_env("FAILOVER_SECONDARY_HEALTH_URL"),
        primary_origin_ip=_env("FAILOVER_PRIMARY_ORIGIN_IP"),
        secondary_origin_ip=_env("FAILOVER_SECONDARY_ORIGIN_IP"),
        dns_record_name=_env("FAILOVER_DNS_RECORD_NAME", "api"),
        dns_record_type="AAAA" if _env("FAILOVER_DNS_RECORD_TYPE", "A").upper() == "AAAA" else "A",
        cloudflare_zone_id=_env("CLOUDFLARE_ZONE_ID") or _env("FAILOVER_CLOUDFLARE_ZONE_ID"),
        cloudflare_api_token=_env("CLOUDFLARE_API_TOKEN") or _env("FAILOVER_CLOUDFLARE_API_TOKEN"),
        cloudflare_api_base=_env(
            "CLOUDFLARE_API_BASE_URL", "https://api.cloudflare.com"
        ).rstrip("/"),
        poll_seconds=max(1.0, _env_float("FAILOVER_POLL_SECONDS", 5.0)),
        fail_threshold=max(1, _env_int("FAILOVER_FAIL_THRESHOLD", 3)),
        recover_threshold=max(1, _env_int("FAILOVER_RECOVER_THRESHOLD", 6)),
        probe_timeout_seconds=max(0.5, _env_float("FAILOVER_PROBE_TIMEOUT_SECONDS", 3.0)),
        auto_failback=_env_bool("FAILOVER_AUTO_FAILBACK", False),
        telegram_bot_token=_env("TELEGRAM_ERROR_BOT_TOKEN"),
        telegram_chat_id=_env("TELEGRAM_ERROR_CHAT_ID"),
        dry_run=dry_run or _env_bool("FAILOVER_DRY_RUN", False),
    )


def max_detection_seconds(cfg: FailoverConfig) -> float:
    """Worst-case seconds from first failure to failover decision (excl. CF API)."""

    return cfg.poll_seconds * cfg.fail_threshold + cfg.probe_timeout_seconds


def probe_ok(url: str, timeout: float) -> bool:
    if not url:
        return False
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            body = resp.read(4096).decode("utf-8", errors="replace")
            # Prefer structured ready checks; accept plain ok too.
            if '"status"' in body and "ok" not in body.lower() and "ready" not in body.lower():
                return False
            return True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


Decision = Literal["stay", "failover_to_secondary", "failback_to_primary"]


def decide_action(
    state: WatchState,
    *,
    primary_ok: bool,
    secondary_ok: bool | None,
    fail_threshold: int,
    recover_threshold: int,
    auto_failback: bool,
) -> Decision:
    """Pure state machine: detection window = fail_threshold consecutive probes."""

    if primary_ok:
        state.consecutive_primary_fails = 0
        state.consecutive_primary_oks += 1
    else:
        state.consecutive_primary_oks = 0
        state.consecutive_primary_fails += 1

    if secondary_ok is True:
        state.consecutive_secondary_oks += 1
    elif secondary_ok is False:
        state.consecutive_secondary_oks = 0

    if state.active is SiteRole.PRIMARY:
        if state.consecutive_primary_fails >= fail_threshold:
            if secondary_ok is False:
                # Do not leave clients on a dead secondary.
                return "stay"
            return "failover_to_secondary"
        return "stay"

    # Active secondary
    if not auto_failback:
        return "stay"
    if (
        state.consecutive_primary_oks >= recover_threshold
        and (secondary_ok is None or state.consecutive_secondary_oks >= 1)
    ):
        return "failback_to_primary"
    return "stay"


def _cf_request(
    cfg: FailoverConfig,
    method: str,
    path: str,
    payload: dict | None = None,
) -> dict:
    url = f"{cfg.cloudflare_api_base}/client/v4{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {cfg.cloudflare_api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def find_dns_record_id(cfg: FailoverConfig) -> str | None:
    """Match short name or FQDN (Cloudflare returns FQDN in result.name)."""

    name = cfg.dns_record_name
    path = (
        f"/zones/{cfg.cloudflare_zone_id}/dns_records"
        f"?type={cfg.dns_record_type}&per_page=100"
    )
    result = _cf_request(cfg, "GET", path)
    records = result.get("result") or []
    for row in records:
        row_name = str(row.get("name", ""))
        if row_name == name or row_name.startswith(f"{name}."):
            return str(row["id"])
    # Explicit name filter as fallback (exact FQDN in env).
    q = urllib.parse.urlencode(
        {"type": cfg.dns_record_type, "name": name, "per_page": "20"}
    )
    result = _cf_request(cfg, "GET", f"/zones/{cfg.cloudflare_zone_id}/dns_records?{q}")
    records = result.get("result") or []
    if records:
        return str(records[0]["id"])
    return None


def switch_origin(cfg: FailoverConfig, target_ip: str) -> None:
    if not cfg.cloudflare_zone_id or not cfg.cloudflare_api_token:
        raise RuntimeError("CLOUDFLARE_ZONE_ID and CLOUDFLARE_API_TOKEN are required.")
    if not target_ip:
        raise RuntimeError("Target origin IP is empty.")
    if cfg.dry_run:
        logger.warning("DRY-RUN: would point %s %s → %s", cfg.dns_record_type, cfg.dns_record_name, target_ip)
        return
    record_id = find_dns_record_id(cfg)
    if not record_id:
        raise RuntimeError(
            f"DNS record not found: type={cfg.dns_record_type} name={cfg.dns_record_name}"
        )
    _cf_request(
        cfg,
        "PATCH",
        f"/zones/{cfg.cloudflare_zone_id}/dns_records/{record_id}",
        {
            "type": cfg.dns_record_type,
            "name": cfg.dns_record_name,
            "content": target_ip,
            "ttl": 1,  # Auto when proxied
            "proxied": True,
        },
    )


def notify_telegram(cfg: FailoverConfig, text: str) -> None:
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        logger.info("Telegram skip: %s", text)
        return
    if cfg.dry_run:
        logger.warning("DRY-RUN Telegram: %s", text)
        return
    payload = json.dumps(
        {"chat_id": cfg.telegram_chat_id, "text": text[:3500]}
    ).encode("utf-8")
    url = f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage"
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8):
            pass
    except (urllib.error.URLError, TimeoutError, OSError):
        logger.exception("Telegram notify failed")


def apply_decision(cfg: FailoverConfig, state: WatchState, decision: Decision) -> None:
    if decision == "stay":
        return
    if decision == "failover_to_secondary":
        switch_origin(cfg, cfg.secondary_origin_ip)
        state.active = SiteRole.SECONDARY
        state.consecutive_primary_fails = 0
        state.last_action = "failover_to_secondary"
        notify_telegram(
            cfg,
            "🚨 FAILOVER_ACTIVATED primary→secondary\n"
            f"primary_health={cfg.primary_health_url}\n"
            f"origin→{cfg.secondary_origin_ip}",
        )
        logger.error("Failover to secondary origin %s", cfg.secondary_origin_ip)
        return
    if decision == "failback_to_primary":
        switch_origin(cfg, cfg.primary_origin_ip)
        state.active = SiteRole.PRIMARY
        state.consecutive_primary_oks = 0
        state.last_action = "failback_to_primary"
        notify_telegram(
            cfg,
            "✅ FAILBACK_ACTIVATED secondary→primary\n"
            f"origin→{cfg.primary_origin_ip}",
        )
        logger.warning("Failback to primary origin %s", cfg.primary_origin_ip)


def validate_slo(cfg: FailoverConfig) -> None:
    window = max_detection_seconds(cfg)
    if window > 30.0:
        raise SystemExit(
            f"Detection window {window:.1f}s exceeds 30s SLO. "
            "Lower FAILOVER_POLL_SECONDS or FAILOVER_FAIL_THRESHOLD."
        )


def run_once(cfg: FailoverConfig, state: WatchState) -> Decision:
    primary_ok = probe_ok(cfg.primary_health_url, cfg.probe_timeout_seconds)
    secondary_ok: bool | None = None
    if cfg.secondary_health_url:
        secondary_ok = probe_ok(cfg.secondary_health_url, cfg.probe_timeout_seconds)
    decision = decide_action(
        state,
        primary_ok=primary_ok,
        secondary_ok=secondary_ok,
        fail_threshold=cfg.fail_threshold,
        recover_threshold=cfg.recover_threshold,
        auto_failback=cfg.auto_failback,
    )
    logger.info(
        "primary_ok=%s secondary_ok=%s active=%s fails=%s oks=%s → %s",
        primary_ok,
        secondary_ok,
        state.active.value,
        state.consecutive_primary_fails,
        state.consecutive_primary_oks,
        decision,
    )
    apply_decision(cfg, state, decision)
    return decision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Geo failover watchdog (plan §36)")
    parser.add_argument("--once", action="store_true", help="Single probe cycle")
    parser.add_argument("--dry-run", action="store_true", help="No DNS / Telegram mutations")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config(dry_run=args.dry_run)
    validate_slo(cfg)
    if not cfg.secondary_origin_ip:
        logger.error("FAILOVER_SECONDARY_ORIGIN_IP is required")
        return 2

    state = WatchState()
    if args.once:
        run_once(cfg, state)
        return 0

    logger.info(
        "Watchdog started poll=%.1fs fail_threshold=%s max_detect=%.1fs dry_run=%s",
        cfg.poll_seconds,
        cfg.fail_threshold,
        max_detection_seconds(cfg),
        cfg.dry_run,
    )
    while True:
        try:
            run_once(cfg, state)
        except Exception:
            logger.exception("Watchdog cycle failed")
            notify_telegram(cfg, "⚠️ failover_watchdog cycle error — check logs")
        time.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    sys.exit(main())
