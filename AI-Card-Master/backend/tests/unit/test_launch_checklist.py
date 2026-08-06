"""Unit tests for launch preflight audit and autoscaler decisions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

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


preflight = _load("launch_preflight_audit", "preflight_audit.py")
autoscale = _load("launch_autoscale", "autoscale.py")


def test_scan_text_flags_print_and_test_keys() -> None:
    dirty = (
        "def demo():\n"
        "    print('leak')\n"
        "    api_key = 'sk_test_this_is_not_a_real_key_123'\n"
    )
    findings = preflight.scan_text("app/demo.py", dirty)
    kinds = {item.kind for item in findings}
    assert "console_print" in kinds
    assert "hardcoded_secret" in kinds or "test_api_key_marker" in kinds


def test_scan_text_allows_logger_and_env_placeholders() -> None:
    clean = (
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "logger.info('ok')\n"
        "api_key = 'replace_with_a_strong_random_secret_at_least_64_characters_long'\n"
    )
    assert preflight.scan_text("app/clean.py", clean) == []


def test_audit_tree_on_real_app_is_clean() -> None:
    findings = preflight.audit_tree(BACKEND_ROOT)
    assert findings == [], preflight.format_report(findings)


def test_desired_replicas_scales_workers_with_queue_depth() -> None:
    cfg = autoscale.AutoscaleConfig(
        redis_url="redis://localhost:6379/0",
        compose_files=("docker-compose.yml",),
        project_dir=BACKEND_ROOT,
        queues=autoscale.DEFAULT_QUEUES,
        api_min=1,
        api_max=4,
        worker_min=1,
        worker_max=6,
        scale_up_queue_depth=20,
        scale_down_queue_depth=2,
        poll_seconds=30.0,
        cooldown_seconds=90.0,
        health_url="http://127.0.0.1/health/ready",
        health_slow_ms=1500.0,
        dry_run=True,
    )
    api_n, worker_n = autoscale.desired_replicas(cfg, depth=45, health_ms=100.0)
    assert api_n == 2  # depth >= 2 * scale_up_queue_depth
    assert worker_n == 3  # min + floor(45/20)

    api_n, worker_n = autoscale.desired_replicas(cfg, depth=45, health_ms=2000.0)
    assert api_n >= 2
    assert worker_n == 3

    api_n, worker_n = autoscale.desired_replicas(cfg, depth=25, health_ms=100.0)
    assert api_n == 1
    assert worker_n == 2

    api_n, worker_n = autoscale.desired_replicas(cfg, depth=0, health_ms=100.0)
    assert api_n == 1
    assert worker_n == 1


@pytest.mark.parametrize(
    ("depth", "health_ms", "api_max", "expected_api"),
    [
        (0, 100.0, 4, 1),
        (50, 100.0, 4, 2),
        (5, 2000.0, 4, 2),
    ],
)
def test_desired_api_scaling_matrix(
    depth: int, health_ms: float, api_max: int, expected_api: int
) -> None:
    cfg = autoscale.AutoscaleConfig(
        redis_url="redis://localhost:6379/0",
        compose_files=("docker-compose.yml",),
        project_dir=BACKEND_ROOT,
        queues=autoscale.DEFAULT_QUEUES,
        api_min=1,
        api_max=api_max,
        worker_min=1,
        worker_max=6,
        scale_up_queue_depth=20,
        scale_down_queue_depth=2,
        poll_seconds=30.0,
        cooldown_seconds=90.0,
        health_url="",
        health_slow_ms=1500.0,
        dry_run=True,
    )
    api_n, _ = autoscale.desired_replicas(cfg, depth=depth, health_ms=health_ms)
    assert api_n == expected_api
