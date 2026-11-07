from datetime import timedelta

from radar.delivery.adapters.fake_notifier import FakeNotifier
from radar.findings.adapters.memory_repo import InMemoryFindingRepository
from radar.findings.entities import Classification, FindingStatus
from radar.findings.events import CopyAttached, InProcessEventBus
from radar.findings.service import FindingService
from radar.findings.usecases import ClusterMessage, DeliverAccepted, RedeliverStale
from radar.ingest.ports import IncomingMessage
from radar.screening.adapters.memory_repos import InMemoryUsageRepository
from radar.screening.prefilter import PrefilterConfig
from radar.shared.settings import DEFAULT_AGGREGATORS, DEFAULT_MARKERS, DEFAULT_STOPWORDS

TEXT = ("Ищем Python-разработчика в команду маркетплейса. Стек: FastAPI, PostgreSQL, Redis. Удалённо, "
        "вилка 250–300 тысяч. Пишите @hr_anna")
CLS = Classification(True, "vacancy", "Python, FastAPI", None, None, "@hr_anna", "Python-бэкенд")
PCFG = PrefilterConfig(60, DEFAULT_MARKERS, DEFAULT_STOPWORDS, DEFAULT_AGGREGATORS)


def render(f, copies) -> str:
    return f"{f.classification.summary} | {len(copies)}"


class Paused:
    def __init__(self) -> None:
        self.value = False

    async def __call__(self) -> bool:
        return self.value


class Env:
    def __init__(self, clock) -> None:
        self.clock = clock
        self.repo = InMemoryFindingRepository()
        self.bus = InProcessEventBus()
        self.stats = InMemoryUsageRepository()
        self.notifier = FakeNotifier()
        self.paused = Paused()
        self.service = FindingService(self.repo, clock, window_days=7, threshold=0.6)
        self.cluster = ClusterMessage(self.service, lambda: PCFG, self.bus, self.stats, clock)
        self.deliver = DeliverAccepted(self.repo, self.notifier, render, self.paused, self.stats, clock,
                                       plain=lambda html: html, alerts=self.notifier)
        self.redeliver = RedeliverStale(self.repo, clock, stale_s=600)

    def msg(self, source_id, message_id=1, text=TEXT):
        return IncomingMessage(source_id, message_id, text, self.clock.now(), 500, "author", True, None,
                               f"https://t.me/c/{source_id}/{message_id}", f"Чат {source_id}")

    async def accept_all(self):
        for f in await self.repo.pending(100):
            await self.repo.set_classification(f.id, CLS, 1)


async def test_prefilter_rejects_before_cluster(clock):
    env = Env(clock)
    await env.cluster.submit(env.msg(1, text="#резюме Ищу работу Python-разработчиком, опыт 3 года, пишите @me ..."))
    assert await env.repo.pending(10) == []
    s = await env.stats.get(clock.now().date())
    assert (s.read, s.passed_prefilter) == (1, 0)


async def test_delivers_once_and_counts(clock):
    env = Env(clock)
    await env.cluster.submit(env.msg(1))
    await env.cluster.submit(env.msg(2))
    await env.accept_all()
    assert await env.deliver.execute() == 1
    assert await env.deliver.execute() == 0
    assert env.notifier.sent == ["Python, FastAPI | 2"]
    assert (await env.stats.get(clock.now().date())).findings == 1


async def test_copy_after_delivery_emits_event(clock):
    env = Env(clock)
    await env.cluster.submit(env.msg(1))
    finding_id = (await env.repo.pending(1))[0].id
    await env.accept_all()
    await env.cluster.submit(env.msg(3))  # копия до доставки — события нет, карточка ещё не ушла
    assert env.bus.queue.empty()
    await env.deliver.execute()
    await env.cluster.submit(env.msg(2))
    event = env.bus.queue.get_nowait()
    assert event == CopyAttached(finding_id)


async def test_send_failure_unclaims(clock):
    env = Env(clock)
    await env.cluster.submit(env.msg(1))
    await env.accept_all()
    env.notifier.fail_next = 1
    assert await env.deliver.execute() == 0
    assert [f.status for f in await env.repo.accepted(10)] == [FindingStatus.accepted]
    assert await env.deliver.execute() == 1


async def test_stale_claim_redelivered_once(clock):
    env = Env(clock)
    await env.cluster.submit(env.msg(1))
    await env.accept_all()
    f = (await env.repo.accepted(1))[0]
    assert await env.repo.claim(f.id, clock.now())  # «упали» между claim и отправкой
    clock.advance(599)
    assert await env.redeliver.execute() == 0
    clock.advance(2)
    assert await env.redeliver.execute() == 1
    assert await env.deliver.execute() == 1
    assert await env.redeliver.execute() == 0
    assert await env.deliver.execute() == 0
    assert len(env.notifier.sent) == 1


async def test_pause_holds_delivery(clock):
    env = Env(clock)
    await env.cluster.submit(env.msg(1))
    await env.accept_all()
    env.paused.value = True
    assert await env.deliver.execute() == 0 and env.notifier.sent == []
    env.paused.value = False
    assert await env.deliver.execute() == 1


async def test_late_copy_during_delivery_edits_card(clock):
    env = Env(clock)
    await env.cluster.submit(env.msg(1))
    await env.accept_all()
    original_send = env.notifier.send

    async def send_and_copy(text, parse_mode="HTML"):
        mid = await original_send(text, parse_mode)
        await env.cluster.submit(env.msg(2))  # копия пришла, пока карточка уходила
        return mid

    env.notifier.send = send_and_copy
    await env.deliver.execute()
    assert env.notifier.edits == [(1, "Python, FastAPI | 2")]


async def test_discovery_and_source_counters(clock):
    from radar.accounts.adapters.memory_repo import InMemoryAccountRepository
    from radar.sources.adapters.memory_repo import InMemorySourceRepository
    from radar.sources.service import SourceService
    from radar.sources.usecases import DiscoverFromMessage

    env = Env(clock)
    sources = InMemorySourceRepository(InMemoryAccountRepository(), membership_cap=500)
    src = await sources.add_candidate("home_chat", "seed", 5)
    cluster = ClusterMessage(env.service, lambda: PCFG, env.bus, env.stats, clock,
                             discover=DiscoverFromMessage(SourceService(sources, None)), sources=sources)
    await cluster.submit(env.msg(src.id, text="Флудим тут, заходите в t.me/other_chat_ru"))  # мусор, но ссылка
    await cluster.submit(env.msg(src.id, 2))
    assert (await sources.find("other_chat_ru")).added_by == "discovery"
    got = await sources.get(src.id)
    assert (got.read_count, got.passed_count) == (2, 1)


async def test_window_new_cluster_after_8_days(clock):
    env = Env(clock)
    await env.cluster.submit(env.msg(1))
    clock.advance(timedelta(days=8).total_seconds())
    await env.cluster.submit(env.msg(2))
    assert len(await env.repo.pending(10)) == 2


async def test_rejected_card_falls_back_to_plain_text(clock):
    """I6: Telegram отклонил HTML-карточку → одна попытка простым текстом, без вечного повтора."""
    env = Env(clock)
    await env.cluster.submit(env.msg(1))
    await env.accept_all()
    env.notifier.reject_next = 1
    assert await env.deliver.execute() == 1
    assert env.notifier.modes == ["HTML", None]
    f = (await env.repo.accepted(10)) or None
    assert f is None


async def test_card_rejected_twice_fails_with_alert(clock):
    env = Env(clock)
    await env.cluster.submit(env.msg(1))
    await env.accept_all()
    env.notifier.reject_next = 2
    assert await env.deliver.execute() == 0
    found = list(env.repo.rows.values())[0]
    assert found.status is FindingStatus.failed
    assert any("не принял карточку" in a for a in env.notifier.alerts)
    assert await env.deliver.execute() == 0 and env.notifier.modes == ["HTML", None]  # не крутится
