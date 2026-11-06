"""Какие чаты читаем и кто их читает: закрепление, пополнение каталога."""
from dataclasses import dataclass, field
from uuid import UUID

from radar.accounts.ports import AccountRepository
from radar.sources.entities import AddedBy, SourceKind, SourceStatus
from radar.sources.ports import SourceRepository

ASSIGN_BATCH = 1000


@dataclass
class AddResult:
    added: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)


class SourceService:
    def __init__(self, sources: SourceRepository, accounts: AccountRepository) -> None:
        self._sources = sources
        self._accounts = accounts

    async def add_refs(self, refs: list[str], added_by: AddedBy, priority: int) -> AddResult:
        res = AddResult()
        for ref in refs:
            (res.added if await self._sources.add_candidate(ref, added_by, priority) else res.duplicates).append(ref)
        return res

    async def assign_work(self) -> int:
        """Раздать свободные active-источники active-аккаунтам: каждому — наименее загруженный аккаунт.

        Нагрузка по группам — membership_count (R4), по каналам — число закреплённых каналов.
        """
        active = await self._accounts.list_active()
        if not active:
            return 0
        assigned = 0
        for kind in (SourceKind.group, SourceKind.channel):
            if kind is SourceKind.group:
                load = {a.id: a.membership_count for a in active}
            else:
                counts = await self._sources.assigned_counts(kind)
                load = {a.id: counts.get(a.id, 0) for a in active}
            for source in await self._sources.list_unassigned(kind, ASSIGN_BATCH):
                while load:
                    account_id = min(load, key=lambda k: load[k])
                    if await self._sources.assign(source.id, account_id):
                        load[account_id] += 1
                        assigned += 1
                        break
                    current = await self._sources.get(source.id)
                    if current is None or current.assigned_account_id is not None:
                        break  # источник забрал кто-то другой
                    load.pop(account_id)  # аккаунт упёрся в лимит членства
        return assigned

    async def remove(self, ref: str) -> bool:
        source = await self._sources.find(ref)
        if source is None:
            return False
        await self._sources.release(source.id)
        await self._sources.mark(source.id, SourceStatus.rejected)
        return True

    async def release_account(self, account_id: UUID) -> None:
        await self._sources.release_all_of(account_id)
