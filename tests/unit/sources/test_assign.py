from pathlib import Path

from radar.accounts.adapters.memory_repo import InMemoryAccountRepository
from radar.accounts.entities import AccountStatus
from radar.sources.adapters.memory_repo import InMemorySourceRepository
from radar.sources.entities import SourceKind, SourceStatus
from radar.sources.service import SourceService
from radar.sources.usecases import AddSource, AssignWork, ImportSeeds, ReleaseAccountSources, RemoveSource
from tests.factories import make_account


def setup():
    accounts = InMemoryAccountRepository()
    sources = InMemorySourceRepository(accounts, membership_cap=500)
    return accounts, sources, SourceService(sources, accounts)


async def _active(sources, ref, kind, peer):
    s = await sources.add_candidate(ref, "seed", 5)
    await sources.set_resolved(s.id, peer, 1, kind, ref)
    return s


async def test_assign_work_balances_by_load():
    accounts, sources, svc = setup()
    a1, a2 = make_account(membership_count=10), make_account(membership_count=0)
    banned = make_account(status=AccountStatus.banned)
    for a in (a1, a2, banned):
        await accounts.add(a)
    for i in range(4):
        await _active(sources, f"grp_{i:02d}", SourceKind.group, i)
    for i in range(4):
        await _active(sources, f"chan_{i:02d}", SourceKind.channel, 100 + i)
    assigned = await AssignWork(svc).execute()
    assert assigned == 8
    groups_a2 = await sources.list_assigned(a2.id, SourceKind.group)
    assert len(groups_a2) == 4  # a2 загружен меньше: все 4 группы до выравнивания (10 > 4)
    ch1 = await sources.list_assigned(a1.id, SourceKind.channel)
    ch2 = await sources.list_assigned(a2.id, SourceKind.channel)
    assert (len(ch1), len(ch2)) == (2, 2)
    assert await sources.list_assigned(banned.id, SourceKind.group) == []


async def test_assign_work_skips_candidates():
    accounts, sources, svc = setup()
    await accounts.add(make_account())
    await sources.add_candidate("not_resolved", "seed", 5)
    assert await AssignWork(svc).execute() == 0


async def test_import_seeds(tmp_path: Path):
    _, sources, svc = setup()
    f = tmp_path / "seeds.txt"
    f.write_text("# комментарий\n!@freelance_ru\n@jobs_py\nhttps://t.me/jobs_py\n\nnot a link!!\n")
    result = await ImportSeeds(svc).execute(f)
    assert (result.added, result.duplicates, result.invalid) == (2, 1, 1)
    assert (await sources.find("freelance_ru")).priority == 10
    assert (await sources.find("jobs_py")).priority == 5


async def test_add_and_remove_source():
    accounts, sources, svc = setup()
    a = make_account()
    await accounts.add(a)
    res = await AddSource(svc).execute("вот t.me/new_chat и @other_chat")
    assert res.added == ["new_chat", "other_chat"]
    s = await sources.find("new_chat")
    assert s.added_by == "owner" and s.priority == 10
    await sources.set_resolved(s.id, 5, 1, SourceKind.group, "N")
    await sources.assign(s.id, a.id)
    assert await RemoveSource(svc).execute("@new_chat")
    got = await sources.get(s.id)
    assert got.status is SourceStatus.rejected and got.assigned_account_id is None
    assert (await accounts.get(a.id)).membership_count == 0
    assert not await RemoveSource(svc).execute("@missing_chat")


async def test_release_account_sources():
    accounts, sources, svc = setup()
    a = make_account()
    await accounts.add(a)
    g = await _active(sources, "grp_one", SourceKind.group, 1)
    await sources.assign(g.id, a.id)
    await ReleaseAccountSources(svc).execute(a.id)
    assert (await sources.get(g.id)).assigned_account_id is None
