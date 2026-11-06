"""Настройки, меняемые на ходу (/set, /pause): перекрывают env, хранятся в settings_overrides.

Снимок держится в памяти процесса и обновляется при set() — допущение одной реплики (см. спек).
"""
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from radar.shared.db import SessionFactory, transaction
from radar.shared.models import settings_overrides as t
from radar.shared.settings import Settings

EDITABLE: dict[str, type] = {
    "LLM_BATCH_SIZE": int,
    "LLM_BATCH_WAIT_S": int,
    "LLM_MAX_CHARS": int,
    "LLM_DAILY_TOKEN_LIMIT": int,
    "NEUROAPI_MODEL": str,
    "PREFILTER_MIN_LEN": int,
}
PAUSED_KEY = "DELIVERY_PAUSED"


class UnknownSetting(KeyError):
    pass


class OverridesStore(Protocol):
    async def all(self) -> dict[str, str]: ...
    async def set(self, key: str, value: str) -> None: ...
    async def delete(self, key: str) -> None: ...


class InMemoryOverridesStore:
    def __init__(self) -> None:
        self.rows: dict[str, str] = {}

    async def all(self) -> dict[str, str]:
        return dict(self.rows)

    async def set(self, key: str, value: str) -> None:
        self.rows[key] = value

    async def delete(self, key: str) -> None:
        self.rows.pop(key, None)


class SqlAlchemyOverridesStore:
    def __init__(self, sf: SessionFactory) -> None:
        self._sf = sf

    async def all(self) -> dict[str, str]:
        async with self._sf() as s:
            return {k: v for k, v in (await s.execute(sa.select(t.c.key, t.c.value))).all()}

    async def set(self, key: str, value: str) -> None:
        stmt = insert(t).values(key=key, value=value)
        async with transaction(self._sf) as s:
            await s.execute(stmt.on_conflict_do_update(index_elements=[t.c.key], set_={"value": stmt.excluded.value}))

    async def delete(self, key: str) -> None:
        async with transaction(self._sf) as s:
            await s.execute(t.delete().where(t.c.key == key))


class RuntimeConfig:
    def __init__(self, settings: Settings, store: OverridesStore) -> None:
        self.settings = settings
        self._store = store
        self._overrides: dict[str, str] = {}

    async def load(self) -> None:
        self._overrides = await self._store.all()

    def get(self, key: str):
        if key not in EDITABLE:
            return getattr(self.settings, key)
        raw = self._overrides.get(key)
        return EDITABLE[key](raw) if raw is not None else getattr(self.settings, key)

    async def set(self, key: str, raw: str) -> object:
        if key not in EDITABLE:
            raise UnknownSetting(key)
        typ = EDITABLE[key]
        try:
            value = typ(raw.strip())
        except ValueError as exc:
            raise ValueError(f"{key}: ожидается {typ.__name__}") from exc
        if typ is int and value <= 0:
            raise ValueError(f"{key}: нужно число > 0")
        if typ is str and not value:
            raise ValueError(f"{key}: пустое значение")
        await self._store.set(key, str(value))
        self._overrides[key] = str(value)
        return value

    async def paused(self) -> bool:
        return self._overrides.get(PAUSED_KEY) == "1"

    async def set_paused(self, paused: bool) -> None:
        await self._store.set(PAUSED_KEY, "1" if paused else "0")
        self._overrides[PAUSED_KEY] = "1" if paused else "0"
