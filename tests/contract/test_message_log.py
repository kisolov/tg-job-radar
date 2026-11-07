import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from radar.ingest.adapters.memory_log import InMemoryMessageLog
from radar.ingest.adapters.sqlalchemy_log import SqlAlchemyMessageLog

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@pytest.fixture
def log(backend, request):
    if backend == "memory":
        return InMemoryMessageLog()
    return SqlAlchemyMessageLog(request.getfixturevalue("pg_sessionmaker"))


async def test_remember_once(log):
    assert await log.remember(1, 10, T0)
    assert not await log.remember(1, 10, T0)
    assert await log.remember(2, 10, T0)


async def test_concurrent_remember_single_winner(log):
    results = await asyncio.gather(*(log.remember(1, 99, T0) for _ in range(5)))
    assert results.count(True) == 1


async def test_purge_older(log):
    await log.remember(1, 1, T0 - timedelta(days=8))
    await log.remember(1, 2, T0)
    assert await log.purge_older(T0 - timedelta(days=7)) == 1
    assert await log.remember(1, 1, T0)  # после чистки снова «новое» (окно ретенции)
    assert not await log.remember(1, 2, T0)


async def test_unprocessed_leftovers_are_purged_and_forget_frees_the_key(log):
    """I5: после падения процесса незавершённые записи удаляются — сообщение перечитают; forget — то же сразу."""
    t = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
    assert await log.remember(1, 1, t)
    await log.done(1, 1)
    assert await log.remember(1, 2, t)  # процесс упал до done
    assert await log.purge_unprocessed() == 1
    assert not await log.remember(1, 1, t)  # обработанное помним
    assert await log.remember(1, 2, t)  # недообработанное — снова впервые
    await log.forget(1, 2)
    assert await log.remember(1, 2, t)
