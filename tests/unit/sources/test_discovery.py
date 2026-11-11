from datetime import timedelta

from radar.accounts.adapters.memory_repo import InMemoryAccountRepository
from radar.ingest.ports import IncomingMessage
from radar.sources.adapters.memory_repo import InMemorySourceRepository
from radar.sources.entities import SourceKind, SourceStatus
from radar.sources.service import SourceService
from radar.sources.usecases import AssignWork, DiscoverFromMessage, RetireUseless
from tests.factories import make_account

HH = "Python dev 🔥 https://hh.ru/vacancy/{n} #python #вакансия"
GOOD = "Ищем Python-разработчика на проект, удалённо, бюджет 100к, пишите @lead_dev — подробности в лс"


def setup():
    accounts = InMemoryAccountRepository()
    sources = InMemorySourceRepository(accounts, membership_cap=3)
    return accounts, sources, SourceService(sources, accounts)


def msg(text: str, fwd: str | None = None) -> IncomingMessage:
    from datetime import UTC, datetime

    return IncomingMessage(1, 1, text, datetime(2026, 11, 4, tzinfo=UTC), 1, "a", True, fwd, "l", "t")


async def test_links_become_candidates():
    _, sources, svc = setup()
    await DiscoverFromMessage(svc).execute(msg("Ещё вакансии тут: t.me/py_jobs_ru и https://t.me/+InViTe"))
    s = await sources.find("py_jobs_ru")
    assert s.added_by == "discovery" and s.priority == 1 and s.status is SourceStatus.candidate
    assert await sources.find("+InViTe") is not None


async def test_max_five_candidates_per_message():
    _, sources, svc = setup()
    text = " ".join(f"t.me/chat_number_{i}" for i in range(9))
    added = await DiscoverFromMessage(svc).execute(msg(text))
    assert added == 5 and len(await sources.next_to_resolve(100)) == 5


async def test_forward_source_becomes_candidate():
    _, sources, svc = setup()
    await DiscoverFromMessage(svc).execute(msg("пересланное без ссылок", fwd="Origin_Channel"))
    assert (await sources.find("origin_channel")).added_by == "discovery"


def test_english_chat_rejected():
    _, _, svc = setup()
    assert svc.vet("Remote Jobs Worldwide", "", ["We are hiring Python developers, remote, apply now"] * 5) \
        is SourceStatus.rejected


def test_offtopic_russian_chat_rejected():
    _, _, svc = setup()
    assert svc.vet("Котики и собачки", "Чат любителей животных", ["Какой милый котик!"] * 5) is SourceStatus.rejected


def test_topical_russian_chat_active():
    _, _, svc = setup()
    assert svc.vet("Фриланс заказы", "", [GOOD] * 5) is SourceStatus.active
    assert svc.vet("IT Jobs", "", [GOOD] * 5) is SourceStatus.active  # латиница в названии, но выборка русская


def test_relay_channel_rejected():
    _, _, svc = setup()
    sample = [HH.format(n=i) for i in range(12)] + [GOOD] * 8
    assert svc.vet("Вакансии Python", "", sample) is SourceStatus.rejected
    few = [HH.format(n=i) for i in range(12)]  # < 20 сообщений — по ретрансляции не судим
    assert svc.vet("Вакансии Python", "", few) is SourceStatus.active


async def _joined_group(sources, accounts, ref, peer, account, at):
    s = await sources.add_candidate(ref, "seed", 5)
    await sources.set_resolved(s.id, peer, 1, SourceKind.group, ref, at=at)
    assert await sources.assign(s.id, account.id)
    await sources.set_joined(s.id)
    return s


async def test_source_without_findings_after_100_messages_is_retired(clock):
    """100 прочитанных сообщений без единой находки — источник снимается с чтения (канал и группа одинаково)."""
    accounts, sources, svc = setup()
    a = make_account()
    await accounts.add(a)
    t0 = clock.now()
    dull_group = await _joined_group(sources, accounts, "dull_chat", 1, a, t0)
    dull_chan = await sources.add_candidate("dull_chan", "seed", 5)
    await sources.set_resolved(dull_chan.id, 4, 1, SourceKind.channel, "c", at=t0)
    found = await _joined_group(sources, accounts, "busy_chat", 2, a, t0)
    young = await _joined_group(sources, accounts, "young_chat", 3, a, t0)
    mine = await sources.add_candidate("my_chat", "owner", 10)
    await sources.set_resolved(mine.id, 5, 1, SourceKind.channel, "m", at=t0)
    await sources.bump_counts(dull_group.id, read=100, passed=7)  # прошли предфильтр, но LLM не принял ни одной
    await sources.bump_counts(dull_chan.id, read=120, passed=0)
    await sources.bump_counts(found.id, read=300, passed=4)
    await sources.add_found(found.id)
    await sources.bump_counts(young.id, read=99, passed=0)
    await sources.bump_counts(mine.id, read=500, passed=0)

    assert await RetireUseless(svc, min_read=100).execute() == 2
    assert (await sources.get(dull_group.id)).status is SourceStatus.rejected
    assert (await sources.get(dull_chan.id)).status is SourceStatus.rejected
    assert [s.id for s in await sources.list_to_leave(a.id)] == [dull_group.id]  # выйти должен воркер аккаунта
    for kept in (found, young, mine):  # есть находка / мало прочитано / добавлен владельцем
        assert (await sources.get(kept.id)).status is SourceStatus.active
    assert await RetireUseless(svc, min_read=100).execute() == 0


async def test_eviction_only_of_zero_yield(clock):
    accounts, sources, svc = setup()  # cap = 3
    a = make_account()
    await accounts.add(a)
    t0 = clock.now()
    g = [await _joined_group(sources, accounts, f"grp_{i}", i, a, t0) for i in range(3)]
    for s in g:
        await sources.add_found(s.id, 2)
    newcomer = await sources.add_candidate("new_grp", "owner", 10)
    await sources.set_resolved(newcomer.id, 99, 1, SourceKind.group, "new", at=t0)
    clock.advance(timedelta(days=15).total_seconds())
    await AssignWork(svc, clock).execute()
    assert [(await sources.get(s.id)).status for s in g] == [SourceStatus.active] * 3  # у всех есть находки
    assert (await sources.get(newcomer.id)).assigned_account_id is None
    # одна группа без находок → вытесняется (выход — воркером), новичок ждёт освобождения слота
    await sources.add_found(g[1].id, -2)
    await AssignWork(svc, clock).execute()
    assert (await sources.get(g[1].id)).status is SourceStatus.rejected
    assert [s.id for s in await sources.list_to_leave(a.id)] == [g[1].id]
