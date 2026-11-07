import asyncio
from datetime import date

import pytest

from radar.screening.adapters.memory_repos import InMemoryRequirementsRepository, InMemoryUsageRepository
from radar.screening.adapters.sqlalchemy_repos import SqlAlchemyRequirementsRepository, SqlAlchemyUsageRepository
from radar.screening.ports import Usage
from radar.screening.requirements_default import DEFAULT_REQUIREMENTS

DAY = date(2026, 11, 4)


@pytest.fixture
def usage_repo(backend, request):
    if backend == "memory":
        return InMemoryUsageRepository()
    return SqlAlchemyUsageRepository(request.getfixturevalue("pg_sessionmaker"))


@pytest.fixture
def req_repo(backend, request):
    if backend == "memory":
        return InMemoryRequirementsRepository()
    return SqlAlchemyRequirementsRepository(request.getfixturevalue("pg_sessionmaker"))


async def test_budget_blocks_over_limit(usage_repo):
    assert await usage_repo.reserve(DAY, 800, limit=1000)
    assert not await usage_repo.reserve(DAY, 300, limit=1000)
    assert await usage_repo.reserve(DAY, 200, limit=1000)


async def test_commit_replaces_reservation_with_fact(usage_repo):
    assert await usage_repo.reserve(DAY, 800, limit=1000)
    await usage_repo.commit_usage(DAY, 800, Usage(300, 100))
    s = await usage_repo.get(DAY)
    assert (s.reserved, s.prompt_tokens, s.completion_tokens, s.requests) == (0, 300, 100, 1)
    assert await usage_repo.reserve(DAY, 600, limit=1000)  # 400 факта + 600


async def test_release_reservation(usage_repo):
    await usage_repo.reserve(DAY, 900, limit=1000)
    await usage_repo.release(DAY, 900)
    assert (await usage_repo.get(DAY)).reserved == 0


async def test_concurrent_reserve_never_exceeds(usage_repo):
    results = await asyncio.gather(*(usage_repo.reserve(DAY, 300, limit=1000) for _ in range(6)))
    assert results.count(True) == 3
    assert (await usage_repo.get(DAY)).reserved == 900


async def test_bump_counters(usage_repo):
    await usage_repo.bump(DAY, read=3, passed_prefilter=1)
    await usage_repo.bump(DAY, read=2, findings=1)
    s = await usage_repo.get(DAY)
    assert (s.read, s.passed_prefilter, s.findings, s.llm_items) == (5, 1, 1, 0)
    empty = await usage_repo.get(date(2026, 1, 1))
    assert empty.read == 0 and empty.prompt_tokens == 0


async def test_bump_rejects_unknown_counter(usage_repo):
    with pytest.raises(ValueError):
        await usage_repo.bump(DAY, reserved=5)


async def test_requirements_versioned(req_repo):
    await req_repo.seed_default()  # TRUNCATE перед тестом стирает строку из миграции; повтор безопасен
    await req_repo.seed_default()
    v, text = await req_repo.current()
    assert v == 1 and text == DEFAULT_REQUIREMENTS
    assert await req_repo.set("Новые требования") == 2
    assert await req_repo.current() == (2, "Новые требования")


async def test_reset_reserved_frees_budget_left_by_a_crash(usage_repo):
    """M8: резерв пакета, который был в полёте при падении процесса, на старте снимается."""
    d = date(2026, 11, 4)
    assert await usage_repo.reserve(d, 900, 1000)
    assert not await usage_repo.reserve(d, 200, 1000)
    assert await usage_repo.reset_reserved() == 1
    assert (await usage_repo.get(d)).reserved == 0
    assert await usage_repo.reserve(d, 200, 1000)
