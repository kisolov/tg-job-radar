import pytest

from radar.accounts.adapters.alerts import RecordingAlertSink
from radar.accounts.adapters.memory_repo import InMemoryAccountRepository
from radar.findings.adapters.memory_repo import InMemoryFindingRepository
from radar.findings.entities import FindingStatus
from radar.findings.similarity import fingerprint, normalize, shingles
from radar.ingest.ports import IncomingMessage
from radar.screening.adapters.fake_classifier import FakeClassifier
from radar.screening.adapters.memory_repos import InMemoryRequirementsRepository, InMemoryUsageRepository
from radar.screening.ports import LlmUnavailable
from radar.screening.service import ScreeningService
from radar.screening.usecases import ClassifyPending
from radar.shared.runtime import InMemoryOverridesStore, RuntimeConfig
from radar.shared.settings import Settings
from radar.sources.adapters.memory_repo import InMemorySourceRepository
from tests.unit.shared.test_settings import MIN_ENV


class Env:
    def __init__(self, clock, **settings):
        self.clock = clock
        self.findings = InMemoryFindingRepository()
        self.classifier = FakeClassifier()
        self.usage = InMemoryUsageRepository()
        self.alerts = RecordingAlertSink()
        self.sources = InMemorySourceRepository(InMemoryAccountRepository(), membership_cap=500)
        self.runtime = RuntimeConfig(Settings(_env_file=None, **{**MIN_ENV, **settings}), InMemoryOverridesStore())
        self.accepted_calls = 0

        async def on_accepted():
            self.accepted_calls += 1

        self.uc = ClassifyPending(
            findings=self.findings, classifier=self.classifier,
            screening=ScreeningService(self.usage, self.alerts, clock),
            requirements=InMemoryRequirementsRepository(), usage=self.usage, sources=self.sources,
            runtime=self.runtime, clock=clock, on_accepted=on_accepted,
        )

    async def add(self, source_id: int, text: str):
        m = IncomingMessage(source_id, 1, text, self.clock.now(), 1, "a", True, None, "l", "t")
        n = normalize(text)
        f, _ = await self.findings.cluster(m, n, fingerprint(n), shingles(n), 7, 0.6, self.clock.now())
        return f


PY = "Ищем Python-разработчика на FastAPI, удалённо, пишите @hr"
JAVA = "Ищем Java-разработчика в банк, офис, пишите @hr_bank"


async def test_waits_for_batch_window(clock):
    env = Env(clock)
    await env.runtime.load()
    await env.add(1, PY)
    assert await env.uc.step() == 0 and env.classifier.calls == []
    clock.advance(60)
    assert await env.uc.step() == 1
    assert len(env.classifier.calls) == 1


async def test_full_batch_goes_immediately(clock):
    env = Env(clock, LLM_BATCH_SIZE=2)
    await env.runtime.load()
    await env.add(1, PY)
    await env.add(2, JAVA)
    assert await env.uc.step() == 2
    assert len(env.classifier.calls) == 1 and len(env.classifier.calls[0]) == 2


async def test_classifies_accepts_and_counts(clock):
    env = Env(clock, LLM_BATCH_SIZE=2)
    await env.runtime.load()
    s = await env.sources.add_candidate("chan_one", "seed", 5)
    py = await env.add(s.id, PY)
    java = await env.add(2, JAVA)
    await env.uc.step()
    assert (await env.findings.get(py.id)).status is FindingStatus.accepted
    assert (await env.findings.get(java.id)).status is FindingStatus.rejected
    assert (await env.findings.get(py.id)).requirements_version == 1
    assert env.accepted_calls == 1
    st = await env.usage.get(clock.now().date())
    assert (st.llm_items, st.requests, st.prompt_tokens, st.reserved) == (2, 1, 20, 0)
    assert (await env.sources.get(s.id)).found_count == 1


async def test_llm_outage_keeps_pending_and_releases_budget(clock):
    env = Env(clock, LLM_BATCH_SIZE=1)
    await env.runtime.load()
    f = await env.add(1, PY)
    env.classifier.fail_next = 1
    with pytest.raises(LlmUnavailable):
        await env.uc.step()
    assert (await env.findings.get(f.id)).status is FindingStatus.pending
    assert (await env.usage.get(clock.now().date())).reserved == 0
    assert await env.uc.step() == 1


async def test_budget_exhausted_pauses(clock):
    env = Env(clock, LLM_BATCH_SIZE=1, LLM_DAILY_TOKEN_LIMIT=10)
    await env.runtime.load()
    await env.add(1, PY)
    assert await env.uc.step() == 0
    assert env.classifier.calls == [] and len(env.alerts.sent) == 1


async def test_runtime_override_applies(clock):
    env = Env(clock)
    await env.runtime.load()
    await env.runtime.set("LLM_BATCH_SIZE", "1")
    await env.add(1, PY)
    assert await env.uc.step() == 1  # пакет из 1 — без ожидания окна
