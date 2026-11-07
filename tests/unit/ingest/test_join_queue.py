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
    # M3: заявка висит у админа — если её одобрят, аккаунт будет в чате; слот держим, чтобы R4 не разошёлся
    assert got.status is SourceStatus.rejected and got.assigned_account_id == a.id
    assert (await world.accounts.get(a.id)).membership_count == 1
    await world.source_service.assign_work()
    assert (await world.sources.get(g.id)).status is SourceStatus.rejected


async def test_channels_too_much_fills_membership(world):
    a = await world.add_account()
    await world.add_source("grp_one", SourceKind.group, 1, account=a)
    world.tg.errors[("join", "grp_one")] = TgChannelsTooMuch()
    await world.join_queue.tick(a.id, world.tg.factory(a))
    got = await world.accounts.get(a.id)
    # M4: неучтённые членства — отдельным счётчиком; наш счётчик остаётся честным
    assert got.membership_count == 0 and got.external_memberships == CAP
    assert not got.can_join(world.clock.now() + __import__("datetime").timedelta(days=1), CAP)


async def test_channels_too_much_does_not_drift_membership_on_release(world):
    """M4: после ChannelsTooMuch освобождение группы возвращает ровно один слот, счётчик не уходит ниже реального."""
    a = await world.add_account()
    kept = [await world.add_source(f"grp_{i}", SourceKind.group, 10 + i, account=a) for i in range(3)]
    for g in kept:
        await world.sources.set_joined(g.id)
    await world.add_source("grp_new", SourceKind.group, 20, account=a)
    world.tg.errors[("join", "grp_new")] = TgChannelsTooMuch()
    await world.join_queue.tick(a.id, world.tg.factory(a))
    got = await world.accounts.get(a.id)
    assert (got.membership_count, got.external_memberships) == (3, CAP - 3)
    await world.sources.release(kept[0].id)
    got = await world.accounts.get(a.id)
    assert got.membership_count + got.external_memberships == CAP - 1
    extra = await world.add_source("grp_extra", SourceKind.group, 30)
    assert await world.sources.assign(extra.id, a.id)  # освободившийся слот можно занять
    extra2 = await world.add_source("grp_extra2", SourceKind.group, 31)
    assert not await world.sources.assign(extra2.id, a.id)  # больше — нет


async def test_invite_join_sets_peer(world):
    a = await world.add_account()
    s = await world.sources.add_candidate("+InviteHash", "seed", 5)
    await world.sources.set_resolved(s.id, None, None, SourceKind.group, "Invite chat")
    assert await world.sources.assign(s.id, a.id)
    await world.join_queue.tick(a.id, world.tg.factory(a))
    got = await world.sources.get(s.id)
    assert got.joined and got.peer_id is not None
