"""C2/C3: access_hash выдаётся аккаунту, а не каталогу; приватный канал по инвайту требует вступления."""
from radar.accounts.entities import AccountStatus
from radar.ingest.ports import Resolved
from radar.sources.entities import SourceKind, SourceStatus


async def resolve_with(world, account, ref, peer, kind=SourceKind.channel):
    world.tg.chats[ref] = Resolved(peer, None, kind, ref)
    await world.sources.add_candidate(ref, "seed", 5)
    assert await world.resolve_queue.tick(account.id, world.tg.factory(account))
    return await world.sources.find(ref)


async def test_resolved_source_is_assigned_only_to_the_resolving_account(world):
    a = await world.add_account(phone="+79000000001")
    b = await world.add_account(phone="+79000000002")
    for i in range(3):  # у A больше каналов — «наименее загруженный» был бы B
        await world.add_source(f"busy_{i}", SourceKind.channel, 100 + i, account=a)
    s = await resolve_with(world, a, "chan_x", 777)
    assert s.hash_account_id == a.id
    await world.source_service.assign_work()
    s = await world.sources.get(s.id)
    assert s.assigned_account_id == a.id
    world.tg.post(s.id, 1, "вакансия", date=world.clock.now())
    await world.poll.execute(a.id, world.tg.factory(a))
    assert (await world.sources.get(s.id)).status is SourceStatus.active
    assert b.id != s.assigned_account_id


async def test_foreign_hash_requeues_source_instead_of_killing_it(world):
    a = await world.add_account(phone="+79000000001")
    b = await world.add_account(phone="+79000000002")
    s = await resolve_with(world, a, "chan_x", 777)
    assert await world.sources.assign(s.id, b.id)  # данные из старой версии: закреплён за чужим
    await world.poll.execute(b.id, world.tg.factory(b))
    s = await world.sources.get(s.id)
    assert s.status is SourceStatus.candidate and s.assigned_account_id is None
    assert s.access_hash is None and s.hash_account_id is None


async def test_banned_owner_sources_are_resolved_again_by_another_account(world):
    a = await world.add_account(phone="+79000000001")
    b = await world.add_account(phone="+79000000002")
    s = await resolve_with(world, a, "chan_x", 777)
    await world.source_service.assign_work()
    acc = world.accounts.rows[a.id]
    acc.status = AccountStatus.banned
    await world.release.execute(a.id)
    await world.source_service.assign_work()
    assert (await world.sources.get(s.id)).status is SourceStatus.candidate
    assert await world.resolve_queue.tick(b.id, world.tg.factory(b))
    await world.source_service.assign_work()
    s = await world.sources.get(s.id)
    assert s.assigned_account_id == b.id and s.hash_account_id == b.id


async def test_owner_in_flood_wait_keeps_source_for_itself(world):
    a = await world.add_account(phone="+79000000001")
    await world.add_account(phone="+79000000002")
    s = await resolve_with(world, a, "chan_x", 777)
    world.accounts.rows[a.id].status = AccountStatus.flood_wait
    await world.source_service.assign_work()
    s = await world.sources.get(s.id)
    assert s.assigned_account_id is None and s.status is SourceStatus.active


async def test_group_join_uses_owner_hash(world):
    a = await world.add_account(phone="+79000000001")
    s = await resolve_with(world, a, "grp_x", 778, SourceKind.group)
    await world.source_service.assign_work()
    assert await world.join_queue.tick(a.id, world.tg.factory(a))
    s = await world.sources.get(s.id)
    assert s.joined and s.status is SourceStatus.active


async def test_private_invite_channel_is_joined_and_does_not_block_polling(world):
    a = await world.add_account(phone="+79000000001")
    open_ch = await world.add_source("chan_one", SourceKind.channel, 501, account=a)
    world.tg.post(open_ch.id, 1, "вакансия", date=world.clock.now())
    priv = await resolve_with(world, a, "+PrivHash", None)  # не вступили: peer_id неизвестен
    assert priv.peer_id is None and priv.needs_membership
    await world.source_service.assign_work()
    priv = await world.sources.get(priv.id)
    assert priv.assigned_account_id == a.id and world.accounts.rows[a.id].membership_count == 1

    await world.poll.execute(a.id, world.tg.factory(a))
    assert [m.message_id for m in world.sink.got] == [1]  # открытый канал опрошен
    assert all(src != priv.id for _, src, _ in world.tg.fetches)

    assert await world.join_queue.tick(a.id, world.tg.factory(a))
    priv = await world.sources.get(priv.id)
    assert priv.joined and priv.peer_id is not None and priv.hash_account_id == a.id
    world.tg.post(priv.id, 7, "заказ", date=world.clock.now())
    world.clock.advance(301)
    await world.poll.execute(a.id, world.tg.factory(a))
    assert 7 in [m.message_id for m in world.sink.got]
