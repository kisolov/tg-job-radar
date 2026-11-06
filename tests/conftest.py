import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from radar.shared.clock import FakeClock
from radar.shared.db import make_engine, make_session_factory
from radar.shared.models import metadata

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://radar:radar@localhost:55432/radar_test"
)


def _upgrade() -> None:
    cfg = Config("alembic.ini")
    cfg.attributes["url"] = TEST_DB_URL
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
async def pg_engine():
    engine = make_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await asyncio.to_thread(_upgrade)
    yield engine
    await engine.dispose()


@pytest.fixture
async def pg_sessionmaker(pg_engine):
    tables = ", ".join(t.name for t in metadata.sorted_tables)
    async with pg_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    return make_session_factory(pg_engine)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()
