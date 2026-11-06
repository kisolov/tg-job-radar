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
