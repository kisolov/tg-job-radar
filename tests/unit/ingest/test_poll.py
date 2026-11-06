from radar.ingest.ports import TgFlood, TgSourceGone
from radar.sources.entities import SourceKind, SourceStatus


async def test_poll_resumes_from_cursor(world):
    a = await world.add_account()
    ch = await world.add_source("chan_one", SourceKind.channel, 1, account=a)
    await world.sources.set_cursor(ch.id, 10)
    for i in (9, 10, 11, 12, 13):
        world.tg.post(ch.id, i, f"msg {i}")
    gw = world.tg.factory(a)
    await world.poll.execute(a.id, gw)
    assert [m.message_id for m in world.sink.got] == [11, 12, 13]
    assert (await world.sources.get(ch.id)).last_message_id == 13
    # «рестарт»: новый шлюз, новые usecase-объекты — курсор из хранилища
    world.clock.advance(300)
    gw2 = world.tg.factory(a)
    await world.poll.execute(a.id, gw2)
    assert world.tg.fetches[-1] == (a.phone, ch.id, 13)
    assert len(world.sink.got) == 3


async def test_first_poll_skips_old_history(world):
    from datetime import timedelta

    a = await world.add_account()
    ch = await world.add_source("chan_one", SourceKind.channel, 1, account=a)
    now = world.clock.now()
    world.tg.post(ch.id, 1, "old", date=now - timedelta(days=3))
    world.tg.post(ch.id, 2, "fresh", date=now - timedelta(hours=2))
    await world.poll.execute(a.id, world.tg.factory(a))
    assert [m.message_id for m in world.sink.got] == [2]
    assert (await world.sources.get(ch.id)).last_message_id == 2


async def test_first_poll_all_old_moves_cursor(world):
    from datetime import timedelta

    a = await world.add_account()
    ch = await world.add_source("chan_one", SourceKind.channel, 1, account=a)
    world.tg.post(ch.id, 5, "old", date=world.clock.now() - timedelta(days=3))
    await world.poll.execute(a.id, world.tg.factory(a))
    assert world.sink.got == [] and (await world.sources.get(ch.id)).last_message_id == 5


async def test_poll_respects_interval(world):
    a = await world.add_account()
    await world.add_source("chan_one", SourceKind.channel, 1, account=a)
    gw = world.tg.factory(a)
    await world.poll.execute(a.id, gw)
    world.clock.advance(299)
    await world.poll.execute(a.id, gw)
    assert len(world.tg.fetches) == 1
    world.clock.advance(1)
    await world.poll.execute(a.id, gw)
    assert len(world.tg.fetches) == 2


async def test_poll_batch_limited_oldest_first(world):
    a = await world.add_account()
    chans = [await world.add_source(f"chan_{i:02d}", SourceKind.channel, i + 1, account=a) for i in range(7)]
    gw = world.tg.factory(a)
    assert await world.poll.execute(a.id, gw) == 5
    world.clock.advance(1)
    assert await world.poll.execute(a.id, gw) == 2
    assert {f[1] for f in world.tg.fetches} == {c.id for c in chans}


async def test_poll_gone_channel_marked_dead(world):
    a = await world.add_account()
    ch = await world.add_source("chan_one", SourceKind.channel, 1, account=a)
    world.tg.errors[("fetch", ch.id)] = TgSourceGone()
    await world.poll.execute(a.id, world.tg.factory(a))
    got = await world.sources.get(ch.id)
    assert got.status is SourceStatus.dead and got.assigned_account_id is None


async def test_poll_flood_raises_to_worker(world):
    a = await world.add_account()
    ch = await world.add_source("chan_one", SourceKind.channel, 1, account=a)
    world.tg.errors[("fetch", ch.id)] = TgFlood(30)
    try:
        await world.poll.execute(a.id, world.tg.factory(a))
        raise AssertionError("expected TgFlood")
    except TgFlood as e:
        assert e.seconds == 30
