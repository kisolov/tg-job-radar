from datetime import date, datetime
from uuid import UUID

import sqlalchemy as sa

from radar.panel.ports import (
    FINDING_TABS,
    CopyRow,
    DayCounts,
    FindingDetail,
    FindingRow,
    FindingsFilter,
    FindingsPage,
    SourceCounts,
    SourceRow,
    SourcesFilter,
    SourcesPage,
)
from radar.shared.db import SessionFactory
from radar.shared.models import accounts as at
from radar.shared.models import finding_copies as ct
from radar.shared.models import findings as ft
from radar.shared.models import sources as st

TITLE_MAX = 140
FOUND = ("accepted", "delivering", "delivered")
TAB_STATUSES = {"delivered": ("delivered",), "queue": ("accepted", "delivering"), "pending": ("pending",),
                "rejected": ("rejected",)}

_cls = ft.c.classification
_kind = _cls["kind"].astext

# Статус источника на экране (см. спеку): вычисляется из status/kind/joined.
UI_STATUS = sa.case(
    # членство нужно группам и всем инвайтам (Source.needs_membership)
    (sa.and_(st.c.status == "active", sa.or_(sa.and_(st.c.kind == "channel", st.c.invite_hash.is_(None)),
                                             st.c.joined.is_(True))), "reading"),
    (st.c.status == "active", "awaiting_join"),
    (st.c.status.in_(("candidate", "resolving")), "awaiting_resolve"),
    else_=st.c.status,
).label("ui_status")
SOURCE_TAB_STATUSES = {"reading": ("reading",), "waiting": ("awaiting_join", "awaiting_resolve"),
                       "dead": ("dead",), "rejected": ("rejected",)}


def _title(text: str, summary: str | None) -> str:
    if summary:
        return summary
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return first if len(first) <= TITLE_MAX else first[:TITLE_MAX - 1] + "…"


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


_copies = sa.select(sa.func.count()).where(ct.c.finding_id == ft.c.id).scalar_subquery().label("copies")
_first_title = (sa.select(ct.c.source_title).where(ct.c.finding_id == ft.c.id)
                .order_by(ct.c.created_at, ct.c.source_id, ct.c.message_id).limit(1)
                .scalar_subquery().label("source_title"))
_ROW_COLS = (ft.c.id, ft.c.status, ft.c.text_snapshot, _cls, ft.c.created_at, ft.c.delivered_at, _copies,
             _first_title)


def _finding_row(r) -> FindingRow:
    c = r.classification or {}
    return FindingRow(
        id=r.id, status=r.status, kind=c.get("kind"), title=_title(r.text_snapshot, c.get("summary")),
        money=c.get("money"), work_format=c.get("work_format"), contact=c.get("contact"),
        source_title=r.source_title, copies=r.copies, created_at=r.created_at, delivered_at=r.delivered_at,
    )


def _source_link(username: str | None, invite: str | None) -> str | None:
    if username:
        return f"https://t.me/{username}"
    if invite:
        return f"https://t.me/{invite}"
    return None


class SqlAlchemyPanelReadModel:
    def __init__(self, sf: SessionFactory) -> None:
        self._sf = sf

    async def _scalar(self, q) -> int:
        async with self._sf() as s:
            return int((await s.execute(q)).scalar_one() or 0)

    async def day_counts(self, start: datetime, end: datetime) -> DayCounts:
        made = sa.and_(ft.c.created_at >= start, ft.c.created_at < end)
        count = sa.func.count()
        q = sa.select(
            sa.select(count).where(made).scalar_subquery(),
            sa.select(count).select_from(ct).where(ct.c.created_at >= start, ct.c.created_at < end)
            .scalar_subquery(),
            sa.select(count).where(made, ft.c.status.in_(FOUND)).scalar_subquery(),
            sa.select(count).select_from(ft).where(ft.c.delivered_at >= start, ft.c.delivered_at < end)
            .scalar_subquery(),
            sa.select(count).select_from(ft).where(ft.c.status == "pending").scalar_subquery(),
            sa.select(count).select_from(ft).where(ft.c.status.in_(("accepted", "delivering"))).scalar_subquery(),
            sa.select(count).select_from(st).where(st.c.added_by == "discovery", st.c.created_at >= start,
                                                   st.c.created_at < end).scalar_subquery(),
        )
        async with self._sf() as s:
            row = (await s.execute(q)).one()
        return DayCounts(*(int(v) for v in row))

    async def delivered_by_day(self, since: datetime) -> dict[date, int]:
        day = sa.func.date(sa.func.timezone("UTC", ft.c.delivered_at)).label("day")
        q = sa.select(day, sa.func.count()).where(ft.c.delivered_at >= since).group_by(day)
        async with self._sf() as s:
            return {r[0]: int(r[1]) for r in (await s.execute(q)).all()}

    async def recent_delivered(self, limit: int) -> list[FindingRow]:
        q = (sa.select(*_ROW_COLS).where(ft.c.status == "delivered")
             .order_by(ft.c.delivered_at.desc(), ft.c.id.desc()).limit(limit))
        async with self._sf() as s:
            return [_finding_row(r) for r in (await s.execute(q)).all()]

    async def findings(self, f: FindingsFilter) -> FindingsPage:
        where = []
        if f.kind:
            where.append(_kind == f.kind)
        if f.since:
            where.append(ft.c.created_at >= f.since)
        if f.q.strip():
            pat = _like(f.q.strip())
            where.append(sa.or_(ft.c.text_snapshot.ilike(pat, escape="\\"),
                                _cls["summary"].astext.ilike(pat, escape="\\"),
                                ft.c.sender_username.ilike(pat, escape="\\")))
        tab_q = sa.select(ft.c.status, sa.func.count()).where(*where).group_by(ft.c.status)
        async with self._sf() as s:
            by_status = {r[0]: int(r[1]) for r in (await s.execute(tab_q)).all()}
            tabs = {t: sum(by_status.get(x, 0) for x in TAB_STATUSES[t]) for t in FINDING_TABS if t != "all"}
            tabs = {"all": sum(by_status.values()), **tabs}
            if f.tab != "all":
                where.append(ft.c.status.in_(TAB_STATUSES[f.tab]))
            q = (sa.select(*_ROW_COLS).where(*where).order_by(ft.c.created_at.desc(), ft.c.id.desc())
                 .limit(f.limit).offset(f.offset))
            items = [_finding_row(r) for r in (await s.execute(q)).all()]
        return FindingsPage(items, tabs[f.tab], tabs)

    async def finding(self, finding_id: int) -> FindingDetail | None:
        q = sa.select(*_ROW_COLS, ft.c.link_snapshot, ft.c.requirements_version, ft.c.sender_username).where(
            ft.c.id == finding_id)
        cq = (sa.select(ct.c.source_title, ct.c.link, ct.c.created_at).where(ct.c.finding_id == finding_id)
              .order_by(ct.c.created_at, ct.c.source_id, ct.c.message_id))
        async with self._sf() as s:
            r = (await s.execute(q)).first()
            if r is None:
                return None
            copies = [CopyRow(c.source_title, c.link, c.created_at) for c in (await s.execute(cq)).all()]
        c = r.classification or {}
        return FindingDetail(row=_finding_row(r), text=r.text_snapshot, link=r.link_snapshot, reason=c.get("reason"),
                             requirements_version=r.requirements_version, sender_username=r.sender_username,
                             copies=copies)

    async def sources(self, f: SourcesFilter) -> SourcesPage:
        base = sa.select(st, UI_STATUS, at.c.phone).select_from(
            st.outerjoin(at, at.c.id == st.c.assigned_account_id)).subquery()
        where = []
        if f.tab != "all":
            where.append(base.c.ui_status.in_(SOURCE_TAB_STATUSES[f.tab]))
        if f.kind:
            where.append(base.c.kind == f.kind)
        order = {"found": (base.c.found_count.desc(), base.c.read_count.desc()),
                 "read": (base.c.read_count.desc(),),
                 "new": (base.c.created_at.desc(),)}[f.sort]
        q = sa.select(base).where(*where).order_by(*order, base.c.id).limit(f.limit).offset(f.offset)
        total_q = sa.select(sa.func.count()).select_from(base).where(*where)
        async with self._sf() as s:
            rows = (await s.execute(q)).all()
            total = int((await s.execute(total_q)).scalar_one())
        items = [SourceRow(
            id=r.id, title=r.title, ref=r.username or r.invite_hash or f"id{r.peer_id}",
            link=_source_link(r.username, r.invite_hash), kind=r.kind, status=r.ui_status, account_phone=r.phone,
            found=r.found_count, read=r.read_count, passed=r.passed_count, added_by=r.added_by,
            created_at=r.created_at,
        ) for r in rows]
        return SourcesPage(items, total)

    async def source_counts(self, productive_since: datetime) -> SourceCounts:
        ui = UI_STATUS
        n = lambda *cond: sa.func.count().filter(*cond)  # noqa: E731
        q = sa.select(
            n(ui == "reading"), n(ui == "reading", st.c.kind == "group"), n(ui == "reading", st.c.kind == "channel"),
            n(ui == "awaiting_join"), n(ui == "awaiting_resolve"),
            n(ui == "awaiting_resolve", st.c.added_by == "discovery"), n(ui == "dead"), n(ui == "rejected"),
        )
        productive = (sa.select(sa.func.count(sa.distinct(ct.c.source_id)))
                      .where(ct.c.created_at >= productive_since)
                      .where(ct.c.finding_id.in_(sa.select(ft.c.id).where(ft.c.status.in_(FOUND)))))
        async with self._sf() as s:
            row = (await s.execute(q)).one()
            prod = int((await s.execute(productive)).scalar_one())
        return SourceCounts(*(int(v) for v in row), productive=prod)

    async def channels_by_account(self) -> dict[UUID, int]:
        q = (sa.select(st.c.assigned_account_id, sa.func.count())
             .where(st.c.assigned_account_id.is_not(None), st.c.kind == "channel", st.c.status == "active")
             .group_by(st.c.assigned_account_id))
        async with self._sf() as s:
            return {r[0]: int(r[1]) for r in (await s.execute(q)).all()}
