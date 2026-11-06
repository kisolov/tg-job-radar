import pytest

from radar.accounts.entities import AccountStatus
from radar.accounts.ports import AccountExists, StaleAccount
from tests.factories import make_account


async def test_add_and_get_roundtrip(account_repo):
    a = make_account()
    a.join.done_today = 3
    await account_repo.add(a)
    got = await account_repo.get(a.id)
    assert got.phone == a.phone and got.join == a.join and got.resolve == a.resolve
    assert (await account_repo.get_by_phone(a.phone)).id == a.id


async def test_save_with_stale_version_raises(account_repo):
    a = make_account()
    await account_repo.add(a)
    first, second = await account_repo.get(a.id), await account_repo.get(a.id)
    first.membership_count = 5
    await account_repo.save(first)
    assert first.version == 1
    second.last_error = "x"
    with pytest.raises(StaleAccount):
        await account_repo.save(second)
    assert (await account_repo.get(a.id)).membership_count == 5


async def test_memory_repo_returns_copies(account_repo):
    a = make_account()
    await account_repo.add(a)
    got = await account_repo.get(a.id)
    got.membership_count = 99
    got.join.done_today = 7
    again = await account_repo.get(a.id)
    assert again.membership_count == 0 and again.join.done_today == 0
    a.membership_count = 42  # объект, переданный в add, тоже не связан с хранилищем
    assert (await account_repo.get(a.id)).membership_count == 0


async def test_list_active_excludes_banned(account_repo):
    ok, banned = make_account(), make_account(status=AccountStatus.banned)
    await account_repo.add(ok)
    await account_repo.add(banned)
    assert [x.id for x in await account_repo.list_active()] == [ok.id]
    assert {x.id for x in await account_repo.list_all()} == {ok.id, banned.id}


async def test_duplicate_phone(account_repo):
    await account_repo.add(make_account(phone="+79001112233"))
    with pytest.raises(AccountExists):
        await account_repo.add(make_account(phone="+79001112233"))
