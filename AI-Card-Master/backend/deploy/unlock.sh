#!/usr/bin/env bash
# Restore baseline host firewall after Dead Man's Switch clear (plan §37).
# Re-applies harden_host.sh allowlist (Cloudflare CIDRs + VPN + SSH keys policy).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK_FLAG="/var/run/ai-card-master-lockdown"

if [[ "${EUID}" -ne 0 ]]; then
  echo "unlock.sh must run as root" >&2
  exit 1
fi

echo "=== Dead Man's Switch unlock → re-apply harden_host ==="
rm -f "${LOCK_FLAG}"

if [[ -x "${SCRIPT_DIR}/harden_host.sh" ]]; then
  bash "${SCRIPT_DIR}/harden_host.sh"
else
  echo "harden_host.sh missing; enabling UFW with previous defaults only" >&2
  ufw --force enable || true
fi

echo "Unlock complete."
