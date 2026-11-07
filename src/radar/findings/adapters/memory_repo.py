import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta

from radar.findings.entities import Classification, Copy, Finding, FindingStatus
from radar.findings.similarity import jaccard, pack, sketch, unpack
from radar.ingest.ports import IncomingMessage


class InMemoryFindingRepository:
    """Фейк: кластеризация под asyncio.Lock (аналог advisory lock), отдаёт копии."""

    def __init__(self) -> None:
        self.rows: dict[int, Finding] = {}
        self.copy_rows: list[Copy] = []
        self._lock = asyncio.Lock()
        self._next = 1

    def _candidates(self, sh, since, threshold) -> list[Finding]:
        n, mine = len(sh), set(sketch(sh))
        out = []
        for f in sorted(self.rows.values(), key=lambda f: f.id):
            other = unpack(f.shingles)
            if (f.created_at >= since and int(n * threshold) <= len(other) <= int(n / threshold) + 1
                    and mine & set(sketch(other))):
                out.append(f)
        return out

    async def dedup_candidates(self, sh, since, threshold) -> list[int]:
        return [f.id for f in self._candidates(sh, since, threshold)] if sh else []

    async def cluster(self, msg: IncomingMessage, norm, fp, sh, window_days, threshold, now):
        async with self._lock:
            since = now - timedelta(days=window_days)
            recent = [f for f in self.rows.values() if f.created_at >= since]
            found = next((f for f in recent if f.fingerprint == fp), None)
            if found is None:
                found = next((f for f in self._candidates(sh, since, threshold)
                              if jaccard(sh, unpack(f.shingles)) >= threshold), None) if sh else None
            new = found is None
            if new:
                found = Finding(
                    id=self._next, fingerprint=fp, shingles=pack(sh), text_snapshot=msg.text,
                    link_snapshot=msg.link, sender_username=msg.sender_username, sender_id=msg.sender_id,
                    sender_is_user=msg.sender_is_user, status=FindingStatus.pending, classification=None,
                    requirements_version=None, claimed_at=None, delivered_at=None, bot_message_id=None,
                    created_at=now,
                )
                self._next += 1
                self.rows[found.id] = found
            if not any((c.source_id, c.message_id) == (msg.source_id, msg.message_id) for c in self.copy_rows):
                self.copy_rows.append(Copy(found.id, msg.source_id, msg.message_id, msg.link, msg.source_title))
            return deepcopy(found), new

    async def get(self, finding_id: int) -> Finding | None:
        f = self.rows.get(finding_id)
        return deepcopy(f) if f else None

    def _by_status(self, status: FindingStatus, limit: int) -> list[Finding]:
        rows = sorted((f for f in self.rows.values() if f.status is status), key=lambda f: (f.created_at, f.id))
        return deepcopy(rows[:limit])

    async def pending(self, limit: int) -> list[Finding]:
        rows = sorted((f for f in self.rows.values() if f.status is FindingStatus.pending),
                      key=lambda f: (f.llm_attempts, f.created_at, f.id))
        return deepcopy(rows[:limit])

    async def record_llm_failure(self, finding_ids: list[int], max_attempts: int) -> list[int]:
        failed = []
        for fid in finding_ids:
            f = self.rows.get(fid)
            if f is None or f.status is not FindingStatus.pending:
                continue
            f.llm_attempts += 1
            if f.llm_attempts >= max_attempts:
                f.status = FindingStatus.failed
                failed.append(fid)
        return sorted(failed)

    async def oldest_pending_at(self) -> datetime | None:
        p = self._by_status(FindingStatus.pending, 1)
        return p[0].created_at if p else None

    async def set_classification(self, finding_id: int, cls: Classification, requirements_version: int) -> bool:
        f = self.rows[finding_id]
        if f.status is not FindingStatus.pending:
            return False
        f.status = FindingStatus.accepted if cls.relevant else FindingStatus.rejected
        f.classification, f.requirements_version = cls, requirements_version
        return True

    async def accepted(self, limit: int) -> list[Finding]:
        return self._by_status(FindingStatus.accepted, limit)

    async def claim(self, finding_id: int, now: datetime) -> bool:
        f = self.rows[finding_id]
        if f.status is not FindingStatus.accepted:
            return False
        f.status, f.claimed_at = FindingStatus.delivering, now
        return True

    async def mark_delivered(self, finding_id: int, bot_message_id: int, now: datetime) -> None:
        f = self.rows[finding_id]
        f.status, f.bot_message_id, f.delivered_at = FindingStatus.delivered, bot_message_id, now

    async def fail_delivery(self, finding_id: int) -> bool:
        f = self.rows[finding_id]
        if f.status is not FindingStatus.delivering:
            return False
        f.status = FindingStatus.failed
        return True

    async def unclaim(self, finding_id: int) -> None:
        f = self.rows[finding_id]
        if f.status is FindingStatus.delivering:
            f.status, f.claimed_at = FindingStatus.accepted, None

    async def stale_claims(self, claimed_before: datetime) -> list[Finding]:
        return deepcopy([f for f in self.rows.values()
                         if f.status is FindingStatus.delivering and f.claimed_at and f.claimed_at < claimed_before])

    async def copies(self, finding_id: int) -> list[Copy]:
        return [replace(c) for c in self.copy_rows if c.finding_id == finding_id]
