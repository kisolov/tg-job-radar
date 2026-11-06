from radar.ingest.ports import Resolved, TgFlood, TgSourceGone
from radar.sources.entities import SourceKind, SourceStatus


async def test_resolve_priority_order(world):
    a = await world.add_account()
    low = await world.sources.add_candidate("low_one", "seed", 5)
    high = await world.sources.add_candidate("high_one", "seed", 10)
    world.tg.chats["low_one"] = Resolved(1, 11, SourceKind.channel, "Low")
    world.tg.chats["high_one"] = Resolved(2, 22, SourceKind.group, "High")
    gw = world.tg.factory(a)
    assert await world.resolve_queue.tick(a.id, gw)
    assert world.tg.resolves == [(a.phone, "high_one")]
    got = await world.sources.get(high.id)
    assert (got.status, got.peer_id, got.kind, got.title) == (SourceStatus.active, 2, SourceKind.group, "High")
    assert not await world.resolve_queue.tick(a.id, gw)  # интервал resolve-Pacer
    world.clock.advance(60)
    assert await world.resolve_queue.tick(a.id, gw)
    assert (await world.sources.get(low.id)).status is SourceStatus.active


async def test_resolve_gone_and_user(world):
    a = await world.add_account()
    gone = await world.sources.add_candidate("gone_one", "seed", 10)
    user = await world.sources.add_candidate("some_person", "seed", 5)
    world.tg.errors[("resolve", "gone_one")] = TgSourceGone()
    world.tg.chats["some_person"] = Resolved(3, 1, None, "Person")
    gw = world.tg.factory(a)
    await world.resolve_queue.tick(a.id, gw)
    world.clock.advance(60)
    await world.resolve_queue.tick(a.id, gw)
    assert (await world.sources.get(gone.id)).status is SourceStatus.dead
    assert (await world.sources.get(user.id)).status is SourceStatus.rejected


async def test_search_adds_candidates(world):
    from radar.ingest.usecases import SearchSources

    a = await world.add_account()
    world.tg.search_results["вакансии python"] = [("py_jobs", "Py Jobs", SourceKind.channel),
                                                  ("py_chat", "Py Chat", SourceKind.group)]
    await world.sources.add_candidate("py_chat", "seed", 5)
    search = SearchSources(world.accounts, world.account_service, world.sources, world.tg.factory, world.clock)
    found = await search.execute(["вакансии python"])
    assert found.added == ["py_jobs"] and found.duplicates == ["py_chat"]
    assert (await world.accounts.get(a.id)).resolve.done_today == 1


async def test_resolve_flood_returns_candidate(world):
    a = await world.add_account()
    s = await world.sources.add_candidate("chan_one", "seed", 5)
    world.tg.errors[("resolve", "chan_one")] = TgFlood(900)
    await world.resolve_queue.tick(a.id, world.tg.factory(a))
    assert (await world.sources.get(s.id)).status is SourceStatus.candidate
    got = await world.accounts.get(a.id)
    assert got.resolve.interval_factor == 1.5 and not got.can_resolve(world.clock.now())
