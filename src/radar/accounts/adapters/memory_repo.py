from copy import deepcopy
from uuid import UUID

from radar.accounts.entities import Account, AccountStatus
from radar.accounts.ports import AccountExists, StaleAccount


class InMemoryAccountRepository:
    """Фейк с той же семантикой, что SQL: отдаёт копии, save — по version.

    Поле `rows` открыто для фейка источников: закрепление группы меняет счётчик членств
    в той же «транзакции», как в SQL-адаптере.
    """

    def __init__(self) -> None:
        self.rows: dict[UUID, Account] = {}

    async def add(self, account: Account) -> None:
        if any(a.phone == account.phone for a in self.rows.values()):
            raise AccountExists(account.phone)
        self.rows[account.id] = deepcopy(account)

    async def get(self, account_id: UUID) -> Account | None:
        a = self.rows.get(account_id)
        return deepcopy(a) if a else None

    async def get_by_phone(self, phone: str) -> Account | None:
        return next((deepcopy(a) for a in self.rows.values() if a.phone == phone), None)

    async def list_active(self) -> list[Account]:
        return [deepcopy(a) for a in self.rows.values() if a.status is AccountStatus.active]

    async def list_all(self) -> list[Account]:
        return [deepcopy(a) for a in self.rows.values()]

    async def save(self, account: Account) -> None:
        current = self.rows.get(account.id)
        if current is None or current.version != account.version:
            raise StaleAccount(account.id)
        account.version += 1
        self.rows[account.id] = deepcopy(account)
