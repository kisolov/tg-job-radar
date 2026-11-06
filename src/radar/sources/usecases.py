"""Входы в операции с каталогом источников (бот, CLI, воркеры)."""
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from radar.sources.links import normalize_username
from radar.sources.service import AddResult, SourceService

OWNER_PRIORITY = 10
SEED_PRIORITY_HIGH = 10
SEED_PRIORITY = 5


def _owner_refs(text: str) -> list[str]:
    """Из сообщения владельца берутся токены-ссылки: `@name`, `t.me/...`, `telegram.me/...`."""
    refs: list[str] = []
    for token in text.split():
        if token.startswith("@") or "t.me/" in token or "telegram.me/" in token:
            ref = normalize_username(token)
            if ref and ref not in refs:
                refs.append(ref)
    return refs


class AddSource:
    def __init__(self, service: SourceService) -> None:
        self._service = service

    async def execute(self, text: str) -> AddResult:
        return await self._service.add_refs(_owner_refs(text), "owner", OWNER_PRIORITY)


class RemoveSource:
    def __init__(self, service: SourceService) -> None:
        self._service = service

    async def execute(self, link: str) -> bool:
        ref = normalize_username(link)
        return bool(ref) and await self._service.remove(ref)


@dataclass
class SeedResult:
    added: int
    duplicates: int
    invalid: int


class ImportSeeds:
    """Строка: `@name` / `t.me/...` / `name`; префикс `!` — группа фриланса/вакансий (priority 10);
    `#` — комментарий."""

    def __init__(self, service: SourceService) -> None:
        self._service = service

    async def execute(self, path: Path) -> SeedResult:
        added = dups = invalid = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            priority = SEED_PRIORITY_HIGH if line.startswith("!") else SEED_PRIORITY
            ref = normalize_username(line.lstrip("!").split()[0])
            if ref is None:
                invalid += 1
                continue
            res = await self._service.add_refs([ref], "seed", priority)
            added += len(res.added)
            dups += len(res.duplicates)
        return SeedResult(added, dups, invalid)


class AssignWork:
    def __init__(self, service: SourceService) -> None:
        self._service = service

    async def execute(self) -> int:
        return await self._service.assign_work()


class ReleaseAccountSources:
    def __init__(self, service: SourceService) -> None:
        self._service = service

    async def execute(self, account_id: UUID) -> None:
        await self._service.release_account(account_id)
