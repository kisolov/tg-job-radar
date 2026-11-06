"""Какие чаты читаем и кто их читает: закрепление, пополнение каталога, отсев бесполезных."""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from radar.accounts.ports import AccountRepository
from radar.screening.prefilter import is_aggregator_only, is_russian
from radar.shared.settings import DEFAULT_AGGREGATORS
from radar.sources.entities import AddedBy, SourceKind, SourceStatus
from radar.sources.ports import SourceRepository

ASSIGN_BATCH = 1000
USEFULNESS_WINDOW = timedelta(days=14)
USELESS_MIN_READ = 100
RELAY_MIN_SAMPLE = 20
RELAY_SHARE = 0.5
TOPIC_WORDS = [
    "работа", "ваканс", "фриланс", "заказ", "удален", "it", "айти", "разработ", "программ", "python", "питон",
    "frontend", "фронтенд", "веб", "web", "digital", "junior", "middle", "senior",
    # расширение под стек владельца: чаты по технологиям, где публикуют задачи
    "backend", "бэкенд", "django", "fastapi", "vue", "react", "javascript", "devops", "jobs", "job", "remote",
    "freelance", "hire", "hiring",
]
_TOPIC = re.compile("|".join(rf"(?<!\w){re.escape(w)}" + (r"(?!\w)" if len(w) <= 3 else "") for w in TOPIC_WORDS))


@dataclass
class AddResult:
    added: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)


class SourceService:
    def __init__(self, sources: SourceRepository, accounts: AccountRepository,
                 aggregator_domains: list[str] | None = None) -> None:
        self._sources = sources
        self._accounts = accounts
        self._aggregators = aggregator_domains or DEFAULT_AGGREGATORS

    async def add_refs(self, refs: list[str], added_by: AddedBy, priority: int) -> AddResult:
        res = AddResult()
        for ref in refs:
            (res.added if await self._sources.add_candidate(ref, added_by, priority) else res.duplicates).append(ref)
        return res

    def vet(self, title: str, about: str, sample: list[str]) -> SourceStatus:
        """Кандидат из автопополнения: русскоязычный, по теме, не ретранслятор агрегатора."""
        head = f"{title} {about}".lower().replace("ё", "е")
        texts = [t for t in sample if t and t.strip()]
        russian = is_russian(head) or (bool(texts) and sum(map(is_russian, texts)) / len(texts) >= 0.5)
        if not russian or not _TOPIC.search(head):
            return SourceStatus.rejected
        if len(texts) >= RELAY_MIN_SAMPLE:
            relay = sum(is_aggregator_only(t, self._aggregators) for t in texts) / len(texts)
            if relay >= RELAY_SHARE:
                return SourceStatus.rejected
        return SourceStatus.active

    async def retire(self, source_id: int) -> None:
        """Снять с чтения. Вступленную группу освобождает воркер аккаунта после выхода (list_to_leave),
        иначе Telegram продолжит считать её в лимите членства."""
        source = await self._sources.get(source_id)
        if source is None:
            return
        if not source.joined:
            await self._sources.release(source_id)
        await self._sources.mark(source_id, SourceStatus.rejected)

    async def retire_useless(self, now: datetime) -> int:
        useless = await self._sources.useless(now - USEFULNESS_WINDOW, USELESS_MIN_READ)
        for s in useless:
            await self.retire(s.id)
        return len(useless)

    async def assign_work(self, now: datetime | None = None) -> int:
        """Раздать свободные active-источники active-аккаунтам: каждому — наименее загруженный аккаунт.

        Нагрузка по группам — membership_count (R4), по каналам — число закреплённых каналов. Если все аккаунты
        упёрлись в лимит членства, а группа ждёт, — одна вступленная группа без находок за 14 суток снимается.
        """
        active = await self._accounts.list_active()
        if not active:
            return 0
        assigned = 0
        all_full = False
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
                if not load:
                    all_full = kind is SourceKind.group
                    break
        if all_full and now is not None:
            victim = await self._sources.eviction_candidate(now - USEFULNESS_WINDOW)
            if victim is not None:
                await self.retire(victim.id)
        return assigned

    async def remove(self, ref: str) -> bool:
        source = await self._sources.find(ref)
        if source is None:
            return False
        await self.retire(source.id)
        return True

    async def release_account(self, account_id: UUID) -> None:
        await self._sources.release_all_of(account_id)
