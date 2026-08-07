#!/usr/bin/env bash
# Encrypted PostgreSQL backup → isolated S3 vault (plan §36 / §63).
# Schedule: daily by default (BACKUP_INTERVAL_SECONDS=86400 in compose);
# set 21600 for every-6h RPO. See deploy/docker-compose.backup.yml.
#
# Required env:
#   DATABASE_URL or PGHOST/PGUSER/PGPASSWORD/PGDATABASE
#   BACKUP_S3_ENDPOINT_URL, BACKUP_S3_ACCESS_KEY_ID, BACKUP_S3_SECRET_ACCESS_KEY
#   BACKUP_S3_BUCKET, BACKUP_ENCRYPTION_KEY (≥32 chars)
# Optional:
#   BACKUP_S3_REGION, BACKUP_RETENTION_DAYS (default 14), BACKUP_PREFIX
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

log() { printf '[pg-backup] %s\n' "$*"; }
die() { printf '[pg-backup] ERROR: %s\n' "$*" >&2; exit 1; }

need() { [[ -n "${!1:-}" ]] || die "Missing env: $1"; }

need BACKUP_S3_ENDPOINT_URL
need BACKUP_S3_ACCESS_KEY_ID
need BACKUP_S3_SECRET_ACCESS_KEY
need BACKUP_S3_BUCKET
need BACKUP_ENCRYPTION_KEY

KEY_LEN="${#BACKUP_ENCRYPTION_KEY}"
[[ "$KEY_LEN" -ge 32 ]] || die "BACKUP_ENCRYPTION_KEY must be ≥ 32 characters"

RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
PREFIX="${BACKUP_PREFIX:-pg/ai_card_master}"
REGION="${BACKUP_S3_REGION:-ru-1}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

DUMP_PATH="$WORK/db.dump"
ENC_PATH="$WORK/db.dump.enc"
OBJECT_KEY="${PREFIX}/${STAMP}.dump.enc"

# --- resolve connection ---
if [[ -n "${DATABASE_URL:-}" ]]; then
  # Strip SQLAlchemy driver prefix if present.
  URL="${DATABASE_URL/postgresql+asyncpg:\/\//postgresql:\/\/}"
  URL="${URL/postgresql+psycopg:\/\//postgresql:\/\/}"
  export PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE
  # Prefer parsing via Python for robustness (URL special chars).
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

command -v pg_dump >/dev/null || die "pg_dump not found"
command -v openssl >/dev/null || die "openssl not found"
command -v aws >/dev/null || die "aws CLI not found (use amazon/aws-cli image or install awscli)"

log "Dumping database ${PGDATABASE}@${PGHOST}…"
pg_dump -Fc --no-owner --no-acl -f "$DUMP_PATH"

log "Encrypting (AES-256-CBC)…"
# Key derivation from passphrase; salt stored in ciphertext header.
openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
  -in "$DUMP_PATH" -out "$ENC_PATH" \
  -pass "env:BACKUP_ENCRYPTION_KEY"
rm -f "$DUMP_PATH"

export AWS_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_ACCESS_KEY"
export AWS_DEFAULT_REGION="$REGION"

log "Uploading s3://${BACKUP_S3_BUCKET}/${OBJECT_KEY}"
aws --endpoint-url "$BACKUP_S3_ENDPOINT_URL" s3 cp "$ENC_PATH" \
  "s3://${BACKUP_S3_BUCKET}/${OBJECT_KEY}" \
  --only-show-errors

# Manifest for ops / ransomware RTO drills
MANIFEST="$WORK/manifest.json"
cat >"$MANIFEST" <<EOF
{
  "object_key": "${OBJECT_KEY}",
  "bucket": "${BACKUP_S3_BUCKET}",
  "database": "${PGDATABASE}",
  "created_at_utc": "${STAMP}",
  "format": "pg_dump-Fc+openssl-aes-256-cbc-pbkdf2",
  "retention_days": ${RETENTION_DAYS}
}
EOF
aws --endpoint-url "$BACKUP_S3_ENDPOINT_URL" s3 cp "$MANIFEST" \
  "s3://${BACKUP_S3_BUCKET}/${PREFIX}/latest-manifest.json" \
  --only-show-errors

log "Pruning backups older than ${RETENTION_DAYS} days…"
CUTOFF="$(date -u -d "-${RETENTION_DAYS} days" +%Y%m%dT%H%M%SZ 2>/dev/null || date -u -v-"${RETENTION_DAYS}"d +%Y%m%dT%H%M%SZ)"
# List and delete stale objects under prefix (best-effort).
while IFS= read -r key; do
  [[ -z "$key" ]] && continue
  base="$(basename "$key")"
  stamp="${base%.dump.enc}"
  if [[ "$stamp" < "$CUTOFF" ]]; then
    log "Delete stale $key"
    aws --endpoint-url "$BACKUP_S3_ENDPOINT_URL" s3 rm "s3://${BACKUP_S3_BUCKET}/${key}" --only-show-errors || true
  fi
done < <(
  aws --endpoint-url "$BACKUP_S3_ENDPOINT_URL" s3api list-objects-v2 \
    --bucket "$BACKUP_S3_BUCKET" --prefix "${PREFIX}/" \
    --query "Contents[?ends_with(Key, '.dump.enc')].Key" --output text 2>/dev/null | tr '\t' '\n'
)

log "OK ${OBJECT_KEY}"

# Optional Telegram success/fail is left to the wrapper (compose health).
if [[ -n "${TELEGRAM_ERROR_BOT_TOKEN:-}" && -n "${TELEGRAM_ERROR_CHAT_ID:-}" && "${BACKUP_NOTIFY_SUCCESS:-false}" == "true" ]]; then
  curl -fsS -X POST "https://api.telegram.org/bot${TELEGRAM_ERROR_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_ERROR_CHAT_ID}" \
    --data-urlencode "text=✅ PG backup OK: ${OBJECT_KEY}" >/dev/null || true
fi
