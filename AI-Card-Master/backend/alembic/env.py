"""Alembic environment for async SQLAlchemy migrations.

Uses application Settings for DATABASE_URL and imports ORM metadata
from app.models so autogenerate stays in sync with Clean Architecture models.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.models import Base

# Ensure all ORM models are registered on Base.metadata before autogenerate.
from app.models import api_usage_cost as _api_usage_cost  # noqa: F401
from app.models import bulk_generation as _bulk_generation  # noqa: F401
from app.models import brand_lora as _brand_lora  # noqa: F401
from app.models import claude_reasoning as _claude_reasoning  # noqa: F401
from app.models import generation as _generation  # noqa: F401
from app.models import smart_variant as _smart_variant  # noqa: F401
from app.models import generation_error_log as _generation_error_log  # noqa: F401
from app.models import generation_job as _generation_job  # noqa: F401
from app.models import marketplace_export as _marketplace_export  # noqa: F401
from app.models import payment as _payment  # noqa: F401
from app.models import pain_analysis as _pain_analysis  # noqa: F401
from app.models import stock_parser as _stock_parser  # noqa: F401
from app.models import style_preset_selection as _style_preset_selection  # noqa: F401
from app.models import user as _user  # noqa: F401
from app.models import winback as _winback  # noqa: F401
from app.models import workspace as _workspace  # noqa: F401


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.async_database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL script generation)."""

    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure Alembic context with a live DB connection."""

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations online using an async engine."""

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
