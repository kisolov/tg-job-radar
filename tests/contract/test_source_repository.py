import asyncio
from datetime import UTC, datetime

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
    assert [s.id for s in await source_repo.list_unassigned(True, 10)] == [free.id]
    assert await source_repo.list_unassigned(False, 10) == []
    assert [s.id for s in await source_repo.list_members(a.id)] == [g.id]
    assert await source_repo.list_assigned(a.id, SourceKind.channel) == []


async def test_claim_candidate_once(source_repo):
    a = await source_repo.add_candidate("chan_a", "seed", 5)
    b = await source_repo.add_candidate("chan_b", "seed", 10)
    got = await asyncio.gather(source_repo.claim_candidate(), source_repo.claim_candidate(), source_repo.claim_candidate())
    ids = [s.id for s in got if s]
    assert sorted(ids) == sorted([a.id, b.id]) and got.count(None) == 1
    assert (await source_repo.get(b.id)).status is SourceStatus.resolving


async def test_reset_resolving_after_crash(source_repo):
    a = await source_repo.add_candidate("chan_a", "seed", 5)
    await source_repo.claim_candidate()
    assert await source_repo.reset_resolving() == 1
    assert (await source_repo.get(a.id)).status is SourceStatus.candidate


async def test_resolved_without_peer_then_set_peer(source_repo):
    a = await source_repo.add_candidate("+inv_a", "seed", 5)
    b = await source_repo.add_candidate("chan_b", "seed", 5)
    assert await source_repo.set_resolved(a.id, None, None, SourceKind.group, "A")
    assert await source_repo.set_resolved(b.id, 77, 1, SourceKind.channel, "B")
    assert not await source_repo.set_peer(a.id, 77, 5)  # уже известный чат → дубль
    assert (await source_repo.get(a.id)).status is SourceStatus.rejected
    c = await source_repo.add_candidate("+inv_c", "seed", 5)
    await source_repo.set_resolved(c.id, None, None, SourceKind.group, "C")
    assert await source_repo.set_peer(c.id, 78, 5)
    assert (await source_repo.get(c.id)).peer_id == 78


async def test_due_for_poll(source_repo, account_repo_shared):
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
    acc = make_account()
    await account_repo_shared.add(acc)
    old = await _group(source_repo, "grp_old", 1)
    fresh = await _group(source_repo, "grp_new", 2)
    notjoined = await _group(source_repo, "grp_wait", 3)
    ch = await source_repo.add_candidate("chan_x", "seed", 5)
    await source_repo.set_resolved(ch.id, 9, 1, SourceKind.channel, "X")
    for s in (old, fresh, notjoined, ch):
        await source_repo.assign(s.id, acc.id)
    await source_repo.set_joined(old.id)
    await source_repo.set_joined(fresh.id)
    await source_repo.set_polled(old.id, now - timedelta(minutes=10))
    await source_repo.set_polled(fresh.id, now - timedelta(minutes=1))
    due = await source_repo.due_for_poll(acc.id, now - timedelta(minutes=5), 10)
    assert [s.id for s in due] == [ch.id, old.id]  # никогда не опрошенные — первыми; невступившие — нет


async def test_counts_and_top(source_repo):
    a = await _group(source_repo, "grp_one", 1)
    b = await _group(source_repo, "grp_two", 2)
    await source_repo.add_candidate("cand_one", "seed", 5)
    await source_repo.add_found(b.id, 3)
    await source_repo.add_found(a.id, 1)
    counts = await source_repo.count_by_status()
    assert counts == {SourceStatus.active: 2, SourceStatus.candidate: 1}
    top = await source_repo.top(limit=1, offset=0)
    assert [s.id for s in top] == [b.id] and top[0].found_count == 3
    assert [s.id for s in await source_repo.top(limit=5, offset=1)] == [a.id]


async def test_usefulness_queries(source_repo, account_repo_shared):
    from datetime import UTC, datetime, timedelta

    t0 = datetime(2026, 11, 1, tzinfo=UTC)
    acc = make_account()
    await account_repo_shared.add(acc)
    made = []
    for i, (reads, passed, found) in enumerate([(150, 0, 0), (150, 3, 0), (50, 0, 0), (150, 0, 2)]):
        s = await source_repo.add_candidate(f"grp_{i}_x", "seed", 5)
        await source_repo.set_resolved(s.id, i + 1, 1, SourceKind.group, "g", at=t0)
        await source_repo.assign(s.id, acc.id)
        await source_repo.set_joined(s.id)
        await source_repo.bump_counts(s.id, read=reads, passed=passed)
        await source_repo.add_found(s.id, found)
        made.append(s)
    got = await source_repo.get(made[0].id)
    assert (got.read_count, got.passed_count, got.activated_at) == (150, 0, t0)
    # (150,0,0) и (150,3,0) — без находок; (50,0,0) мало прочитано; (150,0,2) — с находками
    assert [s.id for s in await source_repo.unproductive(min_read=100)] == [made[0].id, made[1].id]
    owner = await source_repo.add_candidate("my_grp_x", "owner", 10)
    await source_repo.set_resolved(owner.id, 99, 1, SourceKind.channel, "m", at=t0)
    await source_repo.bump_counts(owner.id, read=500, passed=0)
    assert owner.id not in [s.id for s in await source_repo.unproductive(min_read=100)]
    cand = await source_repo.eviction_candidate(activated_before=t0 + timedelta(days=1))
    assert cand.id in {made[0].id, made[1].id, made[2].id}  # только с found_count == 0
    await source_repo.mark(made[0].id, SourceStatus.rejected)
    assert [s.id for s in await source_repo.list_to_leave(acc.id)] == [made[0].id]


async def test_find_by_ref(source_repo):
    s = await source_repo.add_candidate("chan_x", "seed", 5)
    assert (await source_repo.find("chan_x")).id == s.id
    assert await source_repo.find("nope_nope") is None


async def test_hash_owner_and_requeue(source_repo, account_repo_shared):
    """C2: хэш принадлежит резолвившему; requeue снимает закрепление (слот −1), стирает хэш, → candidate."""
    a = make_account()
    await account_repo_shared.add(a)
    s = await source_repo.add_candidate("grp_one", "seed", 5)
    await source_repo.set_resolved(s.id, 1, 111, SourceKind.group, "G", account_id=a.id)
    assert (await source_repo.get(s.id)).hash_account_id == a.id
    assert await source_repo.assign(s.id, a.id)
    assert (await account_repo_shared.get(a.id)).membership_count == 1
    await source_repo.requeue(s.id)
    got = await source_repo.get(s.id)
    assert got.status is SourceStatus.candidate and got.assigned_account_id is None and not got.joined
    assert got.access_hash is None and got.hash_account_id is None and got.peer_id == 1
    assert (await account_repo_shared.get(a.id)).membership_count == 0


async def test_invite_channel_needs_membership_and_is_polled_only_when_joined(source_repo, account_repo_shared):
    """C3: канал по инвайту занимает слот, вступает через очередь и опрашивается только с peer_id."""
    a = make_account()
    await account_repo_shared.add(a)
    s = await source_repo.add_candidate("+PrivHash", "seed", 10)
    await source_repo.set_resolved(s.id, None, None, SourceKind.channel, "Priv", account_id=a.id)
    s = await source_repo.get(s.id)
    assert s.needs_membership and s.hash_account_id is None
    assert [x.id for x in await source_repo.list_unassigned(True, 10)] == [s.id]
    assert await source_repo.assign(s.id, a.id)
    assert (await account_repo_shared.get(a.id)).membership_count == 1
    assert [x.id for x in await source_repo.list_members(a.id)] == [s.id]
    later = datetime(2030, 1, 1, tzinfo=UTC)
    assert await source_repo.due_for_poll(a.id, later, 10) == []
    assert await source_repo.set_peer(s.id, 4242, 9, account_id=a.id)
    assert await source_repo.due_for_poll(a.id, later, 10) == []  # ещё не вступили
    await source_repo.set_joined(s.id)
    assert [x.id for x in await source_repo.due_for_poll(a.id, later, 10)] == [s.id]
    assert (await source_repo.get(s.id)).hash_account_id == a.id
    await source_repo.release(s.id)
    assert (await account_repo_shared.get(a.id)).membership_count == 0


async def test_external_memberships_count_toward_the_cap(source_repo, account_repo_shared):
    """M4: чаты вне учёта занимают лимит при закреплении; поле переживает сохранение аккаунта."""
    from tests.contract.conftest import CAP

    a = make_account(external_memberships=CAP - 1)
    await account_repo_shared.add(a)
    assert (await account_repo_shared.get(a.id)).external_memberships == CAP - 1
    g1 = await _group(source_repo, "grp_one", 1)
    g2 = await _group(source_repo, "grp_two", 2)
    assert await source_repo.assign(g1.id, a.id)
    assert not await source_repo.assign(g2.id, a.id)
