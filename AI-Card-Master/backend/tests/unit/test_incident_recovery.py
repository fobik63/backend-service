"""Unit tests for automated incident response & recovery (plan §63)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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


incident = _load("incident_recovery_mod", "incident_recovery.py")


def _cfg(**overrides: object) -> incident.IncidentConfig:
    data: dict[str, object] = {
        "poll_seconds": 15.0,
        "fail_threshold": 3,
        "cooldown_seconds": 300.0,
        "cpu_critical_percent": 92.0,
        "ram_critical_percent": 92.0,
        "disk_critical_percent": 95.0,
        "disk_warn_percent": 85.0,
        "load_critical_per_cpu": 4.0,
        "compose_files": ("docker-compose.yml",),
        "project_dir": BACKEND_ROOT,
        "restart_services": ("api", "worker", "nginx"),
        "redis_url": "redis://127.0.0.1:6379/0",
        "redis_flush_prefixes": incident.DEFAULT_REDIS_CACHE_PREFIXES,
        "redis_flush_scan_count": 200,
        "health_url": "http://127.0.0.1/health/ready",
        "health_timeout_seconds": 3.0,
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "dry_run": True,
        "alert_cooldown_seconds": 120.0,
    }
    data.update(overrides)
    return incident.IncidentConfig(**data)  # type: ignore[arg-type]


def test_classify_ok() -> None:
    sample = incident.HardwareSample(
        cpu_percent=10.0,
        ram_percent=20.0,
        disk_percent=30.0,
        load_1m=0.5,
        cpu_count=4,
    )
    decision = incident.classify_sample(_cfg(), sample)
    assert decision.severity is incident.Severity.OK
    assert decision.action is incident.RecoveryAction.NONE


def test_classify_cpu_critical() -> None:
    sample = incident.HardwareSample(
        cpu_percent=95.0,
        ram_percent=40.0,
        disk_percent=30.0,
        load_1m=1.0,
        cpu_count=4,
    )
    decision = incident.classify_sample(_cfg(), sample)
    assert decision.severity is incident.Severity.CRITICAL
    assert decision.action is incident.RecoveryAction.RECOVER
    assert any(r.startswith("cpu=") for r in decision.reasons)


def test_classify_disk_warn_only() -> None:
    sample = incident.HardwareSample(
        cpu_percent=10.0,
        ram_percent=20.0,
        disk_percent=88.0,
        load_1m=0.2,
        cpu_count=2,
    )
    decision = incident.classify_sample(_cfg(), sample)
    assert decision.severity is incident.Severity.WARN
    assert decision.action is incident.RecoveryAction.ALERT_ONLY


def test_hysteresis_requires_fail_threshold() -> None:
    state = incident.WatchState()
    sample = incident.HardwareSample(95.0, 40.0, 30.0, 1.0, 4)
    critical = incident.classify_sample(_cfg(), sample)
    for expected_streak in (1, 2):
        decision = incident.decide_with_hysteresis(
            state,
            critical,
            fail_threshold=3,
            cooldown_seconds=300.0,
            now=1000.0,
            health_ok=True,
        )
        assert decision.action is incident.RecoveryAction.ALERT_ONLY
        assert state.consecutive_critical == expected_streak

    decision = incident.decide_with_hysteresis(
        state,
        critical,
        fail_threshold=3,
        cooldown_seconds=300.0,
        now=1000.0,
        health_ok=True,
    )
    assert decision.action is incident.RecoveryAction.RECOVER


def test_cooldown_blocks_second_recovery() -> None:
    state = incident.WatchState(consecutive_critical=3, last_recovery_at=900.0)
    sample = incident.HardwareSample(95.0, 95.0, 30.0, 1.0, 4)
    critical = incident.classify_sample(_cfg(), sample)
    decision = incident.decide_with_hysteresis(
        state,
        critical,
        fail_threshold=3,
        cooldown_seconds=300.0,
        now=1000.0,
        health_ok=True,
    )
    assert decision.action is incident.RecoveryAction.ALERT_ONLY
    assert "recovery_cooldown" in decision.reasons


def test_health_fail_forces_recovery_path() -> None:
    state = incident.WatchState()
    ok_sample = incident.HardwareSample(10.0, 20.0, 30.0, 0.1, 2)
    base = incident.classify_sample(_cfg(), ok_sample)
    decision = incident.decide_with_hysteresis(
        state,
        base,
        fail_threshold=3,
        cooldown_seconds=300.0,
        now=50.0,
        health_ok=False,
    )
    assert decision.severity is incident.Severity.CRITICAL
    assert decision.action is incident.RecoveryAction.RECOVER
    assert "health_ready=fail" in decision.reasons


def test_restart_services_exclude_postgres_by_default() -> None:
    assert "postgres" not in incident.DEFAULT_RESTART_SERVICES


def test_redis_prefixes_are_cache_only() -> None:
    forbidden = ("unacked", "celery", "_kombu", "generation.submit")
    joined = ",".join(incident.DEFAULT_REDIS_CACHE_PREFIXES)
    for token in forbidden:
        assert token not in joined


def test_format_hardware_alert_contains_metrics() -> None:
    sample = incident.HardwareSample(93.0, 94.0, 40.0, 8.0, 2)
    decision = incident.Decision(
        severity=incident.Severity.CRITICAL,
        action=incident.RecoveryAction.RECOVER,
        reasons=("cpu=93.0%≥92%",),
        sample=sample,
    )
    text = incident.format_hardware_alert(
        decision=decision,
        recovered=True,
        restarted=["api", "worker"],
        redis_deleted=12,
    )
    assert "INCIDENT_RECOVERY_DONE" in text
    assert "restarted=api,worker" in text
    assert "redis_cache_deleted=12" in text
