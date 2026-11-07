"""Выборки панели на настоящем Postgres (фейка у модели чтения нет — см. спеку веб-панели)."""
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from radar.findings.entities import Classification
from radar.panel.adapters.sqlalchemy_read_model import SqlAlchemyPanelReadModel
from radar.panel.ports import FindingsFilter, SourcesFilter
from radar.shared.db import transaction
from radar.shared.models import accounts, finding_copies, findings, sources

T0 = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
DAY = (datetime(2026, 11, 6, tzinfo=UTC), datetime(2026, 11, 7, tzinfo=UTC))


def cls(kind="vacancy", summary="Python-бэкенд FastAPI", relevant=True):
    return asdict(Classification(relevant, kind, summary, "250–300к", "удалёнка", "@hr_anna", "подходит по стеку"))


class Seed:
    def __init__(self, sf):
        self.sf = sf
        self._fid = 0

    async def account(self, phone="+79001234567"):
        aid = uuid4()
        async with transaction(self.sf) as s:
            await s.execute(accounts.insert().values(
                id=aid, phone=phone, api_id=1, api_hash_enc="x", session_enc="x", device_profile="default",
                status="active", membership_count=0, join_state={}, resolve_state={}))
        return aid

    async def source(self, ref, status="active", kind="channel", joined=False, account=None, found=0, read=0,
                     passed=0, added_by="seed", created_at=T0, title=None):
        invite = ref.startswith("+")
        async with transaction(self.sf) as s:
            r = await s.execute(sources.insert().values(
                username=None if invite else ref, invite_hash=ref if invite else None, kind=kind,
                title=title or ref, status=status, assigned_account_id=account, joined=joined, found_count=found,
                read_count=read, passed_count=passed, added_by=added_by, created_at=created_at,
            ).returning(sources.c.id))
            return r.scalar_one()

    async def finding(self, status="delivered", created_at=T0, delivered_at=None, classification=None,
                      text="Ищем разработчика в команду\nудалённо", copies=(("Python Jobs", 1),),
                      sender="hr_anna"):
        async with transaction(self.sf) as s:
            fid = (await s.execute(findings.insert().values(
                fingerprint=f"fp{self._fid}", shingles=b"", shingle_count=0, text_snapshot=text,
                link_snapshot="https://t.me/ru_pythonjobs/8032", sender_username=sender, sender_is_user=True,
                status=status, classification=classification, requirements_version=3 if classification else None,
                delivered_at=delivered_at, created_at=created_at,
            ).returning(findings.c.id))).scalar_one()
            self._fid += 1
            for i, (title, source_id) in enumerate(copies):
                await s.execute(finding_copies.insert().values(
                    finding_id=fid, source_id=source_id, message_id=fid * 100 + i, link=f"https://t.me/x/{i}",
                    source_title=title, created_at=created_at + timedelta(minutes=i)))
        return fid


@pytest.fixture
def seed(pg_sessionmaker):
    return Seed(pg_sessionmaker)


@pytest.fixture
def rm(pg_sessionmaker):
    return SqlAlchemyPanelReadModel(pg_sessionmaker)


async def test_day_counts(seed, rm):
    await seed.finding("delivered", delivered_at=T0, classification=cls(), copies=(("A", 1), ("B", 2), ("C", 3)))
    await seed.finding("rejected", classification=cls(relevant=False))
    await seed.finding("pending")
    await seed.finding("accepted", classification=cls())
    await seed.finding("delivered", created_at=T0 - timedelta(days=1), delivered_at=T0 - timedelta(days=1),
                       classification=cls())
    await seed.source("auto1", status="candidate", added_by="discovery")
    await seed.source("auto_old", status="candidate", added_by="discovery", created_at=T0 - timedelta(days=2))
    c = await rm.day_counts(*DAY)
    assert (c.unique, c.copies, c.accepted, c.delivered) == (4, 6, 2, 1)
    assert (c.pending, c.queued, c.discovered) == (1, 1, 1)


async def test_delivered_by_day_and_recent(seed, rm):
    for d in (0, 0, 1, 3):
        await seed.finding("delivered", created_at=T0 - timedelta(days=d), delivered_at=T0 - timedelta(days=d),
                           classification=cls(summary=f"вакансия {d}"))
    await seed.finding("delivered", delivered_at=T0 - timedelta(days=9), classification=cls())
    by_day = await rm.delivered_by_day(DAY[0] - timedelta(days=6))
    assert by_day == {date(2026, 11, 6): 2, date(2026, 11, 5): 1, date(2026, 11, 3): 1}
    recent = await rm.recent_delivered(2)
    assert [r.title for r in recent] == ["вакансия 0", "вакансия 0"]
    assert recent[0].source_title == "Python Jobs" and recent[0].copies == 1


async def test_findings_tabs_filters_and_search(seed, rm):
    await seed.finding("delivered", delivered_at=T0, classification=cls("vacancy", "FastAPI маркетплейс"))
    await seed.finding("delivered", delivered_at=T0, classification=cls("project", "Бот для барбершопа"))
    await seed.finding("rejected", classification=cls("vacancy", "Java senior", relevant=False))
    await seed.finding("pending", text="Нужен бот 50% предоплата")
    await seed.finding("delivering", classification=cls("project", "Парсер"))
    await seed.finding("delivered", created_at=T0 - timedelta(days=10), classification=cls())

    page = await rm.findings(FindingsFilter(since=T0 - timedelta(days=7)))
    assert page.total == 5 and page.tabs == {"all": 5, "delivered": 2, "queue": 1, "pending": 1, "rejected": 1}
    assert [r.status for r in page.items][:1] == ["delivering"]  # новые сверху, при равенстве — по id

    projects = await rm.findings(FindingsFilter(tab="delivered", kind="project"))
    assert [r.title for r in projects.items] == ["Бот для барбершопа"] and projects.tabs["all"] == 2

    found = await rm.findings(FindingsFilter(q="МАРКЕТ"))  # без учёта регистра, и по summary
    assert [r.title for r in found.items] == ["FastAPI маркетплейс"]
    pct = await rm.findings(FindingsFilter(q="50%"))
    assert pct.total == 1 and pct.items[0].title == "Нужен бот 50% предоплата"  # % не шаблон, а символ

    paged = await rm.findings(FindingsFilter(limit=2, offset=4))
    assert len(paged.items) == 2 and paged.total == 6


async def test_finding_detail(seed, rm):
    fid = await seed.finding("delivered", delivered_at=T0, classification=cls(),
                             copies=(("Python Jobs", 1), ("Удалёнка IT", 2)))
    d = await rm.finding(fid)
    assert d.row.title == "Python-бэкенд FastAPI" and d.row.copies == 2
    assert d.reason == "подходит по стеку" and d.requirements_version == 3 and d.sender_username == "hr_anna"
    assert [c.source_title for c in d.copies] == ["Python Jobs", "Удалёнка IT"]
    assert await rm.finding(fid + 999) is None


async def test_sources_tabs_sort_and_counts(seed, rm):
    acc = await seed.account("+79001234567")
    await seed.source("pyjobs", kind="channel", account=acc, found=14, read=1920, passed=211)
    await seed.source("freelance", kind="group", joined=True, account=acc, found=9, read=6410)
    await seed.source("bots_orders", kind="group", joined=False, account=acc)
    await seed.source("+AbCdEf", status="candidate", kind=None, added_by="discovery")
    await seed.source("+PrivCh", kind="channel", joined=False, account=acc)  # приватный канал ждёт вступления
    await seed.source("hh_feed", status="rejected")
    await seed.source("old_chat", status="dead")

    reading = await rm.sources(SourcesFilter(tab="reading"))
    assert [r.ref for r in reading.items] == ["pyjobs", "freelance"] and reading.total == 2
    assert reading.items[0].account_phone == "+79001234567" and reading.items[0].link == "https://t.me/pyjobs"

    by_read = await rm.sources(SourcesFilter(tab="reading", sort="read"))
    assert [r.ref for r in by_read.items] == ["freelance", "pyjobs"]

    waiting = await rm.sources(SourcesFilter(tab="waiting"))
    assert {(r.ref, r.status) for r in waiting.items} == {("bots_orders", "awaiting_join"),
                                                          ("+PrivCh", "awaiting_join"),
                                                          ("+AbCdEf", "awaiting_resolve")}
    invite = next(r for r in waiting.items if r.ref == "+AbCdEf")
    assert invite.link == "https://t.me/+AbCdEf"

    groups = await rm.sources(SourcesFilter(kind="group"))
    assert groups.total == 2

    fid_source = (await rm.sources(SourcesFilter(tab="reading"))).items[0].id
    await seed.finding("delivered", delivered_at=T0, classification=cls(), copies=(("pyjobs", fid_source),))
    c = await rm.source_counts(T0 - timedelta(days=7))
    assert (c.reading, c.reading_groups, c.reading_channels) == (2, 1, 1)
    assert (c.awaiting_join, c.awaiting_resolve, c.resolve_from_discovery) == (2, 1, 1)
    assert (c.dead, c.rejected, c.productive) == (1, 1, 1)
    assert await rm.channels_by_account() == {acc: 2}  # каналы на аккаунте, включая ждущий вступления
