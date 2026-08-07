# Launch Checklist — AI-Card-Master (plan §24 / §40)

Use this list before opening public traffic. Check items in order; do not skip security or payments.

## 0) Preflight (automated)

```bash
cd backend
python deploy/preflight_audit.py
python deploy/one_click_deploy.py --print-inventory
```

Must exit `0`. Scans `app/` + `admin_microservice/` for `print`/`console.log`, debuggers, and hardcoded / test API keys.

IaC inventory (`deploy/inventory.json`) must list postgres, redis, api, worker, beat, nginx, pg-backup. See `deploy/IAC.md`.

## 1) Secrets & environment

- [ ] `.env` created from `.env.example` (never commit `.env`)
- [ ] `APP_ENV=production`
- [ ] `JWT_SECRET_KEY` ≥ 64 random chars (not the example placeholder)
- [ ] `ADMIN_PANEL_TOKEN_SECRET` set and distinct from JWT
- [ ] `POSTGRES_PASSWORD` strong; not `changeme_in_production`
- [ ] YooKassa **live** `YOOKASSA_SHOP_ID` / `YOOKASSA_SECRET_KEY` (not test shop)
- [ ] Midjourney / Claude / SD / Face-Fix keys filled; empty unused providers OK
- [ ] `MIDJOURNEY_CALLBACK_BASE_URL` is **HTTPS** public URL
- [ ] `MIDJOURNEY_WEBHOOK_TOKEN` + `MIDJOURNEY_REPLY_REF_SECRET` rotated
- [ ] S3/Selectel: endpoint, bucket, access + secret keys verified with a test upload
- [ ] Telegram error bot token + chat id (500s must reach you)
- [ ] Legal block filled: operator name, address, support/privacy emails, public site URL
- [ ] `CORS_ORIGINS` = production frontend origin(s) only

- [ ] `ADMIN_ALLOWED_USER_ID` = your user UUID
- [ ] Cloudflare: orange-cloud DNS **or** Tunnel (`deploy/docker-compose.tunnel.yml`), `CLOUDFLARE_ENABLED=true`, `CLOUDFLARE_ENFORCE_EDGE=true`
- [ ] Origin harden: `sudo bash deploy/harden_host.sh` (SSH keys + IP allowlist, unused ports closed) — see `deploy/PRIVATE_TUNNEL.md`
- [ ] WireGuard VPN for admin/SSH; `ADMIN_PANEL_BIND_HOST` not public
- [ ] Dead Man's Switch watchdog running (`deploy/dead_mans_watchdog.py`) + Telegram drill

## 2) Database & migrations

- [ ] PostgreSQL reachable; **daily** encrypted backups to isolated vault (`deploy/docker-compose.backup.yml`, plan §63; optional `BACKUP_INTERVAL_SECONDS=21600` for 6h RPO)
- [ ] Restore drill documented: `bash deploy/postgres_restore.sh s3://…`
- [ ] Geo failover watchdog configured (`deploy/failover_watchdog.py`, ≤30s SLO)
- [ ] Incident recovery loop on primary (`python deploy/incident_recovery.py`) + Telegram hardware alerts
- [ ] `alembic upgrade head` on release (done by `deploy/release.sh`)
- [ ] History indexes present (`ix_generation_jobs_user_id_created_at`, …)
- [ ] Smoke: create user → trial/payment path → one generation job
- [ ] Midjourney providers tagged with `region` + `NEURAL_PREFERRED_REGION` / failover list
## 3) Runtime stack

- [ ] **One-click / IaC:** stack brought up via `bash deploy/one_click_deploy.sh --profile production_tunnel` (or Terraform → cloud-init → same script) — `deploy/IAC.md`
- [ ] Terraform (optional): `deploy/terraform` applied; firewall does **not** expose 5432/6379/8100
- [ ] DR drill: new VM + `--restore s3://…` finishes within **≈10 minutes**
- [ ] Redis healthy (`/health/ready` → redis true)
- [ ] API via Nginx only (`deploy/docker-compose.scale.yml`); `:8000` not public
- [ ] Postgres/Redis ports not published to the internet
- [ ] Celery worker + beat running; queues match compose command
- [ ] `/docs` disabled in production (`APP_ENV=production`)
- [ ] `/health/live` and `/health/ready` green behind Cloudflare

## 4) Autoscaling

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.scale.yml \
  up -d --scale api=2 --scale worker=2

# optional continuous scaler
python deploy/autoscale.py
```

- [ ] Scale overlay + Nginx confirmed (`PUBLIC_HTTP_PORT`)
- [ ] `AUTOSCALE_*` limits set in `.env` (min/max API & workers)
- [ ] Scale-up tested: enqueue fake backlog or `--dry-run` once
- [ ] Cooldown prevents thrashing (`AUTOSCALE_COOLDOWN_SECONDS`)

## 5) Security & abuse

- [ ] Suspicious-activity + sanitization middleware on
- [ ] Trial HMAC / FingerprintJS path verified against scripted abuse
- [ ] Admin `/api/v1/admin` blocked for non-admin users
- [ ] Admin microservice bound to localhost / VPN only
- [ ] Rate limits + CAPTCHA path smoke-tested (429 / `CAPTCHA_REQUIRED`)
- [ ] SSH keys only; unused ports closed (plan §37) — `harden_host.sh` + Tunnel
- [ ] Dead Man's Switch drill: inject 5 Postgres auth-fail lines → Telegram + API 503
- [ ] Clear lockdown from VPN (`POST /security/dead-mans-switch/clear`)

## 6) Payments & legal (GDPR)

- [ ] Terms + Privacy served (`/api/v1/legal/...`) with real operator data
- [ ] Account delete (GDPR) erases user data end-to-end
- [ ] YooKassa webhook HTTPS + signature path verified with a small live payment
- [ ] Tariff coins & subscription dates update after payment

## 7) Observability

- [ ] Force a handled 500 in staging → Telegram alert with `error_type` / file / line
- [ ] LOG_LEVEL=`INFO` (no debug dumps of secrets)
- [ ] No leftover `print()` / test keys (preflight)

## 8) Release & rollback drill

```bash
bash deploy/release.sh
# simulate failure, then:
bash deploy/rollback.sh
# if migration must reverse:
bash deploy/rollback.sh --with-db-downgrade -1
```

Windows operator laptop: `powershell -File deploy/rollback.ps1`

- [ ] Release tags `:current` / `:previous` exist after first deploy
- [ ] Rollback restores health within minutes
- [ ] Team knows who runs rollback (single owner)

## 9) Go / No-Go

| Gate | Owner | OK? |
|------|-------|-----|
| Preflight audit exit 0 | Backend | |
| Secrets rotated | Backend | |
| Payments live webhook | Backend | |
| Cloudflare + origin closed | Ops | |
| Rollback drill passed | Ops | |
| Telegram alerts live | Backend | |

**Go-live** only when every row is OK.
