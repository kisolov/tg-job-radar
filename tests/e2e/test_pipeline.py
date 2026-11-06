"""Весь конвейер через DI-контейнер: настоящая БД, фейковые Telegram / LLM / бот, FakeClock."""
from dependency_injector import providers

from radar.bootstrap.di import Container
from radar.delivery.adapters.fake_notifier import FakeNotifier
from radar.ingest.adapters.fake_gateway import FakeTelegram
from radar.ingest.ports import Resolved
from radar.screening.adapters.fake_classifier import FakeClassifier
from radar.shared.settings import Settings
from radar.sources.entities import SourceKind
from tests.conftest import TEST_DB_URL
from tests.factories import make_account

VACANCY = ("Ищем Python-разработчика (FastAPI, PostgreSQL) в команду маркетплейса, удалённо, частичная занятость, "
           "вилка 200–250к. Пишите @hr_anna")
JUNK = {
    4: "#резюме Ищу работу Python-разработчиком, опыт 3 года, Django, FastAPI. Пишите @me_dev",
    5: "Python dev 🔥 https://hh.ru/vacancy/123456 #python #вакансия",
    6: "We are hiring a senior Python developer for a remote role, FastAPI and Postgres, DM @recruiter_en",
}


class World:
    def __init__(self, sessionmaker, clock):
        self.tg = FakeTelegram()
        self.classifier = FakeClassifier()
        self.notifier = FakeNotifier()
        self.sessionmaker, self.clock = sessionmaker, clock

    def container(self) -> Container:
        c = Container()
        c.settings.override(Settings(
            _env_file=None, DATABASE_URL=TEST_DB_URL, OWNER_TELEGRAM_ID=1, BOT_TOKEN="42:TEST",
            USERBOT_STORE_KEY="ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=", NEUROAPI_BASE_URL="http://x",
            NEUROAPI_KEY="k", NEUROAPI_MODEL="m",
        ))
        c.sessions.override(providers.Object(self.sessionmaker))
        c.clock.override(providers.Object(self.clock))
        c.gateway_factory.override(providers.Object(self.tg.factory))
        c.classifier.override(providers.Object(self.classifier))
        c.notifier.override(providers.Object(self.notifier))
        return c


async def boot(c: Container):
    await c.runtime().load()
    await c.assign_work().execute()
    workers = [c.worker_factory()(a) for a in await c.account_repo().list_active()]
    for w in workers:
        assert await w.start()
    return workers


async def tick(c: Container, workers) -> None:
    for w in workers:
        assert await w.step()
    bus, edit = c.bus(), c.attach_copy_edit()
    while not bus.queue.empty():
        await edit.execute(bus.queue.get_nowait())


async def setup_sources(c: Container, w: World) -> dict[int, int]:
    for _ in range(2):
        await c.account_repo().add(make_account())
    ids = {}
    for n in range(1, 7):
        repo = c.source_repo()
        s = await repo.add_candidate(f"chan_{n:02d}", "seed", 5)
        await repo.set_resolved(s.id, 100 + n, 1, SourceKind.channel, f"Канал {n}")
        w.tg.chats[f"chan_{n:02d}"] = Resolved(100 + n, 1, SourceKind.channel, f"Канал {n}")
        ids[n] = s.id
    return ids


async def run_pipeline(pg_sessionmaker, clock) -> tuple[World, dict[int, int]]:
    w = World(pg_sessionmaker, clock)
    c = w.container()
    ids = await setup_sources(c, w)
    w.tg.post(ids[1], 10, VACANCY, source_title="Канал 1")
    w.tg.post(ids[2], 20, "🔥 " + VACANCY + " #python", source_title="Канал 2")
    for n, text in JUNK.items():
        w.tg.post(ids[n], 30, text, source_title=f"Канал {n}")
    workers = await boot(c)
    await tick(c, workers)
    assert await c.classify_pending().step() == 0  # окно пакета ещё не прошло
    clock.advance(60)
    assert await c.classify_pending().step() == 1
    assert c.delivery_trigger().event.is_set()
    assert await c.deliver_accepted().execute() == 1
    # третья копия после доставки → карточка правится
    clock.advance(300)
    w.tg.post(ids[3], 40, VACANCY + "\nОткликаться сюда 👇", source_title="Канал 3")
    await tick(c, workers)
    return w, ids


async def test_pipeline_end_to_end(pg_sessionmaker, clock):
    w, _ = await run_pipeline(pg_sessionmaker, clock)
    assert len(w.notifier.sent) == 1
    card = w.notifier.sent[0]
    assert "👤 @author" in card and "Также в: Канал 2" in card  # фейковый LLM контакт не извлекает → отправитель
    assert len(w.classifier.calls) == 1 and len(w.classifier.calls[0]) == 1  # дубли и мусор не дошли до LLM
    assert len(w.notifier.edits) == 1
    assert w.notifier.edits[0][1].endswith("Также в: Канал 2, Канал 3")
    c = w.container()
    st = await c.usage_repo().get(clock.now().date())
    assert (st.read, st.passed_prefilter, st.llm_items, st.findings) == (6, 3, 1, 1)


async def test_restart_no_redelivery(pg_sessionmaker, clock):
    w, ids = await run_pipeline(pg_sessionmaker, clock)
    c2 = w.container()  # «рестарт»: новый контейнер, та же БД и тот же Telegram
    await c2.source_repo().reset_resolving()
    workers = await boot(c2)
    clock.advance(600)
    await tick(c2, workers)
    clock.advance(60)
    assert await c2.classify_pending().step() == 0
    assert await c2.redeliver_stale().execute() == 0
    assert await c2.deliver_accepted().execute() == 0
    assert len(w.notifier.sent) == 1 and len(w.classifier.calls) == 1
