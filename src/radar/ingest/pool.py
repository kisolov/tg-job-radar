"""Пул: одна корутина на active-аккаунт. Действия аккаунта последовательны (допущение одной реплики)."""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import UUID

from radar.accounts.entities import Account, AccountStatus
from radar.accounts.ports import AccountRepository
from radar.accounts.service import LONG_FLOOD_S, AccountService
from radar.ingest.ports import (
    GatewayFactory,
    IncomingMessage,
    TelegramGateway,
    TgBanned,
    TgFlood,
    TgSourceGone,
    TgUnauthorized,
)
from radar.ingest.usecases import PollChannels, ReceiveMessage, RunJoinQueue, RunResolveQueue
from radar.shared.clock import Clock
from radar.sources.entities import SourceStatus
from radar.sources.ports import SourceRepository
from radar.sources.usecases import AssignWork, ReleaseAccountSources

logger = logging.getLogger(__name__)

TICK_S = 5
SYNC_S = 60


class AccountWorker:
    def __init__(
        self, account_id: UUID, gateway: TelegramGateway, accounts: AccountRepository,
        account_service: AccountService, join_queue: RunJoinQueue, resolve_queue: RunResolveQueue,
        poll: PollChannels, receive: ReceiveMessage, release_sources: ReleaseAccountSources,
        sources: SourceRepository, clock: Clock,
    ) -> None:
        self._clock = clock
        self.account_id, self.gateway = account_id, gateway
        self._accounts, self._svc = accounts, account_service
        self._join, self._resolve, self._poll, self._receive = join_queue, resolve_queue, poll, receive
        self._release, self._sources = release_sources, sources
        self._poll_paused_until = None

    async def start(self) -> bool:
        try:
            await self.gateway.start()
        except TgBanned as e:
            await self._fail(AccountStatus.banned, type(e).__name__ if not str(e) else str(e))
            return False
        except TgUnauthorized as e:
            await self._fail(AccountStatus.unauthorized, str(e) or "сессия недействительна")
            return False
        self.gateway.on_message(self._on_live)
        return True

    async def _on_live(self, msg: IncomingMessage) -> None:
        try:
            await self._receive.execute(msg)
        except Exception:
            logger.exception("Ошибка обработки live-сообщения %s/%s", msg.source_id, msg.message_id)

    async def step(self) -> bool:
        """Один проход: вступление, резолв, опрос. False — аккаунт выбыл, корутину завершить."""
        account = await self._accounts.get(self.account_id)
        if account is None or account.status is not AccountStatus.active:
            await self.gateway.stop()
            return False
        if not self.gateway.is_connected():
            logger.warning("Аккаунт %s: связь с Telegram потеряна, переподключение при синхронизации пула", account.phone)
            await self.gateway.stop()
            return False
        try:
            await self._housekeeping(account)
            await self._join.tick(self.account_id, self.gateway)
            await self._resolve.tick(self.account_id, self.gateway)
            await self._maybe_poll(account)
        except TgBanned as e:
            await self._fail(AccountStatus.banned, str(e) or "TgBanned")
            return False
        except TgUnauthorized as e:
            await self._fail(AccountStatus.unauthorized, str(e) or "TgUnauthorized")
            return False
        except ConnectionError:
            logger.warning("Аккаунт %s: обрыв связи, переподключение при синхронизации пула", account.phone)
            await self.gateway.stop()
            return False
        except Exception:
            logger.exception("Сбой шага аккаунта %s, продолжаем", account.phone)
        return True

    async def _housekeeping(self, account: Account) -> None:
        if account.join.day != self._now().date():
            await self._svc.roll_day(self.account_id)
        for s in await self._sources.list_to_leave(self.account_id):
            try:
                await self.gateway.leave(s)
            except TgSourceGone:
                pass  # нас уже нет в чате
            except (TgFlood, TgBanned, TgUnauthorized, ConnectionError):
                raise
            except Exception:  # I3: битый выход не держит весь шаг; слот освобождаем всё равно
                logger.exception("Не удалось выйти из %s, слот освобождён", s.ref)
            await self._sources.release(s.id)
        joined = [s for s in await self._sources.list_members(self.account_id)
                  if s.joined and s.status is SourceStatus.active]
        self.gateway.watch(joined)

    async def _maybe_poll(self, account: Account) -> None:
        now = self._now()
        if self._poll_paused_until and now < self._poll_paused_until:
            return
        try:
            await self._poll.execute(self.account_id, self.gateway)
        except TgFlood as e:
            self._poll_paused_until = now + timedelta(seconds=e.seconds)
            if e.seconds > LONG_FLOOD_S:
                await self._svc.apply_flood(self.account_id, "resolve", e.seconds)

    def _now(self):
        return self._clock.now()

    async def _fail(self, status: AccountStatus, error: str) -> None:
        await self._svc.mark_failed(self.account_id, status, error)
        await self._release.execute(self.account_id)
        await self.gateway.stop()


class WorkerFactory:
    """Собирает AccountWorker на аккаунт: свой шлюз, общие usecases."""

    def __init__(self, gateway_factory: GatewayFactory, accounts: AccountRepository, account_service: AccountService,
                 join_queue: RunJoinQueue, resolve_queue: RunResolveQueue, poll: PollChannels,
                 receive: ReceiveMessage, release_sources: ReleaseAccountSources, sources: SourceRepository,
                 clock: Clock) -> None:
        self._gateways = gateway_factory
        self._deps = dict(accounts=accounts, account_service=account_service, join_queue=join_queue,
                          resolve_queue=resolve_queue, poll=poll, receive=receive, release_sources=release_sources,
                          sources=sources, clock=clock)

    def __call__(self, account: Account) -> AccountWorker:
        return AccountWorker(account_id=account.id, gateway=self._gateways(account), **self._deps)


class PoolRunner:
    def __init__(
        self, accounts: AccountRepository, worker_factory: Callable[[Account], AccountWorker],
        account_service: AccountService, assign: AssignWork,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._accounts, self._factory, self._svc, self._assign = accounts, worker_factory, account_service, assign
        self._sleep = sleep or asyncio.sleep
        self.running: dict[UUID, asyncio.Task] = {}

    async def sync(self) -> None:
        """Горячее добавление: новые active-аккаунты получают корутину; раздача свободных источников."""
        await self._svc.wake_expired()
        self.running = {k: t for k, t in self.running.items() if not t.done()}
        for account in await self._accounts.list_active():
            if account.id not in self.running:
                self.running[account.id] = asyncio.create_task(self._run(self._factory(account)))
        await self._assign.execute()

    async def _run(self, worker: AccountWorker) -> None:
        """Корутина аккаунта. Завершилась (обрыв связи, сбой старта) — следующий sync() создаст её заново."""
        try:
            if not await worker.start():
                return
            while await worker.step():
                await self._sleep(TICK_S)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Корутина аккаунта %s упала, перезапуск при синхронизации", worker.account_id)
        finally:
            await worker.gateway.stop()

    async def run_forever(self) -> None:
        while True:
            try:
                await self.sync()
            except Exception:
                logger.exception("Сбой синхронизации пула")
            await self._sleep(SYNC_S)

    async def stop(self) -> None:
        tasks = list(self.running.values())
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.running.clear()
