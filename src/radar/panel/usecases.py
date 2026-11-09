"""Операции панели. Чтение — модель чтения + уже существующие репозитории; запись — через сервисы модулей."""
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from radar.accounts.adapters.alerts import Alert, AlertLog
from radar.accounts.ports import AccountRepository
from radar.panel.ports import (
    FINDING_TABS,
    SOURCE_TABS,
    DayCounts,
    FindingDetail,
    FindingRow,
    FindingsFilter,
    FindingsPage,
    PanelReadModel,
    SourceCounts,
    SourcesFilter,
    SourcesPage,
)
from radar.screening.ports import DailyStats, UsageRepository
from radar.shared.clock import Clock
from radar.shared.runtime import RuntimeConfig
from radar.sources.ports import SourceRepository
from radar.sources.service import SourceService

PAGE = 20
RECENT = 4
ALERTS_SHOWN = 10
WEEK_DAYS = 7
PERIODS = {"today": None, "7d": timedelta(days=7), "30d": timedelta(days=30), "all": None}
KINDS = (None, "vacancy", "project")
SOURCE_KINDS = (None, "group", "channel")
SORTS = ("found", "read", "new")


def mask_phone(phone: str) -> str:
    d = "".join(ch for ch in phone if ch.isdigit())
    if len(d) < 10:
        return "•••" + d[-4:]
    if len(d) == 11 and d[0] == "7":  # код страны по цифрам не определить; +7 — основной случай
        return f"+7 {d[1:4]} ••• {d[-4:-2]} {d[-2:]}"
    return f"+{d[:-7]} ••• {d[-4:-2]} {d[-2:]}"


def _day_start(now: datetime) -> datetime:
    return datetime(now.year, now.month, now.day, tzinfo=UTC)


def _check(value, allowed, name: str) -> None:
    if value not in allowed:
        raise ValueError(f"{name}: недопустимое значение {value!r}")


@dataclass(frozen=True)
class AccountView:
    id: UUID
    phone: str
    status: str
    status_until: datetime | None
    groups: int
    joins_today: int
    joins_limit: int
    pace_factor: float
    last_flood_at: datetime | None
    channels: int
    last_error: str | None


@dataclass(frozen=True)
class LlmView:
    model: str
    token_limit: int
    batch_size: int
    batch_wait_s: int


@dataclass(frozen=True)
class DayBar:
    day: date
    n: int


@dataclass(frozen=True)
class Overview:
    day: date
    paused: bool
    stats: DailyStats
    counts: DayCounts
    cost: float
    llm: LlmView
    membership_cap: int
    accounts: list[AccountView]
    week: list[DayBar]
    recent: list[FindingRow]
    sources: SourceCounts
    bot: bool = True
    alerts: list[Alert] = field(default_factory=list)


class GetOverview:
    def __init__(self, read_model: PanelReadModel, accounts: AccountRepository, usage: UsageRepository,
                 runtime: RuntimeConfig, clock: Clock, alert_log: AlertLog | None = None,
                 bot_enabled: bool = True) -> None:
        self._rm, self._accounts, self._usage, self._runtime, self._clock = read_model, accounts, usage, runtime, clock
        self._alert_log, self._bot = alert_log, bot_enabled

    async def execute(self) -> Overview:
        now = self._clock.now()
        start = _day_start(now)
        stats = await self._usage.get(start.date())
        s = self._runtime.settings
        channels = await self._rm.channels_by_account()
        accounts = sorted(await self._accounts.list_all(), key=lambda a: a.phone)
        by_day = await self._rm.delivered_by_day(start - timedelta(days=WEEK_DAYS - 1))
        days = [start.date() - timedelta(days=i) for i in range(WEEK_DAYS - 1, -1, -1)]
        return Overview(
            day=start.date(),
            paused=await self._runtime.paused(),
            stats=stats,
            counts=await self._rm.day_counts(start, start + timedelta(days=1)),
            cost=(stats.prompt_tokens * s.LLM_PRICE_PER_1K_PROMPT
                  + stats.completion_tokens * s.LLM_PRICE_PER_1K_COMPLETION) / 1000,
            llm=LlmView(self._runtime.get("NEUROAPI_MODEL"), self._runtime.get("LLM_DAILY_TOKEN_LIMIT"),
                        self._runtime.get("LLM_BATCH_SIZE"), self._runtime.get("LLM_BATCH_WAIT_S")),
            membership_cap=s.MEMBERSHIP_CAP,
            accounts=[AccountView(
                id=a.id, phone=mask_phone(a.phone), status=a.status.value, status_until=a.status_until,
                groups=a.membership_count, joins_today=a.join.done_today, joins_limit=a.join.daily_limit,
                pace_factor=a.join.interval_factor, last_flood_at=a.join.last_flood_at,
                channels=channels.get(a.id, 0), last_error=a.last_error,
            ) for a in accounts],
            week=[DayBar(d, by_day.get(d, 0)) for d in days],
            recent=await self._rm.recent_delivered(RECENT),
            sources=await self._rm.source_counts(now - timedelta(days=7)),
            bot=self._bot,
            alerts=self._alert_log.recent()[:ALERTS_SHOWN] if self._alert_log else [],
        )


class ListFindings:
    def __init__(self, read_model: PanelReadModel, clock: Clock) -> None:
        self._rm, self._clock = read_model, clock

    async def execute(self, tab: str = "all", kind: str | None = None, period: str = "7d", q: str = "",
                      page: int = 1) -> FindingsPage:
        _check(tab, FINDING_TABS, "tab")
        _check(kind, KINDS, "kind")
        _check(period, PERIODS, "period")
        now = self._clock.now()
        since = _day_start(now) if period == "today" else (now - PERIODS[period] if PERIODS[period] else None)
        page = max(1, page)
        return await self._rm.findings(FindingsFilter(tab=tab, kind=kind, since=since, q=q.strip(), limit=PAGE,
                                                      offset=(page - 1) * PAGE))


class GetFinding:
    def __init__(self, read_model: PanelReadModel) -> None:
        self._rm = read_model

    async def execute(self, finding_id: int) -> FindingDetail | None:
        return await self._rm.finding(finding_id)


class ListPanelSources:
    def __init__(self, read_model: PanelReadModel, clock: Clock) -> None:
        self._rm, self._clock = read_model, clock

    async def execute(self, tab: str = "all", kind: str | None = None, sort: str = "found",
                      page: int = 1) -> tuple[SourcesPage, SourceCounts]:
        _check(tab, SOURCE_TABS, "tab")
        _check(kind, SOURCE_KINDS, "kind")
        _check(sort, SORTS, "sort")
        page = max(1, page)
        rows = await self._rm.sources(SourcesFilter(tab=tab, kind=kind, sort=sort, limit=PAGE,
                                                    offset=(page - 1) * PAGE))
        rows = replace(rows, items=[replace(r, account_phone=mask_phone(r.account_phone) if r.account_phone else None)
                                    for r in rows.items])
        return rows, await self._rm.source_counts(self._clock.now() - timedelta(days=7))


class RemoveSourceById:
    """Как /remove, но по id строки таблицы: инвайт-ссылки не надо нормализовать обратно."""

    def __init__(self, sources: SourceRepository, service: SourceService) -> None:
        self._sources, self._service = sources, service

    async def execute(self, source_id: int) -> bool:
        source = await self._sources.get(source_id)
        return source is not None and await self._service.remove(source.ref)
