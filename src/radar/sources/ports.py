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
        self, source_id: int, peer_id: int | None, access_hash: int | None, kind: SourceKind, title: str,
        at=None,
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
    async def bump_counts(self, source_id: int, read: int, passed: int) -> None:
        """Счётчики прочитанных и прошедших предфильтр сообщений источника."""

    async def useless(self, activated_before, min_read: int) -> list[Source]:
        """Вступленные active-группы старше окна: ни одной находки, ни одного прошедшего предфильтр, прочитано ≥ min_read."""

    async def eviction_candidate(self, activated_before) -> Source | None:
        """Вступленная active-группа старше окна без находок (наименее полезная) — кандидат на вытеснение."""

    async def list_to_leave(self, account_id: UUID) -> list[Source]:
        """Вступленные группы аккаунта, которые сняты с чтения (rejected/dead): воркер выходит и освобождает слот."""

    async def add_found(self, source_id: int, n: int = 1) -> None:
        """+n к числу находок источника (статистика /sources, отсев бесполезных)."""

    async def count_by_status(self) -> dict[SourceStatus, int]: ...
    async def top(self, limit: int, offset: int) -> list[Source]:
        """active-источники по убыванию found_count."""

    async def set_cursor(self, source_id: int, last_message_id: int) -> None:
        """Только вперёд."""
