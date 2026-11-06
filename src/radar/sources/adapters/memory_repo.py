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

    async def claim_candidate(self) -> Source | None:
        c = [s for s in self.rows.values() if s.status is SourceStatus.candidate]
        if not c:
            return None
        s = min(c, key=lambda s: (-s.priority, s.id))
        s.status = SourceStatus.resolving
        s.version += 1
        return deepcopy(s)

    async def reset_resolving(self) -> int:
        stuck = [s for s in self.rows.values() if s.status is SourceStatus.resolving]
        for s in stuck:
            s.status = SourceStatus.candidate
            s.version += 1
        return len(stuck)

    def _peer_taken(self, source_id: int, peer_id: int | None) -> bool:
        return peer_id is not None and any(o.peer_id == peer_id and o.id != source_id for o in self.rows.values())

    def _reject(self, s: Source) -> None:
        s.status = SourceStatus.rejected
        s.version += 1

    async def set_resolved(self, source_id, peer_id, access_hash, kind, title, at=None) -> bool:
        s = self.rows[source_id]
        if self._peer_taken(source_id, peer_id):
            self._reject(s)
            return False
        s.peer_id, s.access_hash, s.kind, s.title = peer_id, access_hash, kind, title
        s.status = SourceStatus.active
        s.activated_at = at
        s.version += 1
        return True

    async def set_peer(self, source_id: int, peer_id: int, access_hash: int) -> bool:
        s = self.rows[source_id]
        if self._peer_taken(source_id, peer_id):
            self._reject(s)
            return False
        s.peer_id, s.access_hash = peer_id, access_hash
        s.version += 1
        return True

    async def set_polled(self, source_id: int, at) -> None:
        self.rows[source_id].last_polled_at = at

    async def due_for_poll(self, account_id: UUID, before, limit: int) -> list[Source]:
        due = [
            s for s in self.rows.values()
            if s.assigned_account_id == account_id and s.status is SourceStatus.active
            and (s.kind is SourceKind.channel or s.joined)
            and (s.last_polled_at is None or s.last_polled_at <= before)
        ]
        due.sort(key=lambda s: (s.last_polled_at is not None, s.last_polled_at or 0, s.id))
        return deepcopy(due[:limit])

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

    async def bump_counts(self, source_id: int, read: int, passed: int) -> None:
        if s := self.rows.get(source_id):
            s.read_count += read
            s.passed_count += passed

    def _joined_active_groups(self, activated_before):
        return [s for s in self.rows.values()
                if s.status is SourceStatus.active and s.kind is SourceKind.group and s.joined
                and s.assigned_account_id is not None and s.activated_at is not None
                and s.activated_at < activated_before]

    async def useless(self, activated_before, min_read: int) -> list[Source]:
        return deepcopy([s for s in self._joined_active_groups(activated_before)
                         if s.found_count == 0 and s.passed_count == 0 and s.read_count >= min_read])

    async def eviction_candidate(self, activated_before) -> Source | None:
        c = [s for s in self._joined_active_groups(activated_before) if s.found_count == 0]
        c.sort(key=lambda s: (s.passed_count, -s.read_count, s.id))
        return deepcopy(c[0]) if c else None

    async def list_to_leave(self, account_id: UUID) -> list[Source]:
        return deepcopy([s for s in self.rows.values() if s.assigned_account_id == account_id and s.joined
                         and s.status in (SourceStatus.rejected, SourceStatus.dead)])

    async def add_found(self, source_id: int, n: int = 1) -> None:
        if s := self.rows.get(source_id):
            s.found_count += n

    async def count_by_status(self) -> dict[SourceStatus, int]:
        return dict(Counter(s.status for s in self.rows.values()))

    async def top(self, limit: int, offset: int) -> list[Source]:
        rows = sorted((s for s in self.rows.values() if s.status is SourceStatus.active),
                      key=lambda s: (-s.found_count, s.id))
        return deepcopy(rows[offset:offset + limit])

    async def set_cursor(self, source_id: int, last_message_id: int) -> None:
        if s := self.rows.get(source_id):  # как UPDATE в SQL: нет строки — нет изменений
            s.last_message_id = max(s.last_message_id, last_message_id)
