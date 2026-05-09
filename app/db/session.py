from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.db.models import Base


def make_engine(settings: Settings | None = None):
    settings = settings or get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True)


engine = make_engine()
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_database() -> None:
    if not get_settings().auto_create_tables:
        return
    async with engine.begin() as conn:
        if engine.url.get_backend_name().startswith("postgresql"):
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
