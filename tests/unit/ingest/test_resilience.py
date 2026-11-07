"""I2: потеря соединения → воркер пересоздаётся; I3: сбой одного источника не блокирует остальные."""
import asyncio

from radar.ingest.ports import Resolved
from radar.sources.entities import SourceKind, SourceStatus


async def spin(n=20):
    for _ in range(n):
        await asyncio.sleep(0)


async def test_lost_connection_ends_worker_and_runner_restarts_it(world):
    async def fake_sleep(_):
        await asyncio.sleep(0)

    a = await world.add_account()
    runner = world.runner(sleep=fake_sleep)
    await runner.sync()
    await spin()
    first = world.tg.gateways[-1]
    assert first.started
    first.connected = False  # сеть пропала дольше встроенных повторов Telethon
    await spin()
    assert runner.running[a.id].done() and not first.started
    await runner.sync()
    await spin()
    assert len(world.tg.gateways) == 2 and world.tg.gateways[-1].started
    await runner.stop()


async def test_failing_start_is_retried_on_next_sync(world):
    async def fake_sleep(_):
        await asyncio.sleep(0)

    a = await world.add_account()
    world.tg.account_errors[a.phone] = ConnectionError("no network")
    runner = world.runner(sleep=fake_sleep)
    await runner.sync()
    await spin()
    assert runner.running[a.id].done()
    del world.tg.account_errors[a.phone]
    await runner.sync()
    await spin()
    assert world.tg.gateways[-1].started
    await runner.stop()


async def test_poll_error_in_one_source_does_not_starve_others(world):
    a = await world.add_account()
    bad = await world.add_source("chan_bad", SourceKind.channel, 1, account=a)
    good = await world.add_source("chan_good", SourceKind.channel, 2, account=a)
    world.tg.errors[("fetch", bad.id)] = RuntimeError("ChatIdInvalid после миграции")
    world.tg.post(good.id, 5, "вакансия", date=world.clock.now())
    await world.poll.execute(a.id, world.tg.factory(a))
    assert [m.message_id for m in world.sink.got] == [5]
    assert (await world.sources.get(bad.id)).last_polled_at == world.clock.now()  # не встанет первым навсегда


async def test_failing_leave_does_not_block_the_step(world):
    a = await world.add_account()
    grp = await world.add_source("grp_old", SourceKind.group, 3, account=a)
    await world.sources.set_joined(grp.id)
    await world.sources.mark(grp.id, SourceStatus.rejected)
    world.tg.errors[("leave", grp.ref)] = RuntimeError("PeerIdInvalid")
    world.tg.chats["chan_new"] = Resolved(9, None, SourceKind.channel, "new")
    await world.sources.add_candidate("chan_new", "seed", 5)
    w = world.worker(a)
    await w.start()
    assert await w.step()
    assert ("+7" in world.tg.resolves[0][0]) and world.tg.resolves[0][1] == "chan_new"  # резолв дошёл
    assert (await world.sources.get(grp.id)).assigned_account_id is None  # слот освобождён
