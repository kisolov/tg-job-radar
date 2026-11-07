"""Правила темпа и статусов аккаунта (R5, R6). Каждая операция: load → mutate → save по version."""
import logging
import random
from collections.abc import Callable
from datetime import timedelta
from typing import Literal
from uuid import UUID

from radar.accounts.entities import Account, AccountStatus, PacingPolicy
from radar.accounts.ports import AccountRepository, AlertSink, StaleAccount
from radar.shared.clock import Clock

logger = logging.getLogger(__name__)

Action = Literal["join", "resolve"]
LONG_FLOOD_S = 3600
SAVE_ATTEMPTS = 3


class AccountService:
    def __init__(
        self, accounts: AccountRepository, alerts: AlertSink, clock: Clock, rng: random.Random,
        join_policy: PacingPolicy, resolve_policy: PacingPolicy,
    ) -> None:
        self._accounts = accounts
        self._alerts = alerts
        self._clock = clock
        self._rng = rng
        self._policies = {"join": join_policy, "resolve": resolve_policy}

    async def _mutate(self, account_id: UUID, change: Callable[[Account], str | None]) -> Account | None:
        """change мутирует аккаунт и возвращает текст алерта (или None). Алерт — только после успешной записи."""
        for _ in range(SAVE_ATTEMPTS):
            account = await self._accounts.get(account_id)
            if account is None:
                return None
            alert = change(account)
            try:
                await self._accounts.save(account)
            except StaleAccount:
                continue
            if alert:
                await self._alerts.notify(alert)
            return account
        raise StaleAccount(account_id)

    def _pacer(self, account: Account, action: Action):
        return account.join if action == "join" else account.resolve

    async def record_action(self, account_id: UUID, action: Action) -> Account | None:
        now, policy = self._clock.now(), self._policies[action]

        def change(a: Account) -> None:
            self._pacer(a, action).record_action(now, self._rng, policy)

        return await self._mutate(account_id, change)

    async def roll_day(self, account_id: UUID) -> Account | None:
        now = self._clock.now()

        def change(a: Account) -> None:
            a.join.roll_day(now, self._rng, self._policies["join"])
            a.resolve.roll_day(now, self._rng, self._policies["resolve"])

        return await self._mutate(account_id, change)

    async def apply_flood(self, account_id: UUID, action: Action, seconds: float) -> Account | None:
        now, policy = self._clock.now(), self._policies[action]

        def change(a: Account) -> str | None:
            self._pacer(a, action).record_flood(now, seconds, policy)
            if seconds <= LONG_FLOOD_S or a.status is not AccountStatus.active:
                return None
            if action == "resolve":  # I1: резолв тормозит только свой пейсер, чтение аккаунта продолжается
                a.last_error = f"FloodWait {int(seconds)} с на резолве"
                until = now + timedelta(seconds=seconds)
                return f"⚠️ Аккаунт {a.phone}: FloodWait {int(seconds) // 60} мин на резолве, резолв на паузе до {until:%H:%M} UTC; чтение идёт"
            a.status = AccountStatus.flood_wait
            a.status_until = now + timedelta(seconds=seconds)
            a.last_error = f"FloodWait {int(seconds)} с на {action}"
            return f"⚠️ Аккаунт {a.phone}: FloodWait {int(seconds) // 60} мин ({action}), пауза до {a.status_until:%H:%M} UTC"

        return await self._mutate(account_id, change)

    async def mark_failed(self, account_id: UUID, status: AccountStatus, error: str) -> Account | None:
        def change(a: Account) -> str | None:
            changed = a.status is not status
            a.status, a.last_error = status, error
            if changed and status in (AccountStatus.banned, AccountStatus.unauthorized):
                return f"🚫 Аккаунт {a.phone}: {status.value} ({error}). Его группы возвращены в очередь."
            return None

        return await self._mutate(account_id, change)

    async def wake_expired(self) -> list[Account]:
        now, woken = self._clock.now(), []
        for a in await self._accounts.list_all():
            if a.status is AccountStatus.flood_wait and a.status_until and a.status_until <= now:

                def change(x: Account) -> None:
                    if x.status is AccountStatus.flood_wait:
                        x.status, x.status_until = AccountStatus.active, None

                if (done := await self._mutate(a.id, change)) is not None:
                    woken.append(done)
        return woken

    async def mark_membership_full(self, account_id: UUID, cap: int) -> Account | None:
        """Telegram ответил ChannelsTooMuch: недостающее до лимита — чаты вне нашего учёта (M4). Наш счётчик
        не трогаем, поэтому освобождение слотов потом не уводит его ниже реального."""

        def change(a: Account) -> None:
            a.external_memberships = max(a.external_memberships, cap - a.membership_count)

        return await self._mutate(account_id, change)

    async def disable(self, account_id: UUID) -> Account | None:
        def change(a: Account) -> None:
            a.status = AccountStatus.disabled

        return await self._mutate(account_id, change)
