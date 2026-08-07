#!/usr/bin/env bash
# Harden origin host: UFW (Cloudflare + VPN only) + SSH keys / IP allowlist (plan §37).
#
# Usage (as root on the API host):
#   export SSH_ALLOW_CIDRS="203.0.113.10/32,10.8.0.0/24"
#   export VPN_IFACE=wg0
#   bash deploy/harden_host.sh
#
# Safe defaults:
#   - deny all inbound except Cloudflare HTTP(S), VPN iface, SSH from allowlist
#   - never publish Postgres/Redis/admin ports
# Prefer Cloudflare Tunnel (docker-compose.tunnel.yml) so 80/443 are also closed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH_PORT="${SSH_PORT:-22}"
VPN_IFACE="${VPN_IFACE:-wg0}"
PUBLIC_HTTP_PORT="${PUBLIC_HTTP_PORT:-80}"
PUBLIC_HTTPS_PORT="${PUBLIC_HTTPS_PORT:-443}"
ENABLE_PUBLIC_HTTP="${ENABLE_PUBLIC_HTTP:-false}"  # true only if NOT using cloudflared tunnel
SSHD_DROPIN="/etc/ssh/sshd_config.d/99-ai-card-master.conf"

if [[ "${EUID}" -ne 0 ]]; then
  echo "harden_host.sh must run as root" >&2
  exit 1
fi

echo "=== AI-Card-Master host harden (plan §37) ==="

# --- SSH: keys only, no passwords ---
mkdir -p /etc/ssh/sshd_config.d
cat > "${SSHD_DROPIN}" <<EOF
# Managed by AI-Card-Master deploy/harden_host.sh — do not edit by hand.
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
AuthenticationMethods publickey
X11Forwarding no
AllowTcpForwarding no
ClientAliveInterval 30
ClientAliveCountMax 3
MaxAuthTries 3
LoginGraceTime 20
EOF

if [[ -n "${SSH_ALLOW_CIDRS:-}" ]]; then
  echo "SSH_ALLOW_CIDRS=${SSH_ALLOW_CIDRS} (enforced via UFW; keep a console/VNC escape hatch)"
fi

if command -v sshd >/dev/null 2>&1; then
  sshd -t && systemctl reload sshd 2>/dev/null || systemctl reload ssh 2>/dev/null || true
fi

# --- UFW baseline ---
apt-get install -y ufw >/dev/null 2>&1 || true
ufw --force reset >/dev/null 2>&1 || true
ufw default deny incoming
ufw default allow outgoing
ufw allow in on lo
ufw allow out on lo

if ip link show "${VPN_IFACE}" >/dev/null 2>&1; then
  ufw allow in on "${VPN_IFACE}" comment 'VPN-gateway'
fi

IFS=',' read -ra CIDRS <<< "${SSH_ALLOW_CIDRS:-}"
for cidr in "${CIDRS[@]}"; do
  cidr_trimmed="$(echo "$cidr" | xargs)"
  [[ -z "$cidr_trimmed" ]] && continue
  ufw allow from "$cidr_trimmed" to any port "${SSH_PORT}" proto tcp comment 'SSH-allowlist'
done

# Cloudflare published IPv4 ranges → origin :80/:443 only when tunnel is NOT used.
# Source: https://www.cloudflare.com/ips-v4
CF_IPV4=(
  173.245.48.0/20 103.21.244.0/22 103.22.200.0/22 103.31.4.0/22
  141.101.64.0/18 108.162.192.0/18 190.93.240.0/20 188.114.96.0/20
  197.234.240.0/22 198.41.128.0/17 162.158.0.0/15 104.16.0.0/13
  104.24.0.0/14 172.64.0.0/13 131.0.72.0/22
)

if [[ "${ENABLE_PUBLIC_HTTP}" == "true" ]]; then
  for cidr in "${CF_IPV4[@]}"; do
    ufw allow from "$cidr" to any port "${PUBLIC_HTTP_PORT}" proto tcp comment 'CF-HTTP'
    ufw allow from "$cidr" to any port "${PUBLIC_HTTPS_PORT}" proto tcp comment 'CF-HTTPS'
  done
  echo "Public HTTP enabled for Cloudflare CIDRs only on :${PUBLIC_HTTP_PORT}/:${PUBLIC_HTTPS_PORT}"
else
  echo "Public HTTP disabled (Cloudflare Tunnel mode). Origin ports stay closed."
fi

# Explicitly refuse common accidental exposures
for port in 5432 6379 8000 8100 15672 2375 2376; do
  ufw deny "${port}/tcp" comment "deny-internal-${port}" || true
done

ufw --force enable
ufw status verbose

# Optional WireGuard reminder
if [[ ! -f /etc/wireguard/${VPN_IFACE}.conf ]]; then
  echo "NOTE: Install WireGuard VPN gateway (${VPN_IFACE}) for admin/SSH access."
  echo "      See deploy/PRIVATE_TUNNEL.md"
fi

# Install lockdown/unlock helpers
install -m 750 "${SCRIPT_DIR}/lockdown.sh" /usr/local/sbin/ai-card-lockdown.sh
install -m 750 "${SCRIPT_DIR}/unlock.sh" /usr/local/sbin/ai-card-unlock.sh

echo "Harden complete."
echo "Next: cloudflared tunnel (deploy/docker-compose.tunnel.yml) + DEAD_MANS_SWITCH_* in .env"
