#!/usr/bin/env bash
# Host firewall lockdown for Dead Man's Switch (plan §37).
# Keeps: loopback, established, WireGuard/VPN, SSH from allowlist, Cloudflare Tunnel (outbound).
# Drops: all other inbound (including public HTTP/HTTPS to origin).
#
# Invoked by DeadMansSwitchService when DEAD_MANS_SWITCH_RUN_HOST_LOCKDOWN=true.
# Requires root. Prefer Cloudflare Tunnel so origin has no public listeners at all.

set -euo pipefail

VPN_IFACE="${VPN_IFACE:-wg0}"
SSH_PORT="${SSH_PORT:-22}"
LOCK_FLAG="/var/run/ai-card-master-lockdown"

if [[ "${EUID}" -ne 0 ]]; then
  echo "lockdown.sh must run as root" >&2
  exit 1
fi

echo "=== Dead Man's Switch host lockdown ==="

# Snapshot current UFW state for unlock.sh
ufw status numbered > "${LOCK_FLAG}.ufw.bak" 2>/dev/null || true
date -u +%Y-%m-%dT%H:%M:%SZ > "${LOCK_FLAG}"

# Default deny inbound; allow loopback + established.
ufw --force reset >/dev/null 2>&1 || true
ufw default deny incoming
ufw default allow outgoing

ufw allow in on lo
ufw allow out on lo

# WireGuard / VPN gateway
if ip link show "${VPN_IFACE}" >/dev/null 2>&1; then
  ufw allow in on "${VPN_IFACE}"
fi

# SSH only from explicit allowlist (comma-separated CIDRs in SSH_ALLOW_CIDRS)
IFS=',' read -ra CIDRS <<< "${SSH_ALLOW_CIDRS:-}"
if [[ ${#CIDRS[@]} -eq 0 || -z "${CIDRS[0]// }" ]]; then
  echo "WARNING: SSH_ALLOW_CIDRS empty — SSH locked to VPN interface only" >&2
else
  for cidr in "${CIDRS[@]}"; do
    cidr_trimmed="$(echo "$cidr" | xargs)"
    [[ -z "$cidr_trimmed" ]] && continue
    ufw allow from "$cidr_trimmed" to any port "${SSH_PORT}" proto tcp comment 'DMS-SSH'
  done
fi

# Do NOT open 80/443/8000/5432/6379/8100 publicly during lockdown.
ufw --force enable
ufw status verbose

echo "Lockdown active. Clear via admin /security/dead-mans-switch/clear + unlock.sh"
