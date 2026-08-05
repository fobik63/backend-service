"""Database engine and async session factory."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


settings = get_settings()


engine: AsyncEngine = create_async_engine(
    settings.async_database_url,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=20,
    max_overflow=40,
)


SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session for dependency injection."""

    async with SessionLocal() as session:
        yield session
