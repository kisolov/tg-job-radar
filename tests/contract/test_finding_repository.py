import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from radar.findings.adapters.memory_repo import InMemoryFindingRepository
from radar.findings.adapters.sqlalchemy_repo import SqlAlchemyFindingRepository
from radar.findings.entities import Classification, FindingStatus
from radar.findings.similarity import fingerprint, normalize, shingles
from radar.ingest.ports import IncomingMessage

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
TEXT = ("Ищем Python-разработчика в команду маркетплейса. Стек: FastAPI, PostgreSQL, Redis. Удалённо, "
        "вилка 250–300 тысяч. Пишите @hr_anna")
CLS = Classification(True, "vacancy", "Python, FastAPI", "250–300к", "удалёнка", "@hr_anna", "Python-бэкенд")


@pytest.fixture
def finding_repo(backend, request):
    if backend == "memory":
        return InMemoryFindingRepository()
    return SqlAlchemyFindingRepository(request.getfixturevalue("pg_sessionmaker"))


def msg(source_id: int, message_id: int = 1, text: str = TEXT) -> IncomingMessage:
    return IncomingMessage(source_id, message_id, text, T0, 500, "author", True, None,
                           f"https://t.me/c/{source_id}/{message_id}", f"Чат {source_id}")


async def cluster(repo, m: IncomingMessage, now=T0):
    norm = normalize(m.text)
    return await repo.cluster(m, norm, fingerprint(norm), shingles(norm), window_days=7, threshold=0.6, now=now)


async def test_new_then_duplicate(finding_repo):
    f1, new1 = await cluster(finding_repo, msg(1))
    f2, new2 = await cluster(finding_repo, msg(2, text="🔥 " + TEXT + " #python"))
    assert new1 and not new2 and f1.id == f2.id
    assert f1.status is FindingStatus.pending and f1.text_snapshot == TEXT
    assert [c.source_id for c in await finding_repo.copies(f1.id)] == [1, 2]


async def test_same_message_copy_not_duplicated(finding_repo):
    f, _ = await cluster(finding_repo, msg(1))
    await cluster(finding_repo, msg(1))
    assert len(await finding_repo.copies(f.id)) == 1


async def test_concurrent_copies_one_cluster(finding_repo):
    results = await asyncio.gather(*(cluster(finding_repo, msg(i)) for i in range(1, 6)))
    assert len({f.id for f, _ in results}) == 1
    assert [new for _, new in results].count(True) == 1
    assert len(await finding_repo.copies(results[0][0].id)) == 5


async def test_window_respected(finding_repo):
    f1, _ = await cluster(finding_repo, msg(1))
    f2, new = await cluster(finding_repo, msg(2), now=T0 + timedelta(days=8))
    assert new and f2.id != f1.id


async def test_classification_only_from_pending(finding_repo):
    f, _ = await cluster(finding_repo, msg(1))
    assert await finding_repo.set_classification(f.id, CLS, 3)
    assert not await finding_repo.set_classification(f.id, CLS, 4)
    got = await finding_repo.get(f.id)
    assert got.status is FindingStatus.accepted and got.requirements_version == 3 and got.classification == CLS
    rej, _ = await cluster(finding_repo, msg(9, text="Совсем другой текст про заказ дизайна логотипа для кофейни, бюджет 5к"))
    await finding_repo.set_classification(rej.id, Classification(False, None, "", None, None, None, "не профиль"), 3)
    assert (await finding_repo.get(rej.id)).status is FindingStatus.rejected


async def test_pending_oldest_first(finding_repo):
    a, _ = await cluster(finding_repo, msg(1))
    b, _ = await cluster(finding_repo, msg(2, text="Нужен разработчик Telegram-бота для салона красоты, бюджет 40к, @ivan"),
                         now=T0 + timedelta(seconds=5))
    assert [f.id for f in await finding_repo.pending(10)] == [a.id, b.id]
    assert await finding_repo.oldest_pending_at() == T0


async def test_claim_once(finding_repo):
    f, _ = await cluster(finding_repo, msg(1))
    assert not await finding_repo.claim(f.id, T0)  # pending ещё не claim-ится
    await finding_repo.set_classification(f.id, CLS, 1)
    results = await asyncio.gather(finding_repo.claim(f.id, T0), finding_repo.claim(f.id, T0))
    assert sorted(results) == [False, True]
    assert (await finding_repo.get(f.id)).status is FindingStatus.delivering


async def test_deliver_and_stale_claims(finding_repo):
    f, _ = await cluster(finding_repo, msg(1))
    g, _ = await cluster(finding_repo, msg(2, text="Нужен разработчик Telegram-бота для салона красоты, бюджет 40к, @ivan"))
    for x in (f, g):
        await finding_repo.set_classification(x.id, CLS, 1)
        await finding_repo.claim(x.id, T0)
    await finding_repo.mark_delivered(f.id, 777, T0)
    stale = await finding_repo.stale_claims(T0 + timedelta(seconds=1))
    assert [x.id for x in stale] == [g.id]
    await finding_repo.unclaim(g.id)
    assert [x.id for x in await finding_repo.accepted(10)] == [g.id]
    got = await finding_repo.get(f.id)
    assert (got.status, got.bot_message_id) == (FindingStatus.delivered, 777)


async def test_returned_objects_are_copies(finding_repo):
    f, _ = await cluster(finding_repo, msg(1))
    f.status = FindingStatus.delivered
    assert (await finding_repo.get(f.id)).status is FindingStatus.pending


async def test_llm_failures_push_back_then_fail(finding_repo):
    """I4: неудачная попытка отодвигает находку в конец очереди; после max — failed."""
    f1, _ = await cluster(finding_repo, msg(1))
    f2, _ = await cluster(finding_repo, msg(2, text="Нужен бот для записи клиентов в салон, бюджет 30 тысяч, пишите"))
    assert [f.id for f in await finding_repo.pending(10)] == [f1.id, f2.id]
    assert await finding_repo.record_llm_failure([f1.id], 2) == []
    assert [f.id for f in await finding_repo.pending(10)] == [f2.id, f1.id]
    assert await finding_repo.record_llm_failure([f1.id], 2) == [f1.id]
    got = await finding_repo.get(f1.id)
    assert got.status is FindingStatus.failed and got.llm_attempts == 2
    assert await finding_repo.record_llm_failure([f1.id], 2) == []  # уже не pending
    assert [f.id for f in await finding_repo.pending(10)] == [f2.id]


async def test_fail_delivery_only_from_delivering(finding_repo):
    """I6: failed ставится только выигравшему claim; повтор и чужой статус — без изменений."""
    f, _ = await cluster(finding_repo, msg(1))
    await finding_repo.set_classification(f.id, CLS, 1)
    assert not await finding_repo.fail_delivery(f.id)  # accepted, не delivering
    assert await finding_repo.claim(f.id, T0)
    assert await finding_repo.fail_delivery(f.id)
    assert (await finding_repo.get(f.id)).status is FindingStatus.failed
    assert not await finding_repo.fail_delivery(f.id)
    assert await finding_repo.accepted(10) == []


async def test_dedup_candidates_skip_unrelated_findings_of_similar_size(finding_repo):
    """M9: под блокировкой дедупа сравниваются только находки с пересекающимся скетчем."""
    import random

    rng = random.Random(3)
    alphabet = "абвгдежзиклмнопрстуфхцчшщэюя"
    for i in range(40):  # тексты той же длины, но другие — раньше все распаковывались и сравнивались
        noise = "".join(rng.choice(alphabet) for _ in range(len(TEXT)))
        await cluster(finding_repo, msg(100 + i, text=noise))
    target, _ = await cluster(finding_repo, msg(1))
    norm = normalize("🔥 " + TEXT + " #python")
    got = await finding_repo.dedup_candidates(shingles(norm), T0 - timedelta(days=7), 0.6)
    assert got == [target.id]
