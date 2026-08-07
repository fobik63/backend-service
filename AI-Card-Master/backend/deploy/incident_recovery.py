#!/usr/bin/env python3
"""Automated Incident Response & Recovery (plan §63).

Monitors host hardware (CPU / RAM / disk / load) and Docker health. On critical
load: restarts configured Compose services, flushes expendable Redis *cache*
prefixes (never Celery broker queues), and alerts Telegram.

Daily encrypted PostgreSQL backups remain the responsibility of
``deploy/postgres_backup.sh`` + ``deploy/docker-compose.backup.yml``
(``BACKUP_INTERVAL_SECONDS=86400`` for daily; default 6h still meets the SLA).

Usage (from backend/ on the origin host):
  python deploy/incident_recovery.py
  python deploy/incident_recovery.py --once
  python deploy/incident_recovery.py --dry-run --once

Run under systemd / screen on the primary origin (not inside a container that
would be restarted by this script).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger("incident_recovery")

# Expendable analytics / stage caches. Celery queue lists and unacked keys
# must never appear here (canonical job state lives in PostgreSQL).
DEFAULT_REDIS_CACHE_PREFIXES: tuple[str, ...] = (
    "claude:",
    "analytics:",
    "generation:history:",
    "ab_test:",
    "pain_analysis:",
    "brand_lora:",
    "catalog:",
    "highload:",
    "three_d:",
)

DEFAULT_RESTART_SERVICES: tuple[str, ...] = ("api", "worker", "nginx")


class Severity(str, Enum):
    OK = "ok"
    WARN = "warn"
    CRITICAL = "critical"


class RecoveryAction(str, Enum):
    NONE = "none"
    ALERT_ONLY = "alert_only"
    RECOVER = "recover"


@dataclass(frozen=True, slots=True)
class HardwareSample:
    cpu_percent: float
    ram_percent: float
    disk_percent: float
    load_1m: float | None
    cpu_count: int


@dataclass(frozen=True, slots=True)
class IncidentConfig:
    poll_seconds: float
    fail_threshold: int
    cooldown_seconds: float
    cpu_critical_percent: float
    ram_critical_percent: float
    disk_critical_percent: float
    disk_warn_percent: float
    load_critical_per_cpu: float
    compose_files: tuple[str, ...]
    project_dir: Path
    restart_services: tuple[str, ...]
    redis_url: str
    redis_flush_prefixes: tuple[str, ...]
    redis_flush_scan_count: int
    health_url: str
    health_timeout_seconds: float
    telegram_bot_token: str
    telegram_chat_id: str
    dry_run: bool
    alert_cooldown_seconds: float


@dataclass(slots=True)
class WatchState:
    consecutive_critical: int = 0
    last_recovery_at: float = 0.0
    last_alert_key: str = ""
    last_alert_at: float = 0.0
    last_action: str = "init"
    disk_alerted: bool = False


@dataclass(frozen=True, slots=True)
class Decision:
    severity: Severity
    action: RecoveryAction
    reasons: tuple[str, ...]
    sample: HardwareSample | None = None


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


def _csv_tuple(raw: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    cleaned = tuple(part.strip() for part in raw.split(",") if part.strip())
    return cleaned or fallback


def load_config(dry_run: bool = False) -> IncidentConfig:
    compose_raw = _env(
        "INCIDENT_COMPOSE_FILES",
        "docker-compose.yml,deploy/docker-compose.scale.yml",
    )
    project_dir = Path(
        _env("INCIDENT_PROJECT_DIR", str(Path(__file__).resolve().parents[1]))
    ).resolve()
    return IncidentConfig(
        poll_seconds=max(5.0, _env_float("INCIDENT_POLL_SECONDS", 15.0)),
        fail_threshold=max(1, _env_int("INCIDENT_FAIL_THRESHOLD", 3)),
        cooldown_seconds=max(60.0, _env_float("INCIDENT_COOLDOWN_SECONDS", 300.0)),
        cpu_critical_percent=max(50.0, _env_float("INCIDENT_CPU_CRITICAL_PERCENT", 92.0)),
        ram_critical_percent=max(50.0, _env_float("INCIDENT_RAM_CRITICAL_PERCENT", 92.0)),
        disk_critical_percent=max(50.0, _env_float("INCIDENT_DISK_CRITICAL_PERCENT", 95.0)),
        disk_warn_percent=max(40.0, _env_float("INCIDENT_DISK_WARN_PERCENT", 85.0)),
        load_critical_per_cpu=max(
            1.0, _env_float("INCIDENT_LOAD_CRITICAL_PER_CPU", 4.0)
        ),
        compose_files=_csv_tuple(compose_raw, ("docker-compose.yml",)),
        project_dir=project_dir,
        restart_services=_csv_tuple(
            _env("INCIDENT_RESTART_SERVICES", ",".join(DEFAULT_RESTART_SERVICES)),
            DEFAULT_RESTART_SERVICES,
        ),
        redis_url=_env("REDIS_URL", "redis://127.0.0.1:6379/0"),
        redis_flush_prefixes=_csv_tuple(
            _env(
                "INCIDENT_REDIS_FLUSH_PREFIXES",
                ",".join(DEFAULT_REDIS_CACHE_PREFIXES),
            ),
            DEFAULT_REDIS_CACHE_PREFIXES,
        ),
        redis_flush_scan_count=max(10, _env_int("INCIDENT_REDIS_FLUSH_SCAN_COUNT", 200)),
        health_url=_env("INCIDENT_HEALTH_URL", "http://127.0.0.1/health/ready"),
        health_timeout_seconds=max(
            0.5, _env_float("INCIDENT_HEALTH_TIMEOUT_SECONDS", 3.0)
        ),
        telegram_bot_token=_env("TELEGRAM_ERROR_BOT_TOKEN"),
        telegram_chat_id=_env("TELEGRAM_ERROR_CHAT_ID"),
        dry_run=dry_run or _env_bool("INCIDENT_DRY_RUN", False),
        alert_cooldown_seconds=max(
            30.0, _env_float("INCIDENT_ALERT_COOLDOWN_SECONDS", 120.0)
        ),
    )


def sample_hardware(disk_path: str = "/") -> HardwareSample:
    """Blocking host sample via psutil when available, else /proc + shutil."""

    cpu_count = max(1, os.cpu_count() or 1)
    load_1m: float | None = None
    try:
        load_1m = float(os.getloadavg()[0])  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        load_1m = None

    try:
        import psutil  # type: ignore[import-untyped]

        cpu = float(psutil.cpu_percent(interval=0.2))
        ram = float(psutil.virtual_memory().percent)
        disk = float(psutil.disk_usage(disk_path).percent)
        return HardwareSample(
            cpu_percent=round(cpu, 2),
            ram_percent=round(ram, 2),
            disk_percent=round(disk, 2),
            load_1m=load_1m,
            cpu_count=cpu_count,
        )
    except ImportError:
        pass

    # Fallback without psutil (Windows-friendly enough for dry-run / unit tests).
    usage = shutil.disk_usage(disk_path)
    disk_percent = (usage.used / usage.total) * 100.0 if usage.total else 0.0
    return HardwareSample(
        cpu_percent=0.0,
        ram_percent=0.0,
        disk_percent=round(disk_percent, 2),
        load_1m=load_1m,
        cpu_count=cpu_count,
    )


def classify_sample(cfg: IncidentConfig, sample: HardwareSample) -> Decision:
    """Pure classifier: map hardware sample → severity / recommended action."""

    reasons: list[str] = []
    critical = False
    warn = False

    if sample.cpu_percent >= cfg.cpu_critical_percent:
        critical = True
        reasons.append(f"cpu={sample.cpu_percent:.1f}%≥{cfg.cpu_critical_percent:.0f}%")
    if sample.ram_percent >= cfg.ram_critical_percent:
        critical = True
        reasons.append(f"ram={sample.ram_percent:.1f}%≥{cfg.ram_critical_percent:.0f}%")
    if sample.disk_percent >= cfg.disk_critical_percent:
        critical = True
        reasons.append(
            f"disk={sample.disk_percent:.1f}%≥{cfg.disk_critical_percent:.0f}%"
        )
    elif sample.disk_percent >= cfg.disk_warn_percent:
        warn = True
        reasons.append(f"disk={sample.disk_percent:.1f}%≥{cfg.disk_warn_percent:.0f}%")

    if sample.load_1m is not None:
        load_limit = cfg.load_critical_per_cpu * sample.cpu_count
        if sample.load_1m >= load_limit:
            critical = True
            reasons.append(
                f"load1={sample.load_1m:.2f}≥{load_limit:.1f} ({sample.cpu_count} cpu)"
            )

    if critical:
        return Decision(
            severity=Severity.CRITICAL,
            action=RecoveryAction.RECOVER,
            reasons=tuple(reasons),
            sample=sample,
        )
    if warn:
        return Decision(
            severity=Severity.WARN,
            action=RecoveryAction.ALERT_ONLY,
            reasons=tuple(reasons),
            sample=sample,
        )
    return Decision(
        severity=Severity.OK,
        action=RecoveryAction.NONE,
        reasons=(),
        sample=sample,
    )


def decide_with_hysteresis(
    state: WatchState,
    decision: Decision,
    *,
    fail_threshold: int,
    cooldown_seconds: float,
    now: float,
    health_ok: bool | None,
) -> Decision:
    """Require consecutive critical samples; respect recovery cooldown."""

    if decision.severity is Severity.CRITICAL:
        state.consecutive_critical += 1
    else:
        state.consecutive_critical = 0

    reasons = list(decision.reasons)
    if health_ok is False:
        reasons.append("health_ready=fail")
        # Unready stack is treated as critical pressure for recovery path.
        state.consecutive_critical = max(state.consecutive_critical, fail_threshold)
        decision = Decision(
            severity=Severity.CRITICAL,
            action=RecoveryAction.RECOVER,
            reasons=tuple(reasons),
            sample=decision.sample,
        )

    if decision.action is RecoveryAction.RECOVER:
        if state.consecutive_critical < fail_threshold:
            return Decision(
                severity=Severity.WARN,
                action=RecoveryAction.ALERT_ONLY,
                reasons=tuple(
                    [
                        *reasons,
                        f"critical_streak={state.consecutive_critical}/{fail_threshold}",
                    ]
                ),
                sample=decision.sample,
            )
        if (
            state.last_recovery_at > 0.0
            and now - state.last_recovery_at < cooldown_seconds
        ):
            return Decision(
                severity=Severity.CRITICAL,
                action=RecoveryAction.ALERT_ONLY,
                reasons=tuple([*reasons, "recovery_cooldown"]),
                sample=decision.sample,
            )
    return decision


def probe_health_ok(url: str, timeout: float) -> bool | None:
    if not url:
        return None
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if int(getattr(resp, "status", 200)) != 200:
                return False
            body = resp.read(4096).decode("utf-8", errors="replace").lower()
            if "not_ready" in body or '"ready": false' in body:
                return False
            return True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def notify_telegram(cfg: IncidentConfig, text: str, *, alert_key: str = "") -> None:
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
        if alert_key:
            logger.info("Telegram alert sent key=%s", alert_key)
    except (urllib.error.URLError, TimeoutError, OSError):
        logger.exception("Telegram notify failed")


def maybe_alert(
    cfg: IncidentConfig,
    state: WatchState,
    *,
    key: str,
    text: str,
    now: float,
) -> None:
    if key and key == state.last_alert_key:
        if now - state.last_alert_at < cfg.alert_cooldown_seconds:
            return
    notify_telegram(cfg, text, alert_key=key)
    state.last_alert_key = key
    state.last_alert_at = now


def _compose_base_cmd(cfg: IncidentConfig) -> list[str]:
    cmd = ["docker", "compose"]
    for compose_file in cfg.compose_files:
        cmd.extend(["-f", compose_file])
    return cmd


def restart_containers(cfg: IncidentConfig) -> list[str]:
    """Restart app-tier Compose services. Never touches postgres by default."""

    services = [s for s in cfg.restart_services if s.lower() != "postgres"]
    if not services:
        logger.warning("No restart services configured")
        return []
    cmd = [*_compose_base_cmd(cfg), "restart", *services]
    logger.error("Restarting containers: %s", " ".join(services))
    if cfg.dry_run:
        logger.warning("DRY-RUN: %s", " ".join(cmd))
        return services
    subprocess.run(cmd, cwd=cfg.project_dir, check=True)
    return services


def flush_redis_cache(cfg: IncidentConfig) -> int:
    """SCAN+DELETE expendable cache prefixes. Preserves Celery broker keys."""

    if not cfg.redis_url or not cfg.redis_flush_prefixes:
        return 0
    if cfg.dry_run:
        logger.warning(
            "DRY-RUN Redis flush prefixes=%s",
            ",".join(cfg.redis_flush_prefixes),
        )
        return 0
    try:
        import redis  # type: ignore[import-untyped]
    except ImportError:
        logger.error("Missing dependency: pip install redis")
        return 0

    deleted = 0
    client = redis.Redis.from_url(cfg.redis_url, decode_responses=True, socket_timeout=5)
    try:
        for prefix in cfg.redis_flush_prefixes:
            pattern = f"{prefix}*"
            for key in client.scan_iter(match=pattern, count=cfg.redis_flush_scan_count):
                # Defensive: never delete Celery unacked / queue internals.
                key_s = str(key)
                if key_s.startswith(("unacked", "_kombu", "celery")):
                    continue
                deleted += int(client.delete(key_s))
        logger.error("Redis cache flush deleted=%s keys", deleted)
    except Exception:
        logger.exception("Redis cache flush failed")
        raise
    finally:
        try:
            client.close()
        except Exception:
            pass
    return deleted


def format_hardware_alert(
    *,
    decision: Decision,
    recovered: bool,
    restarted: list[str],
    redis_deleted: int,
) -> str:
    sample = decision.sample
    lines = [
        "🚨 HARDWARE_INCIDENT" if not recovered else "✅ INCIDENT_RECOVERY_DONE",
        f"severity={decision.severity.value}",
        f"reasons={', '.join(decision.reasons) or 'n/a'}",
    ]
    if sample is not None:
        lines.append(
            f"cpu={sample.cpu_percent:.1f}% ram={sample.ram_percent:.1f}% "
            f"disk={sample.disk_percent:.1f}%"
        )
        if sample.load_1m is not None:
            lines.append(f"load1={sample.load_1m:.2f} cpus={sample.cpu_count}")
    if recovered:
        lines.append(f"restarted={','.join(restarted) or 'none'}")
        lines.append(f"redis_cache_deleted={redis_deleted}")
    return "\n".join(lines)


def apply_recovery(cfg: IncidentConfig, state: WatchState, decision: Decision) -> None:
    restarted: list[str] = []
    deleted = 0
    errors: list[str] = []

    try:
        deleted = flush_redis_cache(cfg)
    except Exception as exc:  # noqa: BLE001 — continue to container restart
        errors.append(f"redis_flush:{exc.__class__.__name__}")

    try:
        restarted = restart_containers(cfg)
    except subprocess.CalledProcessError as exc:
        errors.append(f"docker_restart:exit={exc.returncode}")
        logger.exception("Container restart failed")

    state.last_recovery_at = time.monotonic()
    state.last_action = "recover"
    state.consecutive_critical = 0

    text = format_hardware_alert(
        decision=decision,
        recovered=True,
        restarted=restarted,
        redis_deleted=deleted,
    )
    if errors:
        text += "\nerrors=" + ",".join(errors)
    notify_telegram(cfg, text, alert_key="recovery")


def run_once(cfg: IncidentConfig, state: WatchState) -> Decision:
    disk_path = _env("INCIDENT_DISK_PATH", "/")
    if os.name == "nt" and disk_path == "/":
        disk_path = os.environ.get("SystemDrive", "C:") + "\\"

    sample = sample_hardware(disk_path)
    base = classify_sample(cfg, sample)
    health_ok = probe_health_ok(cfg.health_url, cfg.health_timeout_seconds)
    now = time.monotonic()
    decision = decide_with_hysteresis(
        state,
        base,
        fail_threshold=cfg.fail_threshold,
        cooldown_seconds=cfg.cooldown_seconds,
        now=now,
        health_ok=health_ok,
    )

    logger.info(
        "severity=%s action=%s cpu=%.1f ram=%.1f disk=%.1f health=%s streak=%s reasons=%s",
        decision.severity.value,
        decision.action.value,
        sample.cpu_percent,
        sample.ram_percent,
        sample.disk_percent,
        health_ok,
        state.consecutive_critical,
        ",".join(decision.reasons) or "-",
    )

    if decision.action is RecoveryAction.RECOVER:
        apply_recovery(cfg, state, decision)
        return decision

    if decision.action is RecoveryAction.ALERT_ONLY:
        maybe_alert(
            cfg,
            state,
            key=f"hw:{decision.severity.value}:{','.join(decision.reasons)}",
            text=format_hardware_alert(
                decision=decision,
                recovered=False,
                restarted=[],
                redis_deleted=0,
            ),
            now=now,
        )
        # Disk pressure alone: persistent warn until cleared.
        if any(r.startswith("disk=") for r in decision.reasons):
            state.disk_alerted = True
        state.last_action = "alert_only"
        return decision

    if state.disk_alerted and sample.disk_percent < cfg.disk_warn_percent:
        maybe_alert(
            cfg,
            state,
            key="disk:recovered",
            text=(
                f"✅ DISK_PRESSURE_CLEARED disk={sample.disk_percent:.1f}% "
                f"< {cfg.disk_warn_percent:.0f}%"
            ),
            now=now,
        )
        state.disk_alerted = False
    state.last_action = "ok"
    return decision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Automated incident response & recovery (plan §63)"
    )
    parser.add_argument("--once", action="store_true", help="Single evaluation cycle")
    parser.add_argument("--dry-run", action="store_true", help="No mutate / Telegram")
    parser.add_argument(
        "--log-level",
        default=_env("INCIDENT_LOG_LEVEL", "INFO"),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config(dry_run=args.dry_run)
    state = WatchState()

    if args.once:
        run_once(cfg, state)
        return 0

    logger.info(
        "Incident recovery started poll=%.1fs fail_threshold=%s cooldown=%.0fs "
        "cpu≥%.0f ram≥%.0f disk≥%.0f dry_run=%s",
        cfg.poll_seconds,
        cfg.fail_threshold,
        cfg.cooldown_seconds,
        cfg.cpu_critical_percent,
        cfg.ram_critical_percent,
        cfg.disk_critical_percent,
        cfg.dry_run,
    )
    while True:
        try:
            run_once(cfg, state)
        except Exception:
            logger.exception("Incident recovery cycle failed")
            notify_telegram(
                cfg,
                "⚠️ incident_recovery cycle error — check origin logs",
                alert_key="cycle_error",
            )
        time.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    sys.exit(main())
