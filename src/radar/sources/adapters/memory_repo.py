from collections import Counter
from copy import deepcopy
from uuid import UUID

from radar.accounts.adapters.memory_repo import InMemoryAccountRepository
from radar.sources.entities import AddedBy, Source, SourceKind, SourceStatus


class InMemorySourceRepository:
    """Фейк: методы без await внутри — каждый атомарен для корутин, как транзакция в SQL."""

    def __init__(self, accounts: InMemoryAccountRepository, membership_cap: int) -> None:
        self._accounts = accounts
        self._cap = membership_cap
        self.rows: dict[int, Source] = {}
        self._next_id = 1

    async def add_candidate(self, ref: str, added_by: AddedBy, priority: int) -> Source | None:
        if self._by_ref(ref):
            return None
        invite = ref.startswith("+")
        s = Source(
            id=self._next_id, username=None if invite else ref, invite_hash=ref if invite else None,
            peer_id=None, access_hash=None, kind=None, title=None, status=SourceStatus.candidate,
            assigned_account_id=None, joined=False, last_message_id=0, found_count=0, relay_score=0.0,
            added_by=added_by, priority=priority,
        )
        self._next_id += 1
        self.rows[s.id] = s
        return deepcopy(s)

    def _by_ref(self, ref: str) -> Source | None:
        return next((s for s in self.rows.values() if ref in (s.username, s.invite_hash)), None)

    async def get(self, source_id: int) -> Source | None:
        s = self.rows.get(source_id)
        return deepcopy(s) if s else None

    async def find(self, ref: str) -> Source | None:
        s = self._by_ref(ref)
        return deepcopy(s) if s else None

    async def next_to_resolve(self, limit: int) -> list[Source]:
        c = [s for s in self.rows.values() if s.status is SourceStatus.candidate]
        c.sort(key=lambda s: (-s.priority, s.id))
        return deepcopy(c[:limit])

    async def set_resolved(self, source_id, peer_id, access_hash, kind, title) -> bool:
        s = self.rows[source_id]
        if any(o.peer_id == peer_id and o.id != source_id for o in self.rows.values()):
            s.status = SourceStatus.rejected
            s.version += 1
            return False
        s.peer_id, s.access_hash, s.kind, s.title = peer_id, access_hash, kind, title
        s.status = SourceStatus.active
        s.version += 1
        return True

    async def mark(self, source_id: int, status: SourceStatus) -> None:
        s = self.rows[source_id]
        s.status = status
        s.version += 1

    async def assign(self, source_id: int, account_id: UUID) -> bool:
        s = self.rows[source_id]
        if s.assigned_account_id is not None:
            return False
        if s.kind is SourceKind.group:
            acc = self._accounts.rows[account_id]
            if acc.membership_count >= self._cap:
                return False
            acc.membership_count += 1
            acc.version += 1
        s.assigned_account_id = account_id
        s.version += 1
        return True

    def _unassign(self, s: Source) -> bool:
        was_group = s.assigned_account_id is not None and s.kind is SourceKind.group
        s.assigned_account_id, s.joined = None, False
        s.version += 1
        return was_group

    async def release(self, source_id: int) -> None:
        s = self.rows[source_id]
        if s.assigned_account_id is None:
            return
        account_id = s.assigned_account_id
        if self._unassign(s):
            acc = self._accounts.rows[account_id]
            acc.membership_count = max(0, acc.membership_count - 1)
            acc.version += 1

    async def release_all_of(self, account_id: UUID) -> None:
        groups = sum(self._unassign(s) for s in self.rows.values() if s.assigned_account_id == account_id)
        acc = self._accounts.rows.get(account_id)
        if acc and groups:
            acc.membership_count = max(0, acc.membership_count - groups)
            acc.version += 1

    async def set_joined(self, source_id: int) -> None:
        self.rows[source_id].joined = True

    async def list_assigned(self, account_id: UUID, kind: SourceKind) -> list[Source]:
        return deepcopy([s for s in self.rows.values() if s.assigned_account_id == account_id and s.kind is kind])

    async def list_unassigned(self, kind: SourceKind, limit: int) -> list[Source]:
        free = [s for s in self.rows.values()
                if s.status is SourceStatus.active and s.kind is kind and s.assigned_account_id is None]
        free.sort(key=lambda s: (-s.priority, s.id))
        return deepcopy(free[:limit])

    async def assigned_counts(self, kind: SourceKind) -> dict[UUID, int]:
        return dict(Counter(s.assigned_account_id for s in self.rows.values()
                            if s.kind is kind and s.assigned_account_id is not None))

    async def set_cursor(self, source_id: int, last_message_id: int) -> None:
        s = self.rows[source_id]
        s.last_message_id = max(s.last_message_id, last_message_id)
