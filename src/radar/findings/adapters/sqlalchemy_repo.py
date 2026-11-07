from dataclasses import asdict
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, insert

from radar.findings.entities import Classification, Copy, Finding, FindingStatus
from radar.findings.similarity import jaccard, pack, sketch, unpack
from radar.ingest.ports import IncomingMessage
from radar.shared.db import SessionFactory, transaction
from radar.shared.models import finding_copies as ct
from radar.shared.models import findings as t

# Ключ advisory lock дедупа: весь поиск/создание кластера сериализован (гонка 1 из спека).
DEDUP_LOCK = sa.func.hashtext("findings-dedup")


def _row(r) -> Finding:
    return Finding(
        id=r.id, fingerprint=r.fingerprint, shingles=bytes(r.shingles), text_snapshot=r.text_snapshot,
        link_snapshot=r.link_snapshot, sender_username=r.sender_username, sender_id=r.sender_id,
        sender_is_user=r.sender_is_user, status=FindingStatus(r.status),
        classification=Classification(**r.classification) if r.classification else None,
        requirements_version=r.requirements_version, claimed_at=r.claimed_at, delivered_at=r.delivered_at,
        bot_message_id=r.bot_message_id, created_at=r.created_at, llm_attempts=r.llm_attempts,
    )


class SqlAlchemyFindingRepository:
    def __init__(self, sf: SessionFactory) -> None:
        self._sf = sf

    @staticmethod
    def _candidates_q(sh, since, threshold):
        n = len(sh)
        # Жаккар ≥ t возможен только при min(|A|,|B|)/max(|A|,|B|) ≥ t — отсекаем по размеру;
        # и почти наверняка при пересечении bottom-k скетчей — отсекаем по GIN-индексу (M9).
        return sa.select(t.c.id, t.c.shingles).where(
            t.c.created_at >= since,
            t.c.shingle_count >= int(n * threshold),
            t.c.shingle_count <= int(n / threshold) + 1,
            t.c.sketch.overlap(sa.cast(sketch(sh), ARRAY(sa.BigInteger))),
        ).order_by(t.c.id)

    async def dedup_candidates(self, sh, since, threshold) -> list[int]:
        if not sh:
            return []
        async with self._sf() as s:
            return [r.id for r in (await s.execute(self._candidates_q(sh, since, threshold))).all()]

    async def cluster(self, msg: IncomingMessage, norm, fp, sh, window_days, threshold, now):
        since = now - timedelta(days=window_days)
        n = len(sh)
        async with transaction(self._sf) as s:
            await s.execute(sa.select(sa.func.pg_advisory_xact_lock(DEDUP_LOCK)))
            row = (await s.execute(
                sa.select(t).where(t.c.fingerprint == fp, t.c.created_at >= since).order_by(t.c.id).limit(1)
            )).first()
            if row is None and n:
                candidates = (await s.execute(self._candidates_q(sh, since, threshold))).all()
                best = next((c.id for c in candidates if jaccard(sh, unpack(bytes(c.shingles))) >= threshold), None)
                if best is not None:
                    row = (await s.execute(sa.select(t).where(t.c.id == best))).first()
            new = row is None
            if new:
                row = (await s.execute(t.insert().values(
                    fingerprint=fp, shingles=pack(sh), shingle_count=n, sketch=sketch(sh), text_snapshot=msg.text,
                    link_snapshot=msg.link, sender_username=msg.sender_username, sender_id=msg.sender_id,
                    sender_is_user=msg.sender_is_user, status=FindingStatus.pending.value, created_at=now,
                ).returning(*t.c))).first()
            await s.execute(insert(ct).values(
                finding_id=row.id, source_id=msg.source_id, message_id=msg.message_id, link=msg.link,
                source_title=msg.source_title,
            ).on_conflict_do_nothing())
        return _row(row), new

    async def _select(self, *where, order=(), limit=None) -> list[Finding]:
        q = sa.select(t).where(*where).order_by(*order)
        if limit is not None:
            q = q.limit(limit)
        async with self._sf() as s:
            return [_row(r) for r in (await s.execute(q)).all()]

    async def get(self, finding_id: int) -> Finding | None:
        rows = await self._select(t.c.id == finding_id)
        return rows[0] if rows else None

    async def pending(self, limit: int) -> list[Finding]:
        # неудачные у LLM — в конец очереди: не держат пакет (I4)
        return await self._select(t.c.status == FindingStatus.pending.value,
                                  order=(t.c.llm_attempts, t.c.created_at, t.c.id), limit=limit)

    async def record_llm_failure(self, finding_ids: list[int], max_attempts: int) -> list[int]:
        if not finding_ids:
            return []
        pending = (t.c.id.in_(finding_ids), t.c.status == FindingStatus.pending.value)
        async with transaction(self._sf) as s:
            await s.execute(t.update().where(*pending).values(llm_attempts=t.c.llm_attempts + 1))
            failed = (await s.execute(
                t.update().where(*pending, t.c.llm_attempts >= max_attempts)
                .values(status=FindingStatus.failed.value).returning(t.c.id))).scalars().all()
        return sorted(failed)

    async def oldest_pending_at(self) -> datetime | None:
        async with self._sf() as s:
            return (await s.execute(sa.select(sa.func.min(t.c.created_at))
                                    .where(t.c.status == FindingStatus.pending.value))).scalar()

    async def _update(self, finding_id: int, expect: FindingStatus, **values) -> bool:
        async with transaction(self._sf) as s:
            res = await s.execute(t.update().where(t.c.id == finding_id, t.c.status == expect.value).values(**values))
        return res.rowcount == 1

    async def set_classification(self, finding_id: int, cls: Classification, requirements_version: int) -> bool:
        status = FindingStatus.accepted if cls.relevant else FindingStatus.rejected
        return await self._update(finding_id, FindingStatus.pending, status=status.value,
                                  classification=asdict(cls), requirements_version=requirements_version)

    async def accepted(self, limit: int) -> list[Finding]:
        return await self._select(t.c.status == FindingStatus.accepted.value, order=(t.c.created_at, t.c.id),
                                  limit=limit)

    async def claim(self, finding_id: int, now: datetime) -> bool:
        return await self._update(finding_id, FindingStatus.accepted,
                                  status=FindingStatus.delivering.value, claimed_at=now)

    async def mark_delivered(self, finding_id: int, bot_message_id: int, now: datetime) -> None:
        await self._update(finding_id, FindingStatus.delivering, status=FindingStatus.delivered.value,
                           bot_message_id=bot_message_id, delivered_at=now)

    async def fail_delivery(self, finding_id: int) -> bool:
        return await self._update(finding_id, FindingStatus.delivering, status=FindingStatus.failed.value)

    async def unclaim(self, finding_id: int) -> None:
        await self._update(finding_id, FindingStatus.delivering, status=FindingStatus.accepted.value, claimed_at=None)

    async def stale_claims(self, claimed_before: datetime) -> list[Finding]:
        return await self._select(t.c.status == FindingStatus.delivering.value, t.c.claimed_at < claimed_before,
                                  order=(t.c.id,))

    async def copies(self, finding_id: int) -> list[Copy]:
        async with self._sf() as s:
            rows = (await s.execute(sa.select(ct).where(ct.c.finding_id == finding_id)
                                    .order_by(ct.c.created_at, ct.c.source_id))).all()
        return [Copy(r.finding_id, r.source_id, r.message_id, r.link, r.source_title) for r in rows]
