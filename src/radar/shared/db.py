from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

SessionFactory = async_sessionmaker[AsyncSession]


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True, pool_size=20, max_overflow=20, pool_timeout=60)


def make_session_factory(engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def transaction(sf: SessionFactory) -> AsyncIterator[AsyncSession]:
    """Граница транзакции usecase: commit при выходе, rollback при исключении."""
    async with sf() as session:
        async with session.begin():
            yield session
