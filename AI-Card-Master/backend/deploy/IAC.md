# Infrastructure-as-Code & One-Click Deploy (plan §40)

Цель: бизнес **не привязан к одному железу**. Полная копия сервиса
(серверы → Postgres → Redis/кэш → API/workers → Nginx → бэкапы → туннель)
поднимается на новом хосте за **≈10 минут**.

## Артефакты

| Путь | Роль |
|------|------|
| `deploy/inventory.json` | Декларативный инвентарь runtime-стека |
| `docker-compose.yml` | Postgres 16 + Redis 7 + API + Celery worker/beat |
| `deploy/docker-compose.scale.yml` | Nginx edge, resource limits, без публичных :5432/:6379 |
| `deploy/docker-compose.backup.yml` | PG dump daily (86400s) → isolated S3; set 21600 for 6h RPO |
| `deploy/incident_recovery.py` | §63: critical load → Redis cache flush + container restart + Telegram |
| `deploy/docker-compose.tunnel.yml` | Cloudflare Tunnel (origin без публичного HTTP) |
| `deploy/terraform/` | Hetzner Cloud: primary + secondary VM, firewall, cloud-init |
| `deploy/one_click_deploy.py` | Оркестратор (validate → build → up → migrate → health) |
| `deploy/one_click_deploy.sh` | Bash entrypoint на Linux origin |
| `deploy/one_click_deploy.ps1` | Dry-run / inventory с Windows |

## Профили Compose

| Profile | Файлы | Когда |
|---------|--------|--------|
| `minimal` | base | Локальная отладка |
| `production` | base + scale + backup | Публичный :80 за Cloudflare orange-cloud |
| `production_tunnel` | + tunnel | Рекомендуемый prod (§37) |
| `disaster_recovery` | base + scale + backup | Чистый хост + `--restore s3://…` |

## Путь A — Terraform (новое железо за минуты)

```bash
cd backend/deploy/terraform
cp terraform.tfvars.example terraform.tfvars   # заполнить токен / SSH key / repo URL
terraform init
terraform apply
terraform output one_click_hint
```

Cloud-init ставит Docker и клонирует репозиторий в `/opt/ai-card-master`.
Дальше:

```bash
# с операторской машины
scp backend/.env deploy@PRIMARY_IP:/opt/ai-card-master/…/backend/.env
ssh deploy@PRIMARY_IP
cd …/backend
bash deploy/one_click_deploy.sh --profile production_tunnel
# опционально:
sudo bash deploy/harden_host.sh
```

Secondary VM — тот же профиль; для DR добавьте restore:

```bash
bash deploy/one_click_deploy.sh --profile disaster_recovery \
  --restore 's3://vault/pg/ai_card_master-YYYYMMDDThhmmss.dump.enc'
```

Пропишите IP в `FAILOVER_*` (см. `FAILOVER_PLAN.md`).

## Путь B — Bare metal / любой VPS (без Terraform)

1. Ubuntu 24.04+, Docker Engine + `docker compose` plugin  
2. `git clone` → `cp .env.example .env` → секреты  
3. `bash deploy/one_click_deploy.sh --profile production_tunnel`  
4. `sudo bash deploy/harden_host.sh`

Инвентарь сервисов:

```bash
python deploy/one_click_deploy.py --print-inventory
python deploy/one_click_deploy.py --dry-run --profile production --skip-env-check
```

## RTO ≈ 10 минут (бюджет)

| Шаг | Типично |
|-----|---------|
| Preflight audit | < 1 мин |
| `compose build` / pull (тёплый registry cache) | 2–4 мин |
| `compose up` + health | 1–2 мин |
| `alembic upgrade head` | < 1 мин |
| Optional `postgres_restore` | 2–4 мин |
| **Итого** | **≤ 10 мин** при подготовленном `.env` и образе |

Холодный pull без кэша может выйти за бюджет — держите зеркало образа
или `IMAGE_TAG` уже на хосте (`docker load`).

## Что намеренно снаружи Terraform

- Секреты (`.env`) — только scp / vault / SOPS, не в state  
- DNS / Cloudflare Tunnel token — Zero Trust UI или отдельный CF provider  
- Selectel S3 бакеты — уже описаны env-переменными `S3_*` / `BACKUP_S3_*`

## Связь с §36 / §37

- Geo failover watchdog использует `primary_ipv4` / `secondary_ipv4` из Terraform output  
- Tunnel overlay скрывает origin; firewall Terraform по умолчанию **не** открывает 80/443  
- Бэкап-sidecar входит в production-профили one-click
