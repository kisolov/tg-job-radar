import pytest
from sqlalchemy import text

from radar.shared.db import transaction


async def test_transaction_commits(pg_sessionmaker):
    async with transaction(pg_sessionmaker) as s:
        await s.execute(text("INSERT INTO settings_overrides(key, value) VALUES ('a', '1')"))
    async with transaction(pg_sessionmaker) as s:
        assert (await s.execute(text("SELECT value FROM settings_overrides WHERE key='a'"))).scalar() == "1"


async def test_transaction_rolls_back(pg_sessionmaker):
    with pytest.raises(RuntimeError):
        async with transaction(pg_sessionmaker) as s:
            await s.execute(text("INSERT INTO settings_overrides(key, value) VALUES ('b', '1')"))
            raise RuntimeError("boom")
    async with transaction(pg_sessionmaker) as s:
        assert (await s.execute(text("SELECT count(*) FROM settings_overrides"))).scalar() == 0


def test_fake_clock_advances(clock):
    t0 = clock.now()
    clock.advance(90)
    assert (clock.now() - t0).total_seconds() == 90
    assert t0.tzinfo is not None
