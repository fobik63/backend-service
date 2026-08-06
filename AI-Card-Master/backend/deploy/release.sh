#!/usr/bin/env bash
# Release helper: preflight → tag previous → build → migrate → health.
# Usage (from backend/):
#   bash deploy/release.sh
#   IMAGE_TAG=20260807T120000 bash deploy/release.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILES=(-f docker-compose.yml -f deploy/docker-compose.scale.yml)
IMAGE_NAME="${IMAGE_NAME:-ai-card-master-backend}"
IMAGE_TAG="${IMAGE_TAG:-$(date -u +%Y%m%dT%H%M%S)}"
MANIFEST_DIR="${MANIFEST_DIR:-deploy/releases}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1/health/ready}"
API_REPLICAS="${API_REPLICAS:-1}"
WORKER_REPLICAS="${WORKER_REPLICAS:-1}"

mkdir -p "$MANIFEST_DIR"

echo "==> Preflight audit"
python deploy/preflight_audit.py --root "$ROOT"

if docker image inspect "${IMAGE_NAME}:current" >/dev/null 2>&1; then
  echo "==> Preserve previous image"
  docker tag "${IMAGE_NAME}:current" "${IMAGE_NAME}:previous"
fi

echo "==> Build ${IMAGE_NAME}:${IMAGE_TAG}"
export IMAGE_TAG
docker compose "${COMPOSE_FILES[@]}" build api worker beat
docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "${IMAGE_NAME}:current"

echo "==> Bring stack up (api=${API_REPLICAS} worker=${WORKER_REPLICAS})"
docker compose "${COMPOSE_FILES[@]}" up -d \
  --scale "api=${API_REPLICAS}" \
  --scale "worker=${WORKER_REPLICAS}"

echo "==> Alembic migrate"
docker compose "${COMPOSE_FILES[@]}" exec -T api alembic upgrade head

echo "==> Health check"
for _ in $(seq 1 30); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    echo "Ready: $HEALTH_URL"
    break
  fi
  sleep 2
done
curl -fsS "$HEALTH_URL" >/dev/null

MANIFEST="${MANIFEST_DIR}/${IMAGE_TAG}.json"
cat >"$MANIFEST" <<EOF
{
  "image": "${IMAGE_NAME}:${IMAGE_TAG}",
  "released_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "api_replicas": ${API_REPLICAS},
  "worker_replicas": ${WORKER_REPLICAS},
  "alembic": "upgrade head"
}
EOF
ln -sfn "$(basename "$MANIFEST")" "${MANIFEST_DIR}/latest.json"
echo "==> Release OK → ${MANIFEST}"
