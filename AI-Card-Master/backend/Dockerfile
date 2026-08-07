# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl build-essential libjpeg62-turbo-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt gunicorn>=23.0.0

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
COPY sql ./sql

# Debian slim: groupadd/useradd (--system ≈ Alpine addgroup -S / adduser -S).
RUN groupadd --system appgroup \
    && useradd --system --create-home --gid appgroup --uid 10001 appuser \
    && mkdir -p /app/uploads \
    && chown -R appuser:appgroup /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000", "-w", "4", "--timeout", "120", "--graceful-timeout", "30", "--keep-alive", "5"]
