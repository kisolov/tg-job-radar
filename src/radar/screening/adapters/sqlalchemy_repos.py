from datetime import date

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from radar.screening.ports import COUNTERS, DailyStats, Usage
from radar.screening.requirements_default import DEFAULT_REQUIREMENTS
from radar.shared.db import SessionFactory, transaction
from radar.shared.models import daily_stats as ds
from radar.shared.models import requirements as rq


class SqlAlchemyUsageRepository:
    def __init__(self, sf: SessionFactory) -> None:
        self._sf = sf

    @staticmethod
    async def _ensure_day(s, day: date) -> None:
        await s.execute(insert(ds).values(day=day).on_conflict_do_nothing())

    async def reset_reserved(self) -> int:
        async with transaction(self._sf) as s:
            return (await s.execute(ds.update().where(ds.c.reserved > 0).values(reserved=0))).rowcount

    async def reserve(self, day: date, estimated_tokens: int, limit: int) -> bool:
        async with transaction(self._sf) as s:
            await self._ensure_day(s, day)
            res = await s.execute(
                ds.update()
                .where(ds.c.day == day,
                       ds.c.prompt_tokens + ds.c.completion_tokens + ds.c.reserved + estimated_tokens <= limit)
                .values(reserved=ds.c.reserved + estimated_tokens)
            )
            return res.rowcount == 1

    async def commit_usage(self, day: date, reserved: int, usage: Usage) -> None:
        async with transaction(self._sf) as s:
            await self._ensure_day(s, day)
            await s.execute(ds.update().where(ds.c.day == day).values(
                reserved=sa.func.greatest(0, ds.c.reserved - reserved),
                prompt_tokens=ds.c.prompt_tokens + usage.prompt_tokens,
                completion_tokens=ds.c.completion_tokens + usage.completion_tokens,
                requests=ds.c.requests + 1,
            ))

    async def release(self, day: date, reserved: int) -> None:
        async with transaction(self._sf) as s:
            await s.execute(ds.update().where(ds.c.day == day).values(
                reserved=sa.func.greatest(0, ds.c.reserved - reserved)))

    async def bump(self, day: date, **counters: int) -> None:
        bad = set(counters) - set(COUNTERS)
        if bad:
            raise ValueError(f"Неизвестные счётчики: {bad}")
        if not counters:
            return
        stmt = insert(ds).values(day=day, **counters)
        stmt = stmt.on_conflict_do_update(
            index_elements=[ds.c.day], set_={k: ds.c[k] + stmt.excluded[k] for k in counters})
        async with transaction(self._sf) as s:
            await s.execute(stmt)

    async def get(self, day: date) -> DailyStats:
        async with self._sf() as s:
            r = (await s.execute(sa.select(ds).where(ds.c.day == day))).mappings().first()
        return DailyStats(**r) if r else DailyStats(day)


class SqlAlchemyRequirementsRepository:
    def __init__(self, sf: SessionFactory) -> None:
        self._sf = sf

    async def current(self) -> tuple[int, str]:
        async with self._sf() as s:
            r = (await s.execute(sa.select(rq.c.version, rq.c.text).order_by(rq.c.version.desc()).limit(1))).first()
        if r is None:
            return 0, DEFAULT_REQUIREMENTS
        return r.version, r.text

    async def set(self, text: str) -> int:
        async with transaction(self._sf) as s:
            # Версия = max+1; гонку двух /setreq решает PK (второй получит IntegrityError — команда одна, владелец один).
            nxt = (await s.execute(sa.select(sa.func.coalesce(sa.func.max(rq.c.version), 0) + 1))).scalar()
            await s.execute(rq.insert().values(version=nxt, text=text))
        return nxt

    async def seed_default(self) -> None:
        async with transaction(self._sf) as s:
            await s.execute(insert(rq).values(version=1, text=DEFAULT_REQUIREMENTS).on_conflict_do_nothing())
