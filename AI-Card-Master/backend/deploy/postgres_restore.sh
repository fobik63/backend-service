#!/usr/bin/env bash
# Restore PostgreSQL from an isolated encrypted backup (plan §36).
# Usage:
#   bash deploy/postgres_restore.sh s3://BUCKET/pg/ai_card_master/STAMP.dump.enc
#   bash deploy/postgres_restore.sh /path/to/local.dump.enc
#
# WARNING: drops/recreates target DB objects via pg_restore --clean.
# Rotate app secrets after ransomware recovery.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

die() { printf '[pg-restore] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[pg-restore] %s\n' "$*"; }

SRC="${1:-}"
[[ -n "$SRC" ]] || die "Usage: $0 <s3://bucket/key | /local/file.dump.enc>"

need() { [[ -n "${!1:-}" ]] || die "Missing env: $1"; }
need BACKUP_ENCRYPTION_KEY

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
ENC="$WORK/db.dump.enc"
DUMP="$WORK/db.dump"

if [[ "$SRC" == s3://* ]]; then
  need BACKUP_S3_ENDPOINT_URL
  need BACKUP_S3_ACCESS_KEY_ID
  need BACKUP_S3_SECRET_ACCESS_KEY
  export AWS_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY_ID"
  export AWS_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_ACCESS_KEY"
  export AWS_DEFAULT_REGION="${BACKUP_S3_REGION:-ru-1}"
  log "Downloading $SRC"
  aws --endpoint-url "$BACKUP_S3_ENDPOINT_URL" s3 cp "$SRC" "$ENC" --only-show-errors
else
  [[ -f "$SRC" ]] || die "File not found: $SRC"
  cp "$SRC" "$ENC"
fi

log "Decrypting…"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -in "$ENC" -out "$DUMP" \
  -pass "env:BACKUP_ENCRYPTION_KEY"

if [[ -n "${DATABASE_URL:-}" ]]; then
  URL="${DATABASE_URL/postgresql+asyncpg:\/\//postgresql:\/\/}"
  URL="${URL/postgresql+psycopg:\/\//postgresql:\/\/}"
  eval "$(python3 - <<'PY' "$URL"
import sys
from urllib.parse import urlparse, unquote
u = urlparse(sys.argv[1])
print(f'export PGHOST={u.hostname!r}')
print(f'export PGPORT={u.port or 5432}')
print(f'export PGUSER={unquote(u.username or "")!r}')
print(f'export PGPASSWORD={unquote(u.password or "")!r}')
db = (u.path or "/").lstrip("/") or "postgres"
print(f'export PGDATABASE={db!r}')
PY
)"
else
  need PGHOST
  need PGUSER
  need PGPASSWORD
  need PGDATABASE
  export PGPORT="${PGPORT:-5432}"
fi

log "Restoring into ${PGDATABASE}@${PGHOST} (pg_restore --clean --if-exists)…"
pg_restore --clean --if-exists --no-owner --no-acl -d "$PGDATABASE" "$DUMP"

log "OK — verify /health/ready and rotate secrets if this was a ransomware recovery."
