from typing import Protocol
from uuid import UUID

from radar.accounts.entities import Account, DeviceProfile


class AccountExists(Exception):
    pass


class StaleAccount(Exception):
    """Аккаунт изменён другой записью после чтения (version не совпал)."""


class AccountRepository(Protocol):
    async def add(self, account: Account) -> None: ...
    async def get(self, account_id: UUID) -> Account | None: ...
    async def get_by_phone(self, phone: str) -> Account | None: ...
    async def list_active(self) -> list[Account]: ...
    async def list_all(self) -> list[Account]: ...
    async def save(self, account: Account) -> None:
        """Conditional by version: при несовпадении — StaleAccount; при успехе account.version += 1."""


class SecretBox(Protocol):
    def encrypt(self, plain: str) -> str: ...
    def decrypt(self, token: str) -> str: ...


class SessionProbe(Protocol):
    async def check(self, session: str, api_id: int, api_hash: str, device: DeviceProfile) -> bool: ...


class DeviceProfileProvider(Protocol):
    def get(self, name: str | None = None) -> DeviceProfile: ...


class AlertSink(Protocol):
    async def notify(self, text: str) -> None: ...
