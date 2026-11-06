import asyncio

from radar.sources.entities import SourceKind, SourceStatus
from tests.factories import make_account


async def _group(repo, ref: str, peer: int):
    s = await repo.add_candidate(ref, "seed", 5)
    await repo.set_resolved(s.id, peer, 111, SourceKind.group, ref.title())
    return await repo.get(s.id)


async def test_duplicate_candidate_ignored(source_repo):
    first = await source_repo.add_candidate("a_chat", "seed", 5)
    assert first is not None and first.status is SourceStatus.candidate
    assert await source_repo.add_candidate("a_chat", "owner", 10) is None


async def test_invite_candidate(source_repo):
    s = await source_repo.add_candidate("+AbC", "seed", 5)
    assert s.invite_hash == "+AbC" and s.username is None


async def test_duplicate_peer_after_resolve_rejected(source_repo):
    a = await source_repo.add_candidate("chan_a", "seed", 5)
    b = await source_repo.add_candidate("+invite", "seed", 5)
    assert await source_repo.set_resolved(a.id, 100, 1, SourceKind.channel, "A")
    assert not await source_repo.set_resolved(b.id, 100, 1, SourceKind.channel, "A")
    assert (await source_repo.get(b.id)).status is SourceStatus.rejected
    assert (await source_repo.get(a.id)).status is SourceStatus.active


async def test_next_to_resolve_by_priority(source_repo):
    low = await source_repo.add_candidate("low_one", "seed", 5)
    high = await source_repo.add_candidate("high_one", "seed", 10)
    assert [s.id for s in await source_repo.next_to_resolve(2)] == [high.id, low.id]
    await source_repo.mark(high.id, SourceStatus.resolving)
    assert [s.id for s in await source_repo.next_to_resolve(2)] == [low.id]


async def test_assign_only_once(source_repo, account_repo_shared):
    a1, a2 = make_account(), make_account()
    await account_repo_shared.add(a1)
    await account_repo_shared.add(a2)
    g = await _group(source_repo, "grp_one", 1)
    results = await asyncio.gather(source_repo.assign(g.id, a1.id), source_repo.assign(g.id, a2.id))
    assert sorted(results) == [False, True]
    counts = [(await account_repo_shared.get(x.id)).membership_count for x in (a1, a2)]
    assert sorted(counts) == [0, 1]


async def test_membership_cap(source_repo, account_repo_shared):
    a = make_account(membership_count=499)
    await account_repo_shared.add(a)
    g1, g2 = await _group(source_repo, "grp_one", 1), await _group(source_repo, "grp_two", 2)
    assert await source_repo.assign(g1.id, a.id)
    assert not await source_repo.assign(g2.id, a.id)
    assert (await source_repo.get(g2.id)).assigned_account_id is None
    assert (await account_repo_shared.get(a.id)).membership_count == 500


async def test_channel_assign_does_not_count_membership(source_repo, account_repo_shared):
    a = make_account(membership_count=500)
    await account_repo_shared.add(a)
    s = await source_repo.add_candidate("chan_x", "seed", 5)
    await source_repo.set_resolved(s.id, 9, 1, SourceKind.channel, "X")
    assert await source_repo.assign(s.id, a.id)
    assert (await account_repo_shared.get(a.id)).membership_count == 500


async def test_assign_bumps_account_version(source_repo, account_repo_shared):
    a = make_account()
    await account_repo_shared.add(a)
    g = await _group(source_repo, "grp_one", 1)
    await source_repo.assign(g.id, a.id)
    assert (await account_repo_shared.get(a.id)).version == 1


async def test_release_all_of_account(source_repo, account_repo_shared):
    a = make_account()
    await account_repo_shared.add(a)
    g1, g2 = await _group(source_repo, "grp_one", 1), await _group(source_repo, "grp_two", 2)
    ch = await source_repo.add_candidate("chan_x", "seed", 5)
    await source_repo.set_resolved(ch.id, 9, 1, SourceKind.channel, "X")
    for s in (g1, g2, ch):
        assert await source_repo.assign(s.id, a.id)
    await source_repo.set_joined(g1.id)
    assert (await account_repo_shared.get(a.id)).membership_count == 2
    await source_repo.release_all_of(a.id)
    assert (await account_repo_shared.get(a.id)).membership_count == 0
    for s in (g1, g2, ch):
        got = await source_repo.get(s.id)
        assert got.assigned_account_id is None and not got.joined


async def test_release_single(source_repo, account_repo_shared):
    a = make_account()
    await account_repo_shared.add(a)
    g = await _group(source_repo, "grp_one", 1)
    await source_repo.assign(g.id, a.id)
    await source_repo.release(g.id)
    await source_repo.release(g.id)  # повтор не уводит счётчик в минус
    assert (await account_repo_shared.get(a.id)).membership_count == 0


async def test_cursor_never_moves_back(source_repo):
    s = await source_repo.add_candidate("chan_x", "seed", 5)
    await source_repo.set_cursor(s.id, 50)
    await source_repo.set_cursor(s.id, 40)
    assert (await source_repo.get(s.id)).last_message_id == 50


async def test_list_assigned_and_unassigned(source_repo, account_repo_shared):
    a = make_account()
    await account_repo_shared.add(a)
    g = await _group(source_repo, "grp_one", 1)
    free = await _group(source_repo, "grp_two", 2)
    await source_repo.assign(g.id, a.id)
    assert [s.id for s in await source_repo.list_assigned(a.id, SourceKind.group)] == [g.id]
    assert [s.id for s in await source_repo.list_unassigned(SourceKind.group, 10)] == [free.id]
    assert await source_repo.list_assigned(a.id, SourceKind.channel) == []


async def test_find_by_ref(source_repo):
    s = await source_repo.add_candidate("chan_x", "seed", 5)
    assert (await source_repo.find("chan_x")).id == s.id
    assert await source_repo.find("nope_nope") is None
