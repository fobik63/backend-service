#!/usr/bin/env python3
"""Autoscaler for Docker Compose API + Celery worker replicas.

Watches Celery Redis queue depth and optionally /health/ready latency.
When backlog grows, raises ``docker compose --scale``; when idle, scales down.

Usage (from backend/):
  python deploy/autoscale.py
  python deploy/autoscale.py --once
  python deploy/autoscale.py --dry-run

Requires: redis (pip), docker CLI, compose files below.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

try:
    import redis
except ImportError:  # pragma: no cover - runtime dependency on host
    redis = None  # type: ignore[assignment]

logger = logging.getLogger("autoscale")

DEFAULT_QUEUES = (
    "generation.submit",
    "generation.finalize",
    "generation.recovery",
    "winback",
    "bulk",
    "smart_variant",
    "claude.reasoning",
    "claude.recovery",
    "ab_test",
    "stock_parser",
    "analytics.scrape",
)


@dataclass(frozen=True, slots=True)
class AutoscaleConfig:
    redis_url: str
    compose_files: tuple[str, ...]
    project_dir: Path
    queues: tuple[str, ...]
    api_min: int
    api_max: int
    worker_min: int
    worker_max: int
    scale_up_queue_depth: int
    scale_down_queue_depth: int
    poll_seconds: float
    cooldown_seconds: float
    health_url: str
    health_slow_ms: float
    dry_run: bool


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return float(raw)


def load_config(dry_run: bool = False) -> AutoscaleConfig:
    queues_raw = os.getenv("AUTOSCALE_QUEUES", "").strip()
    queues = (
        tuple(q.strip() for q in queues_raw.split(",") if q.strip())
        if queues_raw
        else DEFAULT_QUEUES
    )
    compose_raw = os.getenv(
        "AUTOSCALE_COMPOSE_FILES",
        "docker-compose.yml,deploy/docker-compose.scale.yml",
    )
    compose_files = tuple(p.strip() for p in compose_raw.split(",") if p.strip())
    project_dir = Path(
        os.getenv("AUTOSCALE_PROJECT_DIR", Path(__file__).resolve().parents[1])
    ).resolve()
    return AutoscaleConfig(
        redis_url=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
        compose_files=compose_files,
        project_dir=project_dir,
        queues=queues,
        api_min=max(1, _env_int("AUTOSCALE_API_MIN", 1)),
        api_max=max(1, _env_int("AUTOSCALE_API_MAX", 4)),
        worker_min=max(1, _env_int("AUTOSCALE_WORKER_MIN", 1)),
        worker_max=max(1, _env_int("AUTOSCALE_WORKER_MAX", 6)),
        scale_up_queue_depth=max(1, _env_int("AUTOSCALE_SCALE_UP_DEPTH", 20)),
        scale_down_queue_depth=max(0, _env_int("AUTOSCALE_SCALE_DOWN_DEPTH", 2)),
        poll_seconds=max(5.0, _env_float("AUTOSCALE_POLL_SECONDS", 30.0)),
        cooldown_seconds=max(30.0, _env_float("AUTOSCALE_COOLDOWN_SECONDS", 90.0)),
        health_url=os.getenv(
            "AUTOSCALE_HEALTH_URL", "http://127.0.0.1/health/ready"
        ).strip(),
        health_slow_ms=max(50.0, _env_float("AUTOSCALE_HEALTH_SLOW_MS", 1500.0)),
        dry_run=dry_run or os.getenv("AUTOSCALE_DRY_RUN", "").lower() in {"1", "true", "yes"},
    )


def queue_depth(client: "redis.Redis", queues: tuple[str, ...]) -> int:
    total = 0
    for name in queues:
        try:
            total += int(client.llen(name) or 0)
        except Exception:  # noqa: BLE001 — fail-open per queue
            logger.exception("Failed to read queue length for %s", name)
    return total


def probe_health_ms(url: str, timeout: float = 3.0) -> float | None:
    if not url:
        return None
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if int(getattr(response, "status", 200)) >= 500:
                return None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    return (time.perf_counter() - started) * 1000.0


def desired_replicas(cfg: AutoscaleConfig, depth: int, health_ms: float | None) -> tuple[int, int]:
    """Return (api_replicas, worker_replicas) from backlog + health latency."""

    worker_target = cfg.worker_min
    if depth >= cfg.scale_up_queue_depth:
        # One extra worker per full scale-up threshold, capped.
        steps = depth // cfg.scale_up_queue_depth
        worker_target = min(cfg.worker_max, cfg.worker_min + steps)
    elif depth <= cfg.scale_down_queue_depth:
        worker_target = cfg.worker_min

    api_target = cfg.api_min
    if health_ms is not None and health_ms >= cfg.health_slow_ms:
        api_target = min(cfg.api_max, cfg.api_min + 1)
    if depth >= cfg.scale_up_queue_depth * 2:
        api_target = min(cfg.api_max, max(api_target, cfg.api_min + 1))
    if depth <= cfg.scale_down_queue_depth and (
        health_ms is None or health_ms < cfg.health_slow_ms * 0.5
    ):
        api_target = cfg.api_min

    return api_target, worker_target


def _compose_base_cmd(cfg: AutoscaleConfig) -> list[str]:
    cmd = ["docker", "compose"]
    for compose_file in cfg.compose_files:
        cmd.extend(["-f", compose_file])
    return cmd


def apply_scale(cfg: AutoscaleConfig, api_n: int, worker_n: int) -> None:
    cmd = [
        *_compose_base_cmd(cfg),
        "up",
        "-d",
        "--no-recreate",
        "--scale",
        f"api={api_n}",
        "--scale",
        f"worker={worker_n}",
        "api",
        "worker",
        "nginx",
    ]
    logger.info("Scaling to api=%s worker=%s", api_n, worker_n)
    if cfg.dry_run:
        logger.info("DRY-RUN: %s", " ".join(cmd))
        return
    subprocess.run(cmd, cwd=cfg.project_dir, check=True)


def run_loop(cfg: AutoscaleConfig, *, once: bool) -> int:
    if redis is None:
        logger.error("Missing dependency: pip install redis")
        return 2

    client = redis.Redis.from_url(cfg.redis_url, decode_responses=True)
    last_scale_at = 0.0
    current_api = cfg.api_min
    current_worker = cfg.worker_min

    while True:
        depth = queue_depth(client, cfg.queues)
        health_ms = probe_health_ms(cfg.health_url)
        api_n, worker_n = desired_replicas(cfg, depth, health_ms)
        logger.info(
            "depth=%s health_ms=%s -> api=%s worker=%s (current api=%s worker=%s)",
            depth,
            f"{health_ms:.0f}" if health_ms is not None else "n/a",
            api_n,
            worker_n,
            current_api,
            current_worker,
        )

        now = time.monotonic()
        if (api_n, worker_n) != (current_api, current_worker):
            if now - last_scale_at < cfg.cooldown_seconds:
                logger.info("Cooldown active; skip scale")
            else:
                try:
                    apply_scale(cfg, api_n, worker_n)
                    current_api, current_worker = api_n, worker_n
                    last_scale_at = now
                except subprocess.CalledProcessError:
                    logger.exception("docker compose scale failed")

        if once:
            return 0
        time.sleep(cfg.poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Single evaluation pass")
    parser.add_argument("--dry-run", action="store_true", help="Log actions only")
    parser.add_argument(
        "--log-level",
        default=os.getenv("AUTOSCALE_LOG_LEVEL", "INFO"),
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config(dry_run=args.dry_run)
    if cfg.api_max < cfg.api_min or cfg.worker_max < cfg.worker_min:
        logger.error("Invalid min/max replica bounds")
        return 2
    return run_loop(cfg, once=args.once)


if __name__ == "__main__":
    sys.exit(main())
