#!/bin/sh
# Wait for Postgres + Redis, apply Alembic migrations, then exec the container CMD.
# Used as the Docker ENTRYPOINT so uvicorn/gunicorn/celery always start against a ready stack.
set -eu

MAX_WAIT_SECONDS="${DEPENDENCY_WAIT_SECONDS:-30}"

log() {
  printf '%s\n' "$*"
}

die() {
  printf 'entrypoint ERROR: %s\n' "$*" >&2
  exit 1
}

_b64decode() {
  python -c 'import base64,sys; sys.stdout.buffer.write(base64.b64decode(sys.argv[1]))' "$1"
}

load_postgres_env() {
  # Outputs: host\nport\nuser\ndb\npassword_b64
  _db_meta="$(
    python - <<'PY'
from __future__ import annotations

import base64
import os
from urllib.parse import unquote, urlparse

raw = os.environ.get("DATABASE_URL", "").strip()
if not raw:
    raise SystemExit("DATABASE_URL is not set")

parsed = urlparse(raw)
if not parsed.hostname:
    raise SystemExit(f"DATABASE_URL has no host: {raw!r}")

host = parsed.hostname
port = str(parsed.port or 5432)
user = unquote(parsed.username or "ai_card")
password = unquote(parsed.password) if parsed.password else ""
db = unquote((parsed.path or "/ai_card_master").lstrip("/") or "ai_card_master")
db = db.split("?", 1)[0]
password_b64 = base64.b64encode(password.encode("utf-8")).decode("ascii")
print("\n".join([host, port, user, db, password_b64]))
PY
  )"
  PGHOST="$(printf '%s\n' "$_db_meta" | sed -n '1p')"
  PGPORT="$(printf '%s\n' "$_db_meta" | sed -n '2p')"
  PGUSER="$(printf '%s\n' "$_db_meta" | sed -n '3p')"
  PGDATABASE="$(printf '%s\n' "$_db_meta" | sed -n '4p')"
  PGPASSWORD="$(_b64decode "$(printf '%s\n' "$_db_meta" | sed -n '5p')")"
  export PGHOST PGPORT PGUSER PGDATABASE PGPASSWORD
}

load_redis_env() {
  _redis_meta="$(
    python - <<'PY'
from __future__ import annotations

import base64
import os
from urllib.parse import unquote, urlparse

raw = os.environ.get("REDIS_URL", "redis://localhost:6379/0").strip()
parsed = urlparse(raw)
if not parsed.hostname:
    raise SystemExit(f"REDIS_URL has no host: {raw!r}")

host = parsed.hostname
port = str(parsed.port or 6379)
password = unquote(parsed.password) if parsed.password else ""
password_b64 = base64.b64encode(password.encode("utf-8")).decode("ascii")
print("\n".join([host, port, password_b64]))
PY
  )"
  REDIS_HOST="$(printf '%s\n' "$_redis_meta" | sed -n '1p')"
  REDIS_PORT="$(printf '%s\n' "$_redis_meta" | sed -n '2p')"
  REDIS_PASSWORD="$(_b64decode "$(printf '%s\n' "$_redis_meta" | sed -n '3p')")"
}

wait_for_postgres() {
  load_postgres_env
  log "Waiting for Postgres at ${PGHOST}:${PGPORT}/${PGDATABASE} (up to ${MAX_WAIT_SECONDS}s)..."
  elapsed=0
  while [ "$elapsed" -lt "$MAX_WAIT_SECONDS" ]; do
    if pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" >/dev/null 2>&1; then
      log "Postgres is ready."
      return 0
    fi
    elapsed=$((elapsed + 1))
    sleep 1
  done
  die "Postgres did not become ready within ${MAX_WAIT_SECONDS}s (${PGHOST}:${PGPORT})"
}

wait_for_redis() {
  load_redis_env
  log "Waiting for Redis at ${REDIS_HOST}:${REDIS_PORT} (up to ${MAX_WAIT_SECONDS}s)..."
  elapsed=0
  while [ "$elapsed" -lt "$MAX_WAIT_SECONDS" ]; do
    if [ -n "${REDIS_PASSWORD}" ]; then
      if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" --no-auth-warning ping 2>/dev/null | grep -q PONG; then
        log "Redis is ready."
        return 0
      fi
    else
      if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping 2>/dev/null | grep -q PONG; then
        log "Redis is ready."
        return 0
      fi
    fi
    elapsed=$((elapsed + 1))
    sleep 1
  done
  die "Redis did not become ready within ${MAX_WAIT_SECONDS}s (${REDIS_HOST}:${REDIS_PORT})"
}

wait_for_postgres
wait_for_redis

log "Applying Alembic migrations (upgrade head)..."
alembic upgrade head
log "Alembic migrations complete."

exec "$@"
