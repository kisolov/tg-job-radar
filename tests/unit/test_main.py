import asyncio

import pytest

from radar.bootstrap.main import every, supervise


async def test_supervise_restarts_crashed_task_with_backoff():
    runs, sleeps = [], []

    async def task():
        runs.append(1)
        if len(runs) < 3:
            raise RuntimeError("boom")
        raise asyncio.CancelledError  # третий запуск «работает», пока нас не отменят

    async def fake_sleep(s):
        sleeps.append(s)

    with pytest.raises(asyncio.CancelledError):
        await supervise("t", task, sleep=fake_sleep)
    assert len(runs) == 3 and sleeps == [5, 10]


async def test_every_survives_errors():
    calls = []

    async def fn():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("x")
        if len(calls) == 3:
            raise asyncio.CancelledError

    async def fake_sleep(s):
        pass

    with pytest.raises(asyncio.CancelledError):
        await every(30, fn, sleep=fake_sleep)
    assert len(calls) == 3


async def test_supervise_resets_backoff_after_long_healthy_run():
    """M7: задача проработала дольше BACKOFF_MAX_S — следующая пауза снова короткая."""
    import pytest

    from radar.bootstrap.main import BACKOFF_MAX_S, BACKOFF_START_S, supervise

    now = [0.0]
    runs = []
    sleeps = []

    async def factory():
        runs.append(now[0])
        if len(runs) == 4:
            now[0] += BACKOFF_MAX_S + 1  # долгая нормальная работа перед падением
        raise RuntimeError("boom")

    async def sleep(s):
        sleeps.append(s)
        if len(sleeps) == 5:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await supervise("t", factory, sleep=sleep, monotonic=lambda: now[0])
    assert sleeps == [BACKOFF_START_S, BACKOFF_START_S * 2, BACKOFF_START_S * 4, BACKOFF_START_S,
                      BACKOFF_START_S * 2]
