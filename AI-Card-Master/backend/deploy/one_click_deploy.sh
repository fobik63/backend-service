#!/usr/bin/env bash
# One-click full-stack deploy on a fresh host (plan §40).
# Wraps deploy/one_click_deploy.py — same flags.
#
# Usage (from backend/):
#   bash deploy/one_click_deploy.sh --profile production_tunnel
#   bash deploy/one_click_deploy.sh --dry-run --profile production
#   bash deploy/one_click_deploy.sh --profile disaster_recovery \
#        --restore 's3://vault/pg/ai_card_master-….dump.enc'
#
# Bare metal / any cloud (no Terraform):
#   1. Install Docker Engine + compose plugin
#   2. Clone repo, copy .env
#   3. Run this script
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy from .env.example and fill secrets first." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose plugin is required" >&2
  exit 1
fi

exec python3 deploy/one_click_deploy.py "$@"
