from radar.ingest.ports import TgChannelsTooMuch, TgFlood, TgJoinRequested, TgSourceGone
from radar.sources.entities import SourceKind, SourceStatus

CAP = 500


async def test_join_respects_pacer(world):
    a = await world.add_account()
    await world.add_source("grp_one", SourceKind.group, 1, account=a)
    await world.add_source("grp_two", SourceKind.group, 2, account=a)
    gw = world.tg.factory(a)
    assert await world.join_queue.tick(a.id, gw)
    assert not await world.join_queue.tick(a.id, gw)
    assert len(world.tg.joins) == 1
    world.clock.advance(600)
    assert await world.join_queue.tick(a.id, gw)
    assert len(world.tg.joins) == 2
    assert all(s.joined for s in await world.sources.list_assigned(a.id, SourceKind.group))


async def test_flood_on_join_throttles_account(world):
    a = await world.add_account()
    await world.add_source("grp_one", SourceKind.group, 1, account=a)
    world.tg.errors[("join", "grp_one")] = TgFlood(300)
    await world.join_queue.tick(a.id, world.tg.factory(a))
    got = await world.accounts.get(a.id)
    assert got.join.interval_factor == 1.5 and not got.join.can_act(world.clock.now())
    assert got.status.value == "active"


async def test_channel_private_marks_source_dead(world):
    a = await world.add_account()
    g = await world.add_source("grp_one", SourceKind.group, 1, account=a)
    other = await world.add_source("grp_two", SourceKind.group, 2, account=a)
    assert (await world.accounts.get(a.id)).membership_count == 2
    world.tg.errors[("join", "grp_one")] = TgSourceGone()
    gw = world.tg.factory(a)
    await world.join_queue.tick(a.id, gw)
    got = await world.sources.get(g.id)
    assert got.status is SourceStatus.dead and got.assigned_account_id is None
    assert (await world.accounts.get(a.id)).membership_count == 1
    world.clock.advance(600)
    assert await world.join_queue.tick(a.id, gw)  # работа аккаунта продолжается
    assert (await world.sources.get(other.id)).joined


async def test_join_request_rejects_source(world):
    a = await world.add_account()
    g = await world.add_source("grp_one", SourceKind.group, 1, account=a)
    world.tg.errors[("join", "grp_one")] = TgJoinRequested()
    await world.join_queue.tick(a.id, world.tg.factory(a))
    got = await world.sources.get(g.id)
    assert got.status is SourceStatus.rejected and got.assigned_account_id is None


async def test_channels_too_much_fills_membership(world):
    a = await world.add_account()
    await world.add_source("grp_one", SourceKind.group, 1, account=a)
    world.tg.errors[("join", "grp_one")] = TgChannelsTooMuch()
    await world.join_queue.tick(a.id, world.tg.factory(a))
    got = await world.accounts.get(a.id)
    assert got.membership_count == CAP
    assert not got.can_join(world.clock.now() + __import__("datetime").timedelta(days=1), CAP)


async def test_invite_join_sets_peer(world):
    a = await world.add_account()
    s = await world.sources.add_candidate("+InviteHash", "seed", 5)
    await world.sources.set_resolved(s.id, None, None, SourceKind.group, "Invite chat")
    assert await world.sources.assign(s.id, a.id)
    await world.join_queue.tick(a.id, world.tg.factory(a))
    got = await world.sources.get(s.id)
    assert got.joined and got.peer_id is not None
