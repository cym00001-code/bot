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
        await _apply_lightweight_migrations(conn)


async def _apply_lightweight_migrations(conn) -> None:
    if not engine.url.get_backend_name().startswith("postgresql"):
        return
    await conn.execute(
        text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS external_message_id VARCHAR(128)")
    )
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_messages_channel_external_message_id_unique "
            "ON messages (channel, external_message_id) WHERE external_message_id IS NOT NULL"
        )
    )
