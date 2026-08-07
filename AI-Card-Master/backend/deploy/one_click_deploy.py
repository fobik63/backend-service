#!/usr/bin/env python3
"""Infrastructure-as-Code one-click deploy orchestrator (plan §40).

Describes the full runtime stack via deploy/inventory.json + Docker Compose
overlays, and produces / executes the bootstrap sequence so a clean host can
become a production replica in ≈10 minutes.

Usage (from backend/):
  python deploy/one_click_deploy.py --dry-run --profile production
  python deploy/one_click_deploy.py --profile production_tunnel
  python deploy/one_click_deploy.py --profile disaster_recovery --restore s3://vault/...dump.enc

Exit codes: 0 ok, 1 validation/runtime error, 2 bad args.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import URLError
from urllib.request import urlopen

DEPLOY_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = DEPLOY_DIR.parent
DEFAULT_INVENTORY = DEPLOY_DIR / "inventory.json"

PLACEHOLDER_MARKERS = (
    "changeme_in_production",
    "replace_with_",
    "YOUR_ORG",
    "replace_with_a_strong",
)


@dataclass(frozen=True, slots=True)
class DeployPlan:
    """Resolved compose file list + scale + optional restore URI."""

    profile: str
    compose_files: tuple[str, ...]
    api_replicas: int
    worker_replicas: int
    image_tag: str
    health_url: str
    restore_uri: str | None
    skip_harden: bool
    skip_migrate: bool
    run_preflight: bool


def load_inventory(path: Path = DEFAULT_INVENTORY) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("inventory must be a JSON object")
    return raw


def resolve_compose_files(
    inventory: Mapping[str, Any],
    profile: str,
) -> tuple[str, ...]:
    compose = inventory["compose"]
    overlays: Mapping[str, str] = compose["overlays"]
    profiles: Mapping[str, Sequence[str]] = compose["profiles"]
    if profile not in profiles:
        known = ", ".join(sorted(profiles))
        raise KeyError(f"unknown profile {profile!r}; expected one of: {known}")

    files: list[str] = []
    for key in profiles[profile]:
        if key == "base":
            files.append(str(compose["base"]))
        else:
            if key not in overlays:
                raise KeyError(f"profile {profile!r} references missing overlay {key!r}")
            files.append(str(overlays[key]))
    return tuple(files)


def parse_env_file(path: Path) -> dict[str, str]:
    """Minimal .env reader (KEY=VALUE, ignores comments/blank)."""
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            result[key] = value
    return result


def validate_production_env(
    inventory: Mapping[str, Any],
    env: Mapping[str, str],
    *,
    profile: str,
) -> list[str]:
    """Return human-readable problems (empty = ok)."""
    problems: list[str] = []
    required = list(inventory.get("required_env_production", []))
    # DATABASE_URL / REDIS_URL are injected by compose for containers; on host
    # we only require secrets that must exist in .env.
    host_required = [
        k
        for k in required
        if k
        not in {
            "DATABASE_URL",
            "REDIS_URL",
        }
    ]
    for key in host_required:
        value = env.get(key, "").strip()
        if not value:
            problems.append(f"missing required env: {key}")
            continue
        if any(marker in value for marker in PLACEHOLDER_MARKERS):
            problems.append(f"placeholder value for {key}")

    if env.get("APP_ENV", "").strip().lower() not in {"production", "prod", "staging"}:
        # Allow missing APP_ENV — compose defaults to production.
        pass

    compose_files = resolve_compose_files(inventory, profile)

    if any("tunnel" in path for path in compose_files):
        token = env.get("CLOUDFLARE_TUNNEL_TOKEN", "").strip()
        if not token:
            problems.append("CLOUDFLARE_TUNNEL_TOKEN required for tunnel profile")

    if any("backup" in path for path in compose_files):
        for key in (
            "BACKUP_S3_ENDPOINT_URL",
            "BACKUP_S3_ACCESS_KEY_ID",
            "BACKUP_S3_SECRET_ACCESS_KEY",
            "BACKUP_S3_BUCKET",
            "BACKUP_ENCRYPTION_KEY",
        ):
            value = env.get(key, "").strip()
            if not value or any(marker in value for marker in PLACEHOLDER_MARKERS):
                problems.append(f"backup overlay needs real {key}")

    return problems


def build_plan(
    inventory: Mapping[str, Any],
    *,
    profile: str,
    env: Mapping[str, str],
    restore_uri: str | None = None,
    skip_harden: bool = True,
    skip_migrate: bool = False,
    run_preflight: bool = True,
) -> DeployPlan:
    compose_files = resolve_compose_files(inventory, profile)
    api_replicas = max(1, int(env.get("API_REPLICAS", "1") or "1"))
    worker_replicas = max(1, int(env.get("WORKER_REPLICAS", "1") or "1"))
    image_tag = (env.get("IMAGE_TAG") or "current").strip() or "current"
    port = (env.get("PUBLIC_HTTP_PORT") or "80").strip() or "80"
    override = (env.get("ONE_CLICK_HEALTH_URL") or "").strip()
    if override:
        health_url = override
    elif any("tunnel" in path for path in compose_files):
        # No host ports published — sentinel consumed by run_deploy (compose exec).
        health_url = "compose://api/health/ready"
    else:
        health_url = f"http://127.0.0.1:{port}/health/ready"
    return DeployPlan(
        profile=profile,
        compose_files=compose_files,
        api_replicas=api_replicas,
        worker_replicas=worker_replicas,
        image_tag=image_tag,
        health_url=health_url,
        restore_uri=restore_uri,
        skip_harden=skip_harden,
        skip_migrate=skip_migrate,
        run_preflight=run_preflight,
    )


def compose_argv(plan: DeployPlan) -> list[str]:
    args = ["docker", "compose"]
    for path in plan.compose_files:
        args.extend(["-f", path])
    return args


def render_commands(plan: DeployPlan, *, root: Path = BACKEND_ROOT) -> list[list[str]]:
    """Pure command list for dry-run / tests (no side effects)."""
    cmds: list[list[str]] = []
    env_prefix = {"IMAGE_TAG": plan.image_tag}

    if plan.run_preflight:
        cmds.append([sys.executable, str(DEPLOY_DIR / "preflight_audit.py"), "--root", str(root)])

    base = compose_argv(plan)
    cmds.append([*base, "build", "api", "worker", "beat"])
    # Tag current for rollback compatibility with release.sh
    cmds.append(
        [
            "docker",
            "tag",
            f"ai-card-master-backend:{plan.image_tag}",
            "ai-card-master-backend:current",
        ]
    )

    up = [
        *base,
        "up",
        "-d",
        "--remove-orphans",
        "--scale",
        f"api={plan.api_replicas}",
        "--scale",
        f"worker={plan.worker_replicas}",
    ]
    cmds.append(up)

    if plan.restore_uri:
        cmds.append(
            [
                "bash",
                str(DEPLOY_DIR / "postgres_restore.sh"),
                plan.restore_uri,
            ]
        )

    if not plan.skip_migrate:
        cmds.append([*base, "exec", "-T", "api", "alembic", "upgrade", "head"])

    if not plan.skip_harden:
        cmds.append(["bash", str(DEPLOY_DIR / "harden_host.sh")])

    # health is polled separately
    _ = env_prefix
    return cmds


def estimate_rto_minutes(plan: DeployPlan) -> float:
    """Conservative wall-clock budget for a warm cache / cold image pull."""
    minutes = 3.0  # docker pull + compose up
    minutes += 1.5 if plan.run_preflight else 0.0
    minutes += 1.0  # migrate
    minutes += 2.0 if plan.restore_uri else 0.0
    minutes += 1.0  # health wait
    minutes += 0.5 if not plan.skip_harden else 0.0
    # scale replicas add little once images are local
    minutes += 0.25 * max(0, plan.api_replicas + plan.worker_replicas - 2)
    return round(minutes, 1)


def wait_for_health(url: str, *, timeout_seconds: float = 180.0, interval: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=5) as resp:  # noqa: S310 — operator health URL
                if 200 <= getattr(resp, "status", 200) < 300:
                    return True
        except (URLError, OSError, TimeoutError):
            pass
        time.sleep(interval)
    return False


def wait_for_compose_health(
    plan: DeployPlan,
    *,
    cwd: Path,
    timeout_seconds: float = 180.0,
    interval: float = 3.0,
    dry_run: bool = False,
) -> bool:
    """Probe /health/ready inside an api container (tunnel / no host ports)."""
    if dry_run:
        return True
    cmd = [
        *compose_argv(plan),
        "exec",
        "-T",
        "api",
        "curl",
        "-fsS",
        "http://127.0.0.1:8000/health/ready",
    ]
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        proc = subprocess.run(cmd, cwd=str(cwd), check=False, capture_output=True)
        if proc.returncode == 0:
            return True
        time.sleep(interval)
    return False


def _run(cmd: Sequence[str], *, cwd: Path, dry_run: bool, env: Mapping[str, str]) -> None:
    printable = " ".join(cmd)
    print(f"==> {printable}")
    if dry_run:
        return
    merged = {**os.environ, **dict(env)}
    subprocess.run(list(cmd), cwd=str(cwd), check=True, env=merged)


def run_deploy(
    plan: DeployPlan,
    *,
    root: Path = BACKEND_ROOT,
    dry_run: bool = False,
    env: Mapping[str, str] | None = None,
) -> None:
    runtime_env = {
        "IMAGE_TAG": plan.image_tag,
        "API_REPLICAS": str(plan.api_replicas),
        "WORKER_REPLICAS": str(plan.worker_replicas),
        **(dict(env) if env else {}),
    }
    for cmd in render_commands(plan, root=root):
        # docker tag may fail on dry first build — skip soft failures only for tag in dry-run
        try:
            _run(cmd, cwd=root, dry_run=dry_run, env=runtime_env)
        except subprocess.CalledProcessError:
            if dry_run:
                raise
            # Allow tag to be retried after build created the image
            if cmd[:2] == ["docker", "tag"]:
                print("warn: docker tag failed (image may already be :current)", file=sys.stderr)
                continue
            raise

    print(f"==> Health probe {plan.health_url}")
    if dry_run:
        print("(dry-run) skip health wait")
        return
    if plan.health_url.startswith("compose://"):
        ok = wait_for_compose_health(plan, cwd=root, dry_run=False)
    else:
        ok = wait_for_health(plan.health_url)
    if not ok:
        raise RuntimeError(f"health check timed out: {plan.health_url}")
    print("Ready.")


def inventory_service_names(inventory: Mapping[str, Any]) -> list[str]:
    return [str(s["name"]) for s in inventory.get("services", [])]


def assert_inventory_contracts(inventory: Mapping[str, Any]) -> None:
    """Structural guarantees used by unit tests and CI."""
    assert inventory.get("plan_section") == 40
    assert float(inventory.get("target_rto_minutes", 99)) <= 10
    compose = inventory["compose"]
    assert "docker-compose.yml" in str(compose["base"])
    for key in ("scale", "backup", "tunnel"):
        assert key in compose["overlays"]
    for profile in ("production", "production_tunnel", "disaster_recovery"):
        assert profile in compose["profiles"]
    names = set(inventory_service_names(inventory))
    for required in ("postgres", "redis", "api", "worker", "beat", "nginx", "pg-backup"):
        assert required in names, f"missing service {required}"
    steps = inventory.get("bootstrap_steps", [])
    assert "compose_up" in steps and "alembic_upgrade" in steps


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI-Card-Master one-click IaC deploy (plan §40)")
    parser.add_argument(
        "--profile",
        default=os.getenv("DEPLOY_PROFILE", "production"),
        help="inventory compose profile (production|production_tunnel|disaster_recovery|minimal)",
    )
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--env-file", type=Path, default=BACKEND_ROOT / ".env")
    parser.add_argument("--restore", default=None, help="Optional s3://… encrypted dump URI")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-harden", action="store_true", default=True)
    parser.add_argument("--with-harden", action="store_true", help="Run harden_host.sh after up")
    parser.add_argument("--skip-migrate", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--skip-env-check", action="store_true")
    parser.add_argument("--print-inventory", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not shutil.which("docker") and not args.dry_run and not args.print_inventory:
        print("docker not found on PATH", file=sys.stderr)
        return 1

    inventory = load_inventory(args.inventory)
    assert_inventory_contracts(inventory)

    if args.print_inventory:
        print(json.dumps(inventory, indent=2, ensure_ascii=False))
        return 0

    env = parse_env_file(args.env_file)
    # Overlay process env for CI / operators
    for key, value in os.environ.items():
        if key.isupper():
            env.setdefault(key, value)

    if not args.skip_env_check and not args.dry_run:
        problems = validate_production_env(inventory, env, profile=args.profile)
        if problems:
            print("Environment validation failed:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
    elif args.dry_run and not args.skip_env_check:
        problems = validate_production_env(inventory, env, profile=args.profile)
        if problems:
            print("warn: env issues (dry-run continues):")
            for problem in problems:
                print(f"  - {problem}")

    skip_harden = not args.with_harden
    plan = build_plan(
        inventory,
        profile=args.profile,
        env=env,
        restore_uri=args.restore,
        skip_harden=skip_harden,
        skip_migrate=args.skip_migrate,
        run_preflight=not args.skip_preflight,
    )

    rto = estimate_rto_minutes(plan)
    print(f"profile={plan.profile} files={list(plan.compose_files)}")
    print(f"estimated_rto_minutes={rto} (budget ≤ {inventory['target_rto_minutes']})")
    if rto > float(inventory["target_rto_minutes"]):
        print("warn: estimate exceeds 10m budget (cold image pulls?)", file=sys.stderr)

    try:
        run_deploy(plan, root=BACKEND_ROOT, dry_run=args.dry_run, env=env)
    except (subprocess.CalledProcessError, RuntimeError, KeyError, ValueError) as exc:
        print(f"deploy failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
