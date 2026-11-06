from datetime import datetime
from typing import Protocol

from radar.findings.entities import Classification, Copy, Finding
from radar.ingest.ports import IncomingMessage


class FindingRepository(Protocol):
    async def cluster(self, msg: IncomingMessage, norm: str, fp: str, sh: set[int], window_days: int,
                      threshold: float, now: datetime) -> tuple[Finding, bool]:
        """Одна транзакция под advisory lock: тот же отпечаток → иначе Жаккар ≥ threshold среди кластеров
        за окно → иначе новый. Всегда добавляет копию (дубль (source, message) игнорируется).
        bool — создан новый кластер."""

    async def get(self, finding_id: int) -> Finding | None: ...
    async def pending(self, limit: int) -> list[Finding]: ...
    async def oldest_pending_at(self) -> datetime | None: ...
    async def set_classification(self, finding_id: int, cls: Classification, requirements_version: int) -> bool:
        """pending → accepted|rejected; только из pending."""

    async def accepted(self, limit: int) -> list[Finding]: ...
    async def claim(self, finding_id: int, now: datetime) -> bool:
        """accepted → delivering, только из accepted (R1)."""

    async def mark_delivered(self, finding_id: int, bot_message_id: int, now: datetime) -> None: ...
    async def unclaim(self, finding_id: int) -> None:
        """delivering → accepted."""

    async def stale_claims(self, claimed_before: datetime) -> list[Finding]: ...
    async def copies(self, finding_id: int) -> list[Copy]: ...
