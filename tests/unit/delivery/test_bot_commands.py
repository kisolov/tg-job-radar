import pytest
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from radar.accounts.adapters.memory_repo import InMemoryAccountRepository
from radar.delivery.bot import BotDeps, build_router
from radar.screening.adapters.memory_repos import InMemoryRequirementsRepository, InMemoryUsageRepository
from radar.shared.runtime import InMemoryOverridesStore, RuntimeConfig
from radar.shared.settings import Settings
from radar.sources.adapters.memory_repo import InMemorySourceRepository
from radar.sources.entities import SourceKind
from radar.sources.service import SourceService
from tests.factories import make_account
from tests.unit.delivery.botkit import make_bot, send
from tests.unit.shared.test_settings import MIN_ENV

OWNER = 1001
STRANGER = 666


@pytest.fixture
async def env(clock):
    accounts = InMemoryAccountRepository()
    sources = InMemorySourceRepository(accounts, membership_cap=500)
    runtime = RuntimeConfig(Settings(_env_file=None, **{**MIN_ENV, "OWNER_TELEGRAM_ID": OWNER}),
                            InMemoryOverridesStore())
    await runtime.load()
    deps = BotDeps(
        accounts=accounts, sources=sources, source_service=SourceService(sources, accounts),
        requirements=InMemoryRequirementsRepository(), usage=InMemoryUsageRepository(), runtime=runtime,
        clock=clock,
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(build_router(OWNER, deps))
    bot, session = make_bot()

    class Env:
        pass

    e = Env()
    e.deps, e.dp, e.bot, e.session = deps, dp, bot, session

    async def say(text, user=OWNER):
        await send(dp, bot, text, user)
        return session.texts[-1] if session.texts else None

    e.say = say
    return e


async def test_non_owner_ignored(env):
    for cmd in ("/status", "/add t.me/x_chat", "/setreq", "/pause", "/set LLM_BATCH_SIZE 1", "привет"):
        await env.say(cmd, user=STRANGER)
    assert env.session.calls == []
    assert await env.deps.sources.find("x_chat") is None
    assert not await env.deps.runtime.paused()


async def test_setreq_flow(env):
    reply = await env.say("/setreq")
    assert "следующим сообщением" in reply
    reply = await env.say("Присылать только Django-вакансии")
    assert "версия 2" in reply
    assert await env.deps.requirements.current() == (2, "Присылать только Django-вакансии")
    assert "Django" in await env.say("/req")


async def test_setreq_cancel(env):
    await env.say("/setreq")
    await env.say("/cancel")
    assert (await env.deps.requirements.current())[0] == 1


async def test_pause_resume(env):
    await env.say("/pause")
    assert await env.deps.runtime.paused()
    await env.say("/resume")
    assert not await env.deps.runtime.paused()


async def test_set_rejects_unknown_key(env):
    reply = await env.say("/set BOT_TOKEN hacked")
    assert "Нельзя" in reply and "LLM_BATCH_SIZE" in reply
    reply = await env.say("/set LLM_BATCH_SIZE много")
    assert "int" in reply
    reply = await env.say("/set LLM_BATCH_SIZE 4")
    assert "LLM_BATCH_SIZE = 4" in reply and env.deps.runtime.get("LLM_BATCH_SIZE") == 4


async def test_add_remove_sources(env):
    reply = await env.say("/add t.me/new_chat\n@other_chat https://t.me/new_chat")
    assert "new_chat" in reply and "other_chat" in reply
    assert (await env.deps.sources.find("new_chat")).added_by == "owner"
    assert "удалён" in await env.say("/remove @new_chat")
    assert "не найден" in await env.say("/remove @nothing_here")


async def test_status_report(env):
    await env.deps.accounts.add(make_account())
    await env.deps.sources.add_candidate("cand_one", "seed", 5)
    await env.deps.usage.bump(env.deps.clock.now().date(), read=120, passed_prefilter=7, llm_items=5, findings=2)
    reply = await env.say("/status")
    for part in ("active: 1", "candidate: 1", "прочитано 120", "предфильтр 7", "в LLM 5", "находок 2"):
        assert part in reply


async def test_sources_list(env):
    s = await env.deps.sources.add_candidate("good_chat", "seed", 5)
    await env.deps.sources.set_resolved(s.id, 1, 1, SourceKind.group, "Good chat")
    await env.deps.sources.add_found(s.id, 4)
    reply = await env.say("/sources")
    assert "Good chat" in reply and "4" in reply
