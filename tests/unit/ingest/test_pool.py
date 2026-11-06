import asyncio

from radar.accounts.entities import AccountStatus
from radar.ingest.ports import TgBanned, TgUnauthorized
from radar.sources.entities import SourceKind


async def test_ban_stops_only_that_account(world):
    a1 = await world.add_account(phone="+70000000001")
    a2 = await world.add_account(phone="+70000000002")
    g1 = await world.add_source("grp_one", SourceKind.group, 1, account=a1)
    ch2 = await world.add_source("chan_two", SourceKind.channel, 2, account=a2)
    world.tg.post(ch2.id, 1, "hello")
    w1, w2 = world.worker(a1), world.worker(a2)
    assert await w1.start() and await w2.start()
    world.tg.account_errors[a1.phone] = TgBanned()
    assert not await w1.step()
    assert await w2.step()
    assert (await world.accounts.get(a1.id)).status is AccountStatus.banned
    assert len(world.alerts.sent) == 1
    assert (await world.sources.get(g1.id)).assigned_account_id is None
    assert (await world.accounts.get(a1.id)).membership_count == 0
    assert [m.source_id for m in world.sink.got] == [ch2.id]
    assert not w1.gateway.started


async def test_worker_leaves_retired_groups(world):
    from radar.sources.entities import SourceStatus

    a = await world.add_account()
    g = await world.add_source("grp_one", SourceKind.group, 1, account=a)
    await world.sources.set_joined(g.id)
    await world.source_service.retire(g.id)
    assert (await world.accounts.get(a.id)).membership_count == 1  # слот занят, пока не вышли
    w = world.worker(a)
    await w.start()
    assert await w.step()
    assert w.gateway.left == ["grp_one"]
    got = await world.sources.get(g.id)
    assert got.status is SourceStatus.rejected and got.assigned_account_id is None and not got.joined
    assert (await world.accounts.get(a.id)).membership_count == 0


async def test_unauthorized_on_start(world):
    a = await world.add_account()
    world.tg.errors[("start", None)] = TgUnauthorized()
    w = world.worker(a)
    assert not await w.start()
    assert (await world.accounts.get(a.id)).status is AccountStatus.unauthorized


async def test_worker_stops_when_account_disabled(world):
    a = await world.add_account()
    w = world.worker(a)
    await w.start()
    await world.account_service.disable(a.id)
    assert not await w.step()
    assert not w.gateway.started


async def test_worker_survives_unexpected_error(world):
    a = await world.add_account()
    ch = await world.add_source("chan_one", SourceKind.channel, 1, account=a)
    world.tg.errors[("fetch", ch.id)] = RuntimeError("network glitch")
    w = world.worker(a)
    await w.start()
    assert await w.step()


async def test_runner_picks_up_new_accounts_and_assigns(world):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
        await asyncio.sleep(0)

    runner = world.runner(sleep=fake_sleep)
    a1 = await world.add_account()
    ch = await world.add_source("chan_one", SourceKind.channel, 1)
    await runner.sync()
    assert set(runner.running) == {a1.id}
    assert (await world.sources.get(ch.id)).assigned_account_id == a1.id
    a2 = await world.add_account()
    await runner.sync()
    assert set(runner.running) == {a1.id, a2.id}
    await runner.stop()
    assert runner.running == {}
