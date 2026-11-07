"""Модель чтения панели: выборки поверх таблиц модулей. Правил нет — только чтение."""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Protocol
from uuid import UUID

FindingTab = Literal["all", "delivered", "queue", "pending", "rejected"]
SourceTab = Literal["all", "reading", "waiting", "dead", "rejected"]
SourceUiStatus = Literal["reading", "awaiting_join", "awaiting_resolve", "dead", "rejected"]
SourceSort = Literal["found", "read", "new"]

FINDING_TABS: tuple[FindingTab, ...] = ("all", "delivered", "queue", "pending", "rejected")
SOURCE_TABS: tuple[SourceTab, ...] = ("all", "reading", "waiting", "dead", "rejected")


@dataclass(frozen=True)
class DayCounts:
    """Находки за сутки [start, end) и текущие очереди."""

    unique: int  # новых находок (кластеров)
    copies: int  # всех копий, включая первые
    accepted: int  # из новых — подошли (accepted/delivering/delivered)
    delivered: int  # доставлено за сутки
    pending: int  # ждут LLM сейчас
    queued: int  # подошли, ждут отправки сейчас
    discovered: int  # источников из автопоиска за сутки


@dataclass(frozen=True)
class FindingRow:
    id: int
    status: str
    kind: str | None
    title: str
    money: str | None
    work_format: str | None
    contact: str | None
    source_title: str | None
    copies: int
    created_at: datetime
    delivered_at: datetime | None


@dataclass(frozen=True)
class CopyRow:
    source_title: str | None
    link: str
    created_at: datetime


@dataclass(frozen=True)
class FindingDetail:
    row: FindingRow
    text: str
    link: str
    reason: str | None
    requirements_version: int | None
    sender_username: str | None
    copies: list[CopyRow] = field(default_factory=list)


@dataclass(frozen=True)
class FindingsFilter:
    tab: FindingTab = "all"
    kind: str | None = None
    since: datetime | None = None
    q: str = ""
    limit: int = 20
    offset: int = 0


@dataclass(frozen=True)
class FindingsPage:
    items: list[FindingRow]
    total: int  # в текущей вкладке
    tabs: dict[str, int]  # счётчик каждой вкладки при тех же прочих фильтрах


@dataclass(frozen=True)
class SourceRow:
    id: int
    title: str | None
    ref: str
    link: str | None
    kind: str | None
    status: SourceUiStatus
    account_phone: str | None
    found: int
    read: int
    passed: int
    added_by: str
    created_at: datetime


@dataclass(frozen=True)
class SourcesFilter:
    tab: SourceTab = "all"
    kind: str | None = None
    sort: SourceSort = "found"
    limit: int = 20
    offset: int = 0


@dataclass(frozen=True)
class SourcesPage:
    items: list[SourceRow]
    total: int


@dataclass(frozen=True)
class SourceCounts:
    reading: int
    reading_groups: int
    reading_channels: int
    awaiting_join: int
    awaiting_resolve: int
    resolve_from_discovery: int
    dead: int
    rejected: int
    productive: int  # дали находки с since


class PanelReadModel(Protocol):
    async def day_counts(self, start: datetime, end: datetime) -> DayCounts: ...

    async def delivered_by_day(self, since: datetime) -> dict[date, int]: ...

    async def recent_delivered(self, limit: int) -> list[FindingRow]: ...

    async def findings(self, f: FindingsFilter) -> FindingsPage: ...

    async def finding(self, finding_id: int) -> FindingDetail | None: ...

    async def sources(self, f: SourcesFilter) -> SourcesPage: ...

    async def source_counts(self, productive_since: datetime) -> SourceCounts: ...

    async def channels_by_account(self) -> dict[UUID, int]: ...
