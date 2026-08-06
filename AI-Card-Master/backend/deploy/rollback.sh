#!/usr/bin/env bash
# Fast rollback to the previous container image (plan §24).
# Usage (from backend/):
#   bash deploy/rollback.sh
#   bash deploy/rollback.sh --with-db-downgrade -1
#   bash deploy/rollback.sh --to 20260807T120000
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILES=(-f docker-compose.yml -f deploy/docker-compose.scale.yml)
IMAGE_NAME="${IMAGE_NAME:-ai-card-master-backend}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1/health/ready}"
API_REPLICAS="${API_REPLICAS:-1}"
WORKER_REPLICAS="${WORKER_REPLICAS:-1}"
TARGET_TAG="previous"
DB_DOWNGRADE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --to)
      TARGET_TAG="${2:?tag required}"
      shift 2
      ;;
    --with-db-downgrade)
      DB_DOWNGRADE="${2:--1}"
      shift 2
      ;;
    -h|--help)
      sed -n '1,12p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if ! docker image inspect "${IMAGE_NAME}:${TARGET_TAG}" >/dev/null 2>&1; then
  echo "Rollback image missing: ${IMAGE_NAME}:${TARGET_TAG}" >&2
  echo "Available tags:" >&2
  docker images "${IMAGE_NAME}" --format '{{.Tag}}' >&2 || true
  exit 1
fi

echo "==> Rolling back to ${IMAGE_NAME}:${TARGET_TAG}"

# Keep a safety copy of the failed current build.
if docker image inspect "${IMAGE_NAME}:current" >/dev/null 2>&1; then
  docker tag "${IMAGE_NAME}:current" "${IMAGE_NAME}:failed-$(date -u +%Y%m%dT%H%M%S)"
fi

docker tag "${IMAGE_NAME}:${TARGET_TAG}" "${IMAGE_NAME}:current"
export IMAGE_TAG=current

docker compose "${COMPOSE_FILES[@]}" up -d \
  --force-recreate \
  --scale "api=${API_REPLICAS}" \
  --scale "worker=${WORKER_REPLICAS}" \
  api worker beat nginx

if [[ -n "$DB_DOWNGRADE" ]]; then
  echo "==> Alembic downgrade ${DB_DOWNGRADE}"
  docker compose "${COMPOSE_FILES[@]}" exec -T api alembic downgrade "$DB_DOWNGRADE"
fi

echo "==> Health check"
ok=0
for _ in $(seq 1 30); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 2
done

if [[ "$ok" -ne 1 ]]; then
  echo "Rollback health check failed: $HEALTH_URL" >&2
  exit 1
fi

mkdir -p deploy/releases
cat >"deploy/releases/rollback-$(date -u +%Y%m%dT%H%M%S).json" <<EOF
{
  "rolled_back_to": "${IMAGE_NAME}:${TARGET_TAG}",
  "db_downgrade": $( [[ -n "$DB_DOWNGRADE" ]] && printf '"%s"' "$DB_DOWNGRADE" || printf 'null' ),
  "at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo "==> Rollback OK"
curl -fsS "$HEALTH_URL" || true
