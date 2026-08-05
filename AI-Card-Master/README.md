# AI-Card-Master

AI-Card-Master is a fullstack starter project for AI-powered card/image processing.
The backend uses FastAPI, and the frontend is prepared for Flutter (Mobile + Web) with Clean Architecture.

## Project Structure

```text
AI-Card-Master/
  backend/
    app/
      __init__.py
      main.py                    # FastAPI entrypoint and image upload endpoint
      api/
        __init__.py              # API layer (routers/endpoints)
      services/
        __init__.py              # AI and image processing business logic
      models/
        __init__.py              # Pydantic/SQLAlchemy models and schemas
      core/
        __init__.py              # Config, security, shared infrastructure
  frontend/
    lib/
      data/
        .gitkeep                 # Data sources and repository implementations
      domain/
        .gitkeep                 # Entities, repository contracts, use cases
      presentation/
        .gitkeep                 # UI, widgets, state management
```

## Backend Architecture (FastAPI)

- `app/api/`: Handles HTTP contracts (request/response, routing, status codes).
- `app/services/`: Contains core business workflows, AI integration, image processing logic.
- `app/models/`: Contains validation schemas (Pydantic) and persistence models (SQLAlchemy).
- `app/core/`: Contains environment configuration, security utilities, and shared technical components.

This module split keeps endpoints thin and testable while centralizing reusable logic in dedicated services.

## PostgreSQL Schema

Core relational model (PostgreSQL):

- `users`: `id`, `email`, `hashed_password`, `subscription_status` (`Free`/`Pro`).
- `generations`: `id`, `user_id`, `input_image_url`, `result_image_url`, `prompt_used`, `created_at`.

DB artifacts in this repository:

- SQL migration: `backend/sql/001_init_schema.sql`
- SQLAlchemy models: `backend/app/models/user.py`, `backend/app/models/generation.py`

Security-oriented schema details:

- UUID primary keys generated on DB side (`gen_random_uuid()`).
- `email` unique constraint + index.
- `generations.user_id` foreign key with `ON DELETE CASCADE`.
- Indexes on `generations.user_id` and `generations.created_at` for query scalability.

## Auth and Password Security

Security code is implemented in:

- `backend/app/core/config.py`
- `backend/app/core/security.py`

Implemented protections:

- Password hashing via **Argon2id** (passlib) with configurable memory/time/parallelism.
- Optional server-side `PASSWORD_PEPPER` support (stored only in environment).
- JWT generation (`access` + `refresh`) with strict claims:
  - `iss`, `aud`, `iat`, `nbf`, `exp`, `jti`, `sub`, `type`
- JWT decode/validation with mandatory claim checks and issuer/audience verification.
- Zero hardcoded secrets: all sensitive values come from `.env` / environment variables.

### Required Environment Variables

```env
DATABASE_URL=postgresql://user:password@localhost:5432/ai_card_master
JWT_SECRET_KEY=replace_with_a_very_long_random_secret_min_64_chars
```

### Optional Security Variables

```env
APP_ENV=development
JWT_ALGORITHM=HS512
JWT_ACCESS_TOKEN_TTL_MINUTES=15
JWT_REFRESH_TOKEN_TTL_DAYS=30
JWT_ISSUER=ai-card-master-api
JWT_AUDIENCE=ai-card-master-clients

# Optional additional secret mixed into password hashing input
PASSWORD_PEPPER=

# Argon2id tuning (adjust for your infrastructure)
ARGON2_MEMORY_COST_KIB=131072
ARGON2_TIME_COST=4
ARGON2_PARALLELISM=4
```

## Infographic Service (LLM + Pillow)

Implemented in `backend/app/services/infographic_service.py`.

Capabilities:

- Accepts short Russian theses from user.
- Expands thesis into a professional advertising headline via LLM.
- Supports both providers via environment config: OpenAI or Anthropic.
- Produces 3 style variants: `Minimal`, `Bold`, `Luxury`.
- Detects free background area (non-product zone) for text placement.
- Renders test text overlays with Pillow and returns PNG previews.

Placement strategy (high level):

- Estimate background color from image border samples.
- Build a foreground mask using background subtraction.
- Search candidate text boxes and score by minimal overlap with foreground/product area.
- Return best coordinates for safe text overlay.

Additional env vars for LLM:

```env
LLM_PROVIDER=openai
LLM_API_KEY=
LLM_MODEL=gpt-4.1-mini
LLM_BASE_URL=https://api.openai.com
LLM_TIMEOUT_SECONDS=25
LLM_MAX_CONNECTIONS=80
LLM_MAX_KEEPALIVE_CONNECTIONS=40
LLM_MAX_RETRIES=2
LLM_BASE_RETRY_DELAY_SECONDS=0.35
```

## Admin Module (Protected)

Implemented modules:

- Service: `backend/app/services/admin_service.py`
- API: `backend/app/api/admin.py`

Protected endpoints (admin-only, JWT Bearer required):

- `GET /api/v1/admin/stats` - generations day/week, total users, active Pro.
- `GET /api/v1/admin/users/by-email` - find user by email.
- `PATCH /api/v1/admin/users/subscription` - manual status update (`Free`/`Pro`).
- `GET /api/v1/admin/generation-errors` - list generation failures.
- `POST /api/v1/admin/generation-errors` - save generation failure event.

Access control:

- JWT is validated using existing security layer.
- Token must be `access` type.
- User from token subject must exist in DB and have `is_admin = true`.

DB additions for admin workflows:

- `users.is_admin` boolean flag.
- `generation_error_logs` table for troubleshooting history.

## Frontend Architecture (Flutter Clean Architecture)

- `data`: Remote/local data sources, DTO mapping, concrete repository implementations.
- `domain`: Business entities, repository interfaces, and use cases.
- `presentation`: Screens, controllers/state management, UI composition.

Dependency direction should remain: `presentation -> domain <- data`.

## Implemented API Routes

`backend/app/main.py` currently provides:

- `GET /` - root endpoint with service metadata.
- `GET /health` - healthcheck endpoint.
- `POST /api/v1/images/upload` - image upload endpoint.

The upload flow includes robust safeguards:

- MIME type whitelist validation (`jpeg`, `png`, `webp`).
- Maximum payload size validation.
- Safe filename generation via UUID.
- Storage directory initialization at startup.
- Structured error handling with explicit `try-except` blocks.
- Consistent JSON error responses via global exception handlers.

## Backend Quick Start

```bash
cd backend
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
.venv\Scripts\Activate.ps1

pip install fastapi uvicorn pydantic python-multipart
uvicorn app.main:app --reload
```

## Upload Example

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/images/upload" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@./sample.jpg"
```

## Durable Generation Pipeline (Celery + Redis)

The production generation path is DB-backed and does not wait for image
providers inside an HTTP request:

- `POST /api/v1/generations` returns HTTP `202` with a stable `task_id`.
- `GET /api/v1/generations/{task_id}` returns canonical PostgreSQL state.
- `POST /api/v1/webhooks/midjourney/{provider}` persists an authenticated,
  idempotent callback and acknowledges it before post-processing.
- PostgreSQL outbox rows survive Redis/broker restarts. Celery Beat dispatches
  committed rows and performs one-shot recovery checks for missed callbacks.
- Paid generation tries configured Midjourney-compatible webhook adapters in
  order, then degrades to Stable Diffusion with a warning.

`useapi.net` ended Midjourney support on 24 June 2026 and is not a production
default. Configure an active proxy through `MIDJOURNEY_PROVIDERS`; the exact
adapter contract and credentials are deployment-specific.

### Backend processes

```bash
cd backend
python -m venv .venv
# activate the virtual environment, then:
python -m pip install -r requirements.txt
alembic upgrade head

# API
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Linux production worker (prefork)
celery -A app.infrastructure.celery_app:celery_app worker \
  --loglevel=INFO \
  -Q generation.submit,generation.finalize,generation.recovery

# Durable outbox dispatcher and missed-webhook recovery schedule
celery -A app.infrastructure.celery_app:celery_app beat --loglevel=INFO
```

For local Windows development, add `--pool=solo` to the worker command. Run
Redis and PostgreSQL before API/worker/beat. `/health/live` checks the process;
`/health/ready` reports PostgreSQL, Redis, and S3 readiness independently.

### Clean Architecture boundaries

- `app/domain`: strict Pydantic v2 state and error contracts.
- `app/application`: generation use cases and dependency-inversion ports.
- `app/infrastructure`: SQLAlchemy, Redis, Celery, and provider adapters.
- `app/api`: thin HTTP validation/authentication and response mapping.
- `app/services`: preserved AI/image services wrapped by application ports.

Image post-processing keeps the original product pixels, creates deterministic
contact/ambient shadows, blends only the edge ring, and applies pixel-hash
verified lossless optimisation before S3/ZIP storage.
