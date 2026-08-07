"""Unit tests for IaC inventory + one-click deploy (plan §40)."""

from __future__ import annotations

import importlib.util
import json
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


iac = _load("one_click_deploy_mod", "one_click_deploy.py")


def test_inventory_json_contracts() -> None:
    inventory = iac.load_inventory(DEPLOY_DIR / "inventory.json")
    iac.assert_inventory_contracts(inventory)
    assert inventory["target_rto_minutes"] <= 10
    names = iac.inventory_service_names(inventory)
    assert names.index("postgres") < names.index("api")


def test_resolve_compose_profiles() -> None:
    inventory = iac.load_inventory()
    prod = iac.resolve_compose_files(inventory, "production")
    assert prod[0] == "docker-compose.yml"
    assert any("scale" in p for p in prod)
    assert any("backup" in p for p in prod)
    assert not any("tunnel" in p for p in prod)

    tunnel = iac.resolve_compose_files(inventory, "production_tunnel")
    assert any("tunnel" in p for p in tunnel)

    dr = iac.resolve_compose_files(inventory, "disaster_recovery")
    assert any("backup" in p for p in dr)


def test_validate_rejects_placeholders() -> None:
    inventory = iac.load_inventory()
    problems = iac.validate_production_env(
        inventory,
        {
            "POSTGRES_PASSWORD": "changeme_in_production",
            "JWT_SECRET_KEY": "replace_with_a_strong_random_secret_at_least_64_characters_long",
            "ADMIN_PANEL_TOKEN_SECRET": "short",
        },
        profile="minimal",
    )
    assert any("POSTGRES_PASSWORD" in p for p in problems)
    assert any("JWT_SECRET_KEY" in p for p in problems)


def test_validate_tunnel_requires_token() -> None:
    inventory = iac.load_inventory()
    env = {
        "POSTGRES_PASSWORD": "super-secret-db-password-32chars",
        "JWT_SECRET_KEY": "x" * 64,
        "ADMIN_PANEL_TOKEN_SECRET": "y" * 32,
        "BACKUP_S3_ENDPOINT_URL": "https://s3.example",
        "BACKUP_S3_ACCESS_KEY_ID": "AKIAEXAMPLE",
        "BACKUP_S3_SECRET_ACCESS_KEY": "secretsecretsecret",
        "BACKUP_S3_BUCKET": "vault",
        "BACKUP_ENCRYPTION_KEY": "z" * 32,
    }
    problems = iac.validate_production_env(
        inventory, env, profile="production_tunnel"
    )
    assert any("CLOUDFLARE_TUNNEL_TOKEN" in p for p in problems)

    env["CLOUDFLARE_TUNNEL_TOKEN"] = "cf-tunnel-token-value"
    assert iac.validate_production_env(inventory, env, profile="production_tunnel") == []


def test_build_plan_and_rto_budget() -> None:
    inventory = iac.load_inventory()
    plan = iac.build_plan(
        inventory,
        profile="production",
        env={"API_REPLICAS": "2", "WORKER_REPLICAS": "2", "IMAGE_TAG": "20260807"},
        restore_uri=None,
    )
    assert plan.api_replicas == 2
    assert plan.image_tag == "20260807"
    assert any("scale" in f for f in plan.compose_files)
    assert iac.estimate_rto_minutes(plan) <= float(inventory["target_rto_minutes"])


def test_render_commands_dry_sequence() -> None:
    inventory = iac.load_inventory()
    plan = iac.build_plan(
        inventory,
        profile="disaster_recovery",
        env={"API_REPLICAS": "1", "WORKER_REPLICAS": "1"},
        restore_uri="s3://vault/pg/demo.dump.enc",
        skip_harden=True,
        skip_migrate=False,
        run_preflight=True,
    )
    cmds = iac.render_commands(plan)
    flat = [" ".join(c) for c in cmds]
    assert any("preflight_audit.py" in row for row in flat)
    assert any(c[0:3] == ["docker", "compose", "-f"] and "build" in c for c in cmds)
    assert any("postgres_restore.sh" in row for row in flat)
    assert any("alembic" in row for row in flat)
    assert any("--scale" in c for c in cmds)


def test_terraform_module_files_exist() -> None:
    tf = DEPLOY_DIR / "terraform"
    for name in (
        "versions.tf",
        "providers.tf",
        "variables.tf",
        "main.tf",
        "firewall.tf",
        "outputs.tf",
        "cloud-init.yaml.tftpl",
        "terraform.tfvars.example",
    ):
        assert (tf / name).is_file(), name
    main = (tf / "main.tf").read_text(encoding="utf-8")
    assert "hcloud_server" in main
    assert "primary" in main
    assert "secondary" in main
    firewall = (tf / "firewall.tf").read_text(encoding="utf-8")
    assert "hcloud_firewall" in firewall
    # Postgres/Redis must never be opened in TF firewall
    assert "5432" not in firewall
    assert "6379" not in firewall


def test_compose_stack_files_exist() -> None:
    assert (BACKEND_ROOT / "docker-compose.yml").is_file()
    inventory = json.loads((DEPLOY_DIR / "inventory.json").read_text(encoding="utf-8"))
    for overlay in inventory["compose"]["overlays"].values():
        assert (BACKEND_ROOT / overlay).is_file(), overlay


def test_cli_print_inventory_exit_zero() -> None:
    code = iac.main(["--print-inventory"])
    assert code == 0


def test_cli_dry_run_skip_env() -> None:
    code = iac.main(
        [
            "--dry-run",
            "--skip-env-check",
            "--skip-preflight",
            "--profile",
            "minimal",
        ]
    )
    assert code == 0
