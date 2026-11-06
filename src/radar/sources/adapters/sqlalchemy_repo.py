from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from radar.shared.db import SessionFactory, transaction
from radar.shared.models import accounts as at
from radar.shared.models import sources as t
from radar.sources.entities import AddedBy, Source, SourceKind, SourceStatus


class _Rollback(Exception):
    pass


def _row(r) -> Source:
    return Source(
        id=r.id, username=r.username, invite_hash=r.invite_hash, peer_id=r.peer_id,
        access_hash=r.access_hash, kind=SourceKind(r.kind) if r.kind else None, title=r.title,
        status=SourceStatus(r.status), assigned_account_id=r.assigned_account_id, joined=r.joined,
        last_message_id=r.last_message_id, found_count=r.found_count, relay_score=r.relay_score,
        added_by=r.added_by, priority=r.priority, version=r.version, last_polled_at=r.last_polled_at,
    )


class SqlAlchemySourceRepository:
    def __init__(self, sf: SessionFactory, membership_cap: int) -> None:
        self._sf = sf
        self._cap = membership_cap

    async def add_candidate(self, ref: str, added_by: AddedBy, priority: int) -> Source | None:
        invite = ref.startswith("+")
        stmt = (
            insert(t)
            .values(username=None if invite else ref, invite_hash=ref if invite else None,
                    status=SourceStatus.candidate.value, added_by=added_by, priority=priority)
            .on_conflict_do_nothing()
            .returning(*t.c)
        )
        async with transaction(self._sf) as s:
            r = (await s.execute(stmt)).first()
        return _row(r) if r else None

    async def _select(self, *where, order=(), limit: int | None = None) -> list[Source]:
        q = sa.select(t).where(*where).order_by(*order)
        if limit is not None:
            q = q.limit(limit)
        async with self._sf() as s:
            return [_row(r) for r in (await s.execute(q)).all()]

    async def get(self, source_id: int) -> Source | None:
        rows = await self._select(t.c.id == source_id)
        return rows[0] if rows else None

    async def find(self, ref: str) -> Source | None:
        rows = await self._select(sa.or_(t.c.username == ref, t.c.invite_hash == ref))
        return rows[0] if rows else None

    async def next_to_resolve(self, limit: int) -> list[Source]:
        return await self._select(t.c.status == SourceStatus.candidate.value,
                                  order=(t.c.priority.desc(), t.c.id), limit=limit)

    async def set_resolved(self, source_id, peer_id, access_hash, kind, title) -> bool:
        try:
            async with transaction(self._sf) as s:
                await s.execute(t.update().where(t.c.id == source_id).values(
                    peer_id=peer_id, access_hash=access_hash, kind=kind.value, title=title,
                    status=SourceStatus.active.value, version=t.c.version + 1, updated_at=sa.func.now(),
                ))
            return True
        except IntegrityError:
            await self.mark(source_id, SourceStatus.rejected)
            return False

    async def mark(self, source_id: int, status: SourceStatus) -> None:
        async with transaction(self._sf) as s:
            await s.execute(t.update().where(t.c.id == source_id).values(
                status=status.value, version=t.c.version + 1, updated_at=sa.func.now()))

    async def assign(self, source_id: int, account_id: UUID) -> bool:
        try:
            async with transaction(self._sf) as s:
                kind = (await s.execute(
                    t.update()
                    .where(t.c.id == source_id, t.c.assigned_account_id.is_(None))
                    .values(assigned_account_id=account_id, version=t.c.version + 1, updated_at=sa.func.now())
                    .returning(t.c.kind)
                )).scalar()
                if kind is None:
                    raise _Rollback
                if kind == SourceKind.group.value:
                    res = await s.execute(
                        at.update()
                        .where(at.c.id == account_id, at.c.membership_count < self._cap)
                        .values(membership_count=at.c.membership_count + 1, version=at.c.version + 1)
                    )
                    if res.rowcount != 1:
                        raise _Rollback
        except _Rollback:
            return False
        return True

    async def _decrement(self, s, account_id: UUID, n: int) -> None:
        if n:
            await s.execute(at.update().where(at.c.id == account_id).values(
                membership_count=sa.func.greatest(0, at.c.membership_count - n), version=at.c.version + 1))

    async def release(self, source_id: int) -> None:
        async with transaction(self._sf) as s:
            old = (await s.execute(
                sa.select(t.c.assigned_account_id, t.c.kind)
                .where(t.c.id == source_id, t.c.assigned_account_id.is_not(None)).with_for_update()
            )).first()
            if old is None:
                return
            await s.execute(t.update().where(t.c.id == source_id).values(
                assigned_account_id=None, joined=False, version=t.c.version + 1, updated_at=sa.func.now()))
            await self._decrement(s, old.assigned_account_id, int(old.kind == SourceKind.group.value))

    async def release_all_of(self, account_id: UUID) -> None:
        async with transaction(self._sf) as s:
            kinds = (await s.execute(
                t.update().where(t.c.assigned_account_id == account_id)
                .values(assigned_account_id=None, joined=False, version=t.c.version + 1, updated_at=sa.func.now())
                .returning(t.c.kind)
            )).scalars().all()
            await self._decrement(s, account_id, sum(k == SourceKind.group.value for k in kinds))

    async def set_joined(self, source_id: int) -> None:
        async with transaction(self._sf) as s:
            await s.execute(t.update().where(t.c.id == source_id).values(joined=True, updated_at=sa.func.now()))

    async def list_assigned(self, account_id: UUID, kind: SourceKind) -> list[Source]:
        return await self._select(t.c.assigned_account_id == account_id, t.c.kind == kind.value, order=(t.c.id,))

    async def list_unassigned(self, kind: SourceKind, limit: int) -> list[Source]:
        return await self._select(
            t.c.status == SourceStatus.active.value, t.c.kind == kind.value, t.c.assigned_account_id.is_(None),
            order=(t.c.priority.desc(), t.c.id), limit=limit,
        )

    async def assigned_counts(self, kind: SourceKind) -> dict[UUID, int]:
        q = (sa.select(t.c.assigned_account_id, sa.func.count())
             .where(t.c.kind == kind.value, t.c.assigned_account_id.is_not(None))
             .group_by(t.c.assigned_account_id))
        async with self._sf() as s:
            return {a: n for a, n in (await s.execute(q)).all()}

    async def set_cursor(self, source_id: int, last_message_id: int) -> None:
        async with transaction(self._sf) as s:
            await s.execute(t.update().where(t.c.id == source_id, t.c.last_message_id < last_message_id)
                            .values(last_message_id=last_message_id))
