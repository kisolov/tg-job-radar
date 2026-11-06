from radar.sources.entities import SourceKind


async def test_same_message_twice_processed_once(world):
    a = await world.add_account()
    g = await world.add_source("grp_one", SourceKind.group, 1, account=a)
    w = world.worker(a)
    await w.start()
    w.gateway.watch([g])
    msg = world.tg.post(g.id, 7, "Нужен разработчик")
    assert await world.tg.push_live(msg) == 1  # live
    await world.poll.execute(a.id, w.gateway)  # и тот же через опрос
    assert [m.message_id for m in world.sink.got] == [7]
    assert (await world.sources.get(g.id)).last_message_id == 7


async def test_receive_returns_false_on_duplicate(world):
    msg = world.tg.post(1, 5, "x")
    assert await world.receive.execute(msg)
    assert not await world.receive.execute(msg)
