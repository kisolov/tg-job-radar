from typing import Protocol
from uuid import UUID

from radar.sources.entities import AddedBy, Source, SourceKind, SourceStatus


class SourceRepository(Protocol):
    async def add_candidate(self, ref: str, added_by: AddedBy, priority: int) -> Source | None:
        """ref — результат normalize_username. Дубль (username/invite) → None (R7)."""

    async def get(self, source_id: int) -> Source | None: ...
    async def find(self, ref: str) -> Source | None: ...
    async def next_to_resolve(self, limit: int) -> list[Source]: ...

    async def claim_candidate(self) -> Source | None:
        """Взять кандидата с наибольшим priority и перевести в `resolving` (SKIP LOCKED: не двоим)."""

    async def set_resolved(
        self, source_id: int, peer_id: int | None, access_hash: int | None, kind: SourceKind, title: str
    ) -> bool:
        """→ active. peer_id None — инвайт, id узнаем при вступлении.
        Если peer_id уже есть у другого источника — этот → rejected, False (R7)."""

    async def reset_resolving(self) -> int:
        """После рестарта: зависшие `resolving` → `candidate`."""

    async def set_peer(self, source_id: int, peer_id: int, access_hash: int) -> bool:
        """id чата, узнанный при вступлении по инвайту. Дубль peer_id → rejected, False (R7)."""

    async def set_polled(self, source_id: int, at) -> None: ...
    async def due_for_poll(self, account_id: UUID, before, limit: int) -> list[Source]:
        """Закреплённые за аккаунтом active каналы и вступленные группы, не опрошенные с `before`;
        никогда не опрошенные первыми, затем самые давние."""

    async def mark(self, source_id: int, status: SourceStatus) -> None: ...

    async def assign(self, source_id: int, account_id: UUID) -> bool:
        """Одна транзакция: закрепить, если свободен (R3); для группы +1 к membership_count аккаунта,
        если < cap (R4). Иначе ничего не меняется, False."""

    async def release(self, source_id: int) -> None: ...
    async def release_all_of(self, account_id: UUID) -> None: ...
    async def set_joined(self, source_id: int) -> None: ...
    async def list_assigned(self, account_id: UUID, kind: SourceKind) -> list[Source]: ...
    async def list_unassigned(self, kind: SourceKind, limit: int) -> list[Source]: ...
    async def assigned_counts(self, kind: SourceKind) -> dict[UUID, int]: ...
    async def set_cursor(self, source_id: int, last_message_id: int) -> None:
        """Только вперёд."""
