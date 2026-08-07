# Private Tunnel & Infrastructure Hardening (plan §37)

Цель: **origin IP скрыт**; публичный трафик только через Cloudflare; админ/SSH — только через VPN + ключи; Dead Man's Switch режет внешний доступ при брутфорсе пароля БД.

## Топология

```
Клиенты ──► Cloudflare Edge (orange-cloud / Tunnel)
                 │
                 │ outbound-only cloudflared
                 ▼
            [origin VPS]  nginx → api (нет публичных :80/:443/:8000)
                 ▲
Админ / SSH ─────┤ WireGuard (wg0) / VPN gateway
                 │
Postgres/Redis ──┘ только docker network (порты не publish)
```

## 1. Cloudflare Tunnel (обязательно в prod)

```bash
# Zero Trust → create tunnel → copy token
echo "CLOUDFLARE_TUNNEL_TOKEN=eyJ..." >> .env

docker compose -f docker-compose.yml \
  -f deploy/docker-compose.scale.yml \
  -f deploy/docker-compose.tunnel.yml up -d
```

В приложении:

```env
CLOUDFLARE_ENABLED=true
CLOUDFLARE_ENFORCE_EDGE=true
CLOUDFLARE_TRUST_HEADERS=true
```

DNS: `api` CNAME → `<tunnel-id>.cfargotunnel.com` (proxied).

## 2. VPN-шлюз (WireGuard)

На origin:

```bash
apt install wireguard
# /etc/wireguard/wg0.conf — Address=10.8.0.1/24, ListenPort=51820
# клиент админа: AllowedIPs=10.8.0.0/24
ufw allow 51820/udp
systemctl enable --now wg-quick@wg0
```

Админ-панель только на loopback / VPN:

```env
ADMIN_PANEL_BIND_HOST=10.8.0.1   # или 127.0.0.1 + SSH tunnel
ADMIN_PANEL_PORT=8100
VPN_GATEWAY_CIDRS=10.8.0.0/24,10.7.0.0/24
```

```bash
uvicorn admin_microservice.main:app --host 10.8.0.1 --port 8100
```

## 3. Host harden (UFW + SSH keys + IP allowlist)

```bash
export SSH_ALLOW_CIDRS="YOUR.OFFICE.IP/32,10.8.0.0/24"
export VPN_IFACE=wg0
export ENABLE_PUBLIC_HTTP=false   # tunnel mode
sudo bash deploy/harden_host.sh
```

Эффект:

- `PasswordAuthentication no`, только pubkey
- UFW: deny all inbound; VPN iface; SSH из `SSH_ALLOW_CIDRS`
- порты 5432/6379/8000/8100 явно deny
- без tunnel: `ENABLE_PUBLIC_HTTP=true` открывает 80/443 **только** Cloudflare CIDR

## 4. Dead Man's Switch

| Компонент | Роль |
|-----------|------|
| `deploy/dead_mans_watchdog.py` | tail Postgres log → POST auth failures |
| Admin `/security/dead-mans-switch/*` | порог → Redis lockdown + Telegram |
| `DeadMansSwitchMiddleware` | 503 `DEAD_MANS_SWITCH_ACTIVE` для не-VPN |
| Cloudflare `under_attack` | edge challenge |
| `deploy/lockdown.sh` | опционально UFW drop (если `DEAD_MANS_SWITCH_RUN_HOST_LOCKDOWN=true`) |

```env
DEAD_MANS_SWITCH_ENABLED=true
DEAD_MANS_SWITCH_FAIL_THRESHOLD=5
DEAD_MANS_SWITCH_WINDOW_SECONDS=60
DEAD_MANS_SWITCH_CLOUDFLARE_UNDER_ATTACK=true
DEAD_MANS_SWITCH_RUN_HOST_LOCKDOWN=false
```

Watchdog (на origin, systemd/screen):

```bash
export ADMIN_PANEL_URL=http://10.8.0.1:8100
export ADMIN_PANEL_TOKEN="$(python -m admin_microservice.mint_token --label dms --ttl-days 90)"
python deploy/dead_mans_watchdog.py --log /var/log/postgresql/postgresql-16-main.log
# or: docker logs -f postgres 2>&1 | python deploy/dead_mans_watchdog.py --stdin
```

Снять блокировку (с VPN):

```bash
curl -X POST -H "Authorization: Bearer adm.v1...." \
  http://10.8.0.1:8100/security/dead-mans-switch/clear
```

## 5. Чек-лист

- [ ] Tunnel up; `nmap` origin → нет 80/443/8000/5432 с интернета
- [ ] `CLOUDFLARE_ENFORCE_EDGE=true` → прямой hit origin = 403
- [ ] SSH: пароль отклонён; доступ только с allowlist/VPN
- [ ] Drill: 5× fake `password authentication failed` → Telegram + 503
- [ ] Clear с VPN восстанавливает трафик
