# Geo-Distribution & Failover Plan (plan §36)

Цель: при падении **primary (NL)** или **нейро-API в регионе** переключить трафик на резерв **≤ 30 секунд**; восстановить бизнес после ransomware из изолированных бэкапов за минуты.

## 1. Топология

| Роль | Локация (пример) | Компоненты |
|------|------------------|------------|
| **Primary** | NL (Amsterdam) | API + Celery worker/beat + Redis + Postgres primary |
| **Secondary** | DE (Frankfurt) или FI | Горячий стендби API+workers; Postgres standby **или** promote из последнего бэкапа |
| **Edge** | Cloudflare | DNS / Load Balancer; origin IP скрыт (см. §37) |
| **Backup vault** | Отдельный бакет / аккаунт S3 | Только credentials бэкапа; Object Lock / versioning |

Каноническое состояние задач — **PostgreSQL** (не Redis). Redis локален на регионе; после failover in-flight Celery tasks подхватятся из outbox/recovery beat.

```
Клиент → Cloudflare (api.*) → Origin A (NL)
                              ↘ Origin B (DE)  ← watchdog переключает DNS/LB ≤30s
Нейро-пул Midjourney: region=eu-nl | eu-de | …
     circuit breaker → следующий здоровый регион
Бэкапы PG: каждые 6h → isolated S3 (не тот же ключ, что у приложения)
```

## 2. SLA переключения (≤ 30 с)

| Параметр | Значение | Зачем |
|----------|----------|--------|
| Интервал probe | **5 с** | `FAILOVER_POLL_SECONDS` |
| Порог fail | **3** подряд | ~15 с детекции |
| HTTP timeout probe | **3 с** | не раздувать окно |
| Cloudflare DNS TTL / proxied | Proxied orange-cloud | смена origin почти сразу |
| Итого RTO edge | **≈ 15–25 с** | запас до 30 с |

Эндпоинты: `/health/live` (процесс), `/health/ready` (Postgres + Redis + S3).  
Watchdog смотрит **только** `/health/ready` на primary origin (прямой IP / внутренний URL, не публичный CF, чтобы не зациклиться).

Запуск:

```bash
# с secondary / jump host (не на том же железе, что primary)
python deploy/failover_watchdog.py
python deploy/failover_watchdog.py --once --dry-run
```

## 3. Сценарии

### A. Primary NL down (сеть / железо / OOM)

1. Watchdog: 3× fail `/health/ready` → Cloudflare DNS/LB → secondary origin IP.
2. Telegram: `FAILOVER_ACTIVATED primary→secondary`.
3. На secondary: API/workers уже up; если Postgres — streaming standby → `promote`; иначе restore из последнего бэкапа (`deploy/postgres_restore.sh`).
4. Recovery beat (`generation.recover_stalled`, Claude outbox) дочищает висящие jobs.
5. Failback: только вручную после N успешных probe (`FAILOVER_RECOVER_THRESHOLD`, по умолчанию 6 ≈ 30 с стабильности) **или** флаг `FAILOVER_AUTO_FAILBACK=false` (рекомендуется в prod).

### B. Нейро-API региона упал (Midjourney proxy / Claude region)

1. Уже есть Redis circuit breaker на провайдера (`MIDJOURNEY_CIRCUIT_BREAKER_*`).
2. Провайдеры в `MIDJOURNEY_PROVIDERS` помечаются полем `region` (`eu-nl`, `eu-de`, …).
3. `get_healthy_async_midjourney_providers()` отдаёт сначала preferred region, затем остальные здоровые — без sleep в воркере.
4. Если весь регион open — генерация идёт через другой регион / SD fallback (тариф Free). Клиент получает понятную ошибку только если **все** пулы мертвы.

### C. Ransomware / шифровальщик на primary

1. **Не** поднимать replica, если она тоже заражена синхронной репликацией — брать **изолированный** бэкап.
2. `deploy/postgres_restore.sh` из vault → новая ВМ / secondary.
3. Ротация всех секретов (JWT, S3 app keys, DB password, YooKassa, MJ/Claude).
4. Cloudflare → новый clean origin; старый сегмент — quarantine.

## 4. Бэкапы PostgreSQL (каждые 6 часов)

| Свойство | Требование |
|----------|------------|
| Расписание | `0 */6 * * *` UTC (compose sidecar / cron) |
| Формат | `pg_dump -Fc` (custom) + AES-256-CBC |
| Хранилище | Отдельный бакет `BACKUP_S3_*` ≠ app `S3_*` |
| Retention | ≥ 14 дней (`BACKUP_RETENTION_DAYS`) |
| Изоляция | Отдельный Access Key; bucket versioning / Object Lock если доступен |
| Алерт | Telegram при fail / missing backup > 7h |

```bash
bash deploy/postgres_backup.sh
bash deploy/postgres_restore.sh s3://vault/pg/ai_card_master-20260807T060000.dump.enc
```

Compose sidecar:

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.backup.yml up -d pg-backup
```

Целевой RTO restore (теплая ВМ + последний dump): **5–15 минут** при отработанном drill.

## 5. Чек-лист внедрения

- [ ] Secondary инстанс в другой DC, тот же `IMAGE_TAG`, секреты из vault
- [ ] `FAILOVER_*` + Cloudflare Zone/Token с правом DNS edit
- [ ] Watchdog на jump host / secondary (systemd / screen)
- [ ] `BACKUP_S3_*` + `BACKUP_ENCRYPTION_KEY` (≥ 32 chars), drill restore раз в месяц
- [ ] `MIDJOURNEY_PROVIDERS` с ≥2 `region`
- [ ] Drill: убить primary API → измерить время до 200 на secondary ≤ 30s
- [ ] Drill: restore dump на пустой Postgres → `alembic upgrade head` не нужен если dump полный

## 6. Связанные артефакты

| Файл | Роль |
|------|------|
| `deploy/failover_watchdog.py` | Probe + Cloudflare origin switch |
| `deploy/postgres_backup.sh` | Dump → encrypt → isolated S3 |
| `deploy/postgres_restore.sh` | Decrypt → pg_restore |
| `deploy/docker-compose.backup.yml` | Sidecar каждые 6h |
| `deploy/terraform/` | IaC: primary/secondary VMs + firewall (§40) |
| `deploy/one_click_deploy.sh` | Полный стек на новом железе ≈10 мин (§40) |
| `deploy/IAC.md` | One-click / Terraform runbook |
| `deploy/LAUNCH_CHECKLIST.md` | Go-live gates |
| `app/services/ai_engine.py` | Region-aware provider pool |

## 7. Чего watchdog намеренно не делает

- Не правит Cloudflare из application workers (только ops-процесс).
- Не делает auto-failback в production по умолчанию (флаппинг хуже краткого downtime).
- Не хранит бэкапы на том же volume/аккаунте, что live Postgres.
