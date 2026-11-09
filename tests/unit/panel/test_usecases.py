from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from radar.accounts.adapters.alerts import AlertLog, TeeAlertSink
from radar.accounts.adapters.memory_repo import InMemoryAccountRepository
from radar.accounts.entities import AccountStatus
from radar.panel.ports import (
    DayCounts,
    FindingsFilter,
    FindingsPage,
    SourceCounts,
    SourceRow,
    SourcesFilter,
    SourcesPage,
)
from radar.panel.usecases import GetOverview, ListFindings, ListPanelSources, RemoveSourceById, mask_phone
from radar.screening.adapters.memory_repos import InMemoryUsageRepository
from radar.screening.ports import Usage
from radar.shared.clock import FakeClock
from radar.shared.runtime import InMemoryOverridesStore, RuntimeConfig
from radar.shared.settings import Settings
from radar.sources.adapters.memory_repo import InMemorySourceRepository
from radar.sources.entities import SourceStatus
from radar.sources.service import SourceService
from tests.factories import make_account
from tests.unit.shared.test_settings import MIN_ENV

NOW = datetime(2026, 11, 6, 14, 32, tzinfo=UTC)
COUNTS = SourceCounts(10, 4, 6, 2, 3, 1, 1, 1, 5)


class StubReadModel:
    """Заглушка модели чтения для тестов композиции; фильтры запоминает."""

    def __init__(self):
        self.calls = []

    async def day_counts(self, start, end):
        self.calls.append(("day", start, end))
        return DayCounts(unique=20, copies=50, accepted=4, delivered=3, pending=2, queued=1, discovered=5)

    async def delivered_by_day(self, since):
        self.calls.append(("week", since))
        return {date(2026, 11, 6): 3, date(2026, 11, 3): 7}

    async def recent_delivered(self, limit):
        return []

    async def source_counts(self, since):
        self.calls.append(("sources", since))
        return COUNTS

    async def channels_by_account(self):
        return self.channels

    async def findings(self, f):
        self.calls.append(("findings", f))
        return FindingsPage([], 0, {})

    async def sources(self, f):
        self.calls.append(("sources_page", f))
        row = SourceRow(1, "Python Jobs", "pyjobs", "https://t.me/pyjobs", "channel", "reading", "+79001234567",
                        14, 1920, 211, "seed", NOW)
        return SourcesPage([row, replace(row, id=2, account_phone=None)], 2)


def runtime(**env) -> RuntimeConfig:
    return RuntimeConfig(Settings(_env_file=None, **{**MIN_ENV, "LLM_PRICE_PER_1K_PROMPT": 0.5,
                                                    "LLM_PRICE_PER_1K_COMPLETION": 1.0, **env}),
                         InMemoryOverridesStore())


def test_mask_phone():
    assert mask_phone("+79001234567") == "+7 900 ••• 45 67"
    assert mask_phone("+380501234567") == "+38050 ••• 45 67"
    assert mask_phone("123") == "•••123"


async def test_overview_composes_everything():
    accounts = InMemoryAccountRepository()
    a = make_account("+79001234567", membership_count=212)
    a.join = replace(a.join, done_today=18, daily_limit=27, interval_factor=1.5)
    b = make_account("+79011112233", status=AccountStatus.flood_wait, status_until=NOW + timedelta(hours=2),
                     last_error="FloodWait 7800 с на резолве")
    await accounts.add(a)
    await accounts.add(b)
    usage = InMemoryUsageRepository()
    await usage.bump(NOW.date(), read=18432, passed_prefilter=642, llm_items=211, findings=9)
    await usage.reserve(NOW.date(), 1000, 10**9)
    await usage.commit_usage(NOW.date(), 1000, Usage(prompt_tokens=400_000, completion_tokens=12_000))
    rm = StubReadModel()
    rm.channels = {a.id: 403}
    rt = runtime()
    await rt.set_paused(True)

    log = AlertLog(FakeClock(NOW))
    await TeeAlertSink(log).notify("⚠️ LLM недоступен 61 мин")
    o = await GetOverview(rm, accounts, usage, rt, FakeClock(NOW), alert_log=log, bot_enabled=False).execute()
    assert o.bot is False and [(a.at, a.text) for a in o.alerts] == [(NOW, "⚠️ LLM недоступен 61 мин")]

    assert o.day == date(2026, 11, 6) and o.paused is True
    assert ("day", datetime(2026, 11, 6, tzinfo=UTC), datetime(2026, 11, 7, tzinfo=UTC)) in rm.calls
    assert o.stats.read == 18432 and o.stats.requests == 1 and o.counts.unique == 20
    assert o.cost == pytest.approx(400 * 0.5 + 12 * 1.0)
    assert o.llm.model == rt.get("NEUROAPI_MODEL") and o.llm.token_limit == 2_000_000
    assert o.llm.batch_size == 10 and o.llm.batch_wait_s == 60
    assert [d.day for d in o.week] == [date(2026, 10, 31) + timedelta(days=i) for i in range(7)]
    assert [d.n for d in o.week] == [0, 0, 0, 7, 0, 0, 3]
    assert o.sources == COUNTS and o.membership_cap == 500
    first = next(x for x in o.accounts if x.phone == "+7 900 ••• 45 67")
    assert (first.status, first.groups, first.joins_today, first.joins_limit) == ("active", 212, 18, 27)
    assert first.pace_factor == 1.5 and first.channels == 403
    flood = next(x for x in o.accounts if x.status == "flood_wait")
    assert flood.status_until == NOW + timedelta(hours=2) and flood.last_error.startswith("FloodWait")
    assert flood.channels == 0


async def test_list_findings_period_and_validation():
    rm = StubReadModel()
    uc = ListFindings(rm, FakeClock(NOW))
    await uc.execute(tab="delivered", kind="project", period="today", q=" бот ", page=2)
    f = rm.calls[-1][1]
    assert f == FindingsFilter(tab="delivered", kind="project", since=datetime(2026, 11, 6, tzinfo=UTC),
                               q="бот", limit=20, offset=20)
    await uc.execute(period="7d")
    assert rm.calls[-1][1].since == NOW - timedelta(days=7) and rm.calls[-1][1].kind is None
    await uc.execute(period="all")
    assert rm.calls[-1][1].since is None
    for bad in (dict(tab="x"), dict(kind="x"), dict(period="x")):
        with pytest.raises(ValueError):
            await uc.execute(**bad)


async def test_list_sources_page_and_counts():
    rm = StubReadModel()
    page, counts = await ListPanelSources(rm, FakeClock(NOW)).execute(tab="waiting", kind="group", sort="new",
                                                                       page=3)
    assert rm.calls[0] == ("sources_page", SourcesFilter(tab="waiting", kind="group", sort="new", limit=20,
                                                         offset=40))
    assert ("sources", NOW - timedelta(days=7)) in rm.calls and counts == COUNTS
    assert [r.account_phone for r in page.items] == ["+7 900 ••• 45 67", None]
    with pytest.raises(ValueError):
        await ListPanelSources(rm, FakeClock(NOW)).execute(sort="x")


async def test_remove_source_by_id():
    accounts = InMemoryAccountRepository()
    repo = InMemorySourceRepository(accounts, membership_cap=500)
    service = SourceService(sources=repo, accounts=accounts, aggregator_domains=[])
    s = await repo.add_candidate("+AbCd", "owner", 9)
    uc = RemoveSourceById(repo, service)
    assert await uc.execute(s.id) is True
    assert (await repo.get(s.id)).status is SourceStatus.rejected
    assert await uc.execute(99999) is False
