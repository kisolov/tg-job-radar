"""Операции чтения Telegram. Сервиса нет: usecase работает с портами напрямую (правил здесь нет)."""
import asyncio
import logging
from datetime import timedelta
from uuid import UUID

from radar.accounts.ports import AccountRepository
from radar.accounts.service import AccountService
from radar.ingest.ports import (
    GatewayFactory,
    IncomingMessage,
    MessageLog,
    MessageSink,
    TelegramGateway,
    TgChannelsTooMuch,
    TgFlood,
    TgJoinRequested,
    TgSourceGone,
)
from radar.shared.clock import Clock
from radar.sources.entities import SourceKind, SourceStatus
from radar.sources.ports import SourceRepository
from radar.sources.service import AddResult, SourceService

logger = logging.getLogger(__name__)

POLL_BATCH = 5
FIRST_POLL_LIMIT = 20
FIRST_POLL_MAX_AGE = timedelta(hours=24)
CHANNELS_TOO_MUCH_PAUSE_S = 3600


class ReceiveMessage:
    """Вход любого сообщения (live или опрос). R2: обрабатывает только тот, кто первым записал (source, id)."""

    def __init__(self, log: MessageLog, sink: MessageSink, sources: SourceRepository, clock: Clock) -> None:
        self._log, self._sink, self._sources, self._clock = log, sink, sources, clock

    async def execute(self, msg: IncomingMessage) -> bool:
        await self._sources.set_cursor(msg.source_id, msg.message_id)
        if not await self._log.remember(msg.source_id, msg.message_id, self._clock.now()):
            return False
        await self._sink.submit(msg)
        return True


class PollChannels:
    """Опрос истории закреплённых каналов (и догон вступленных групп после простоя) по курсору."""

    def __init__(self, sources: SourceRepository, receive: ReceiveMessage, clock: Clock, interval_s: float) -> None:
        self._sources, self._receive, self._clock = sources, receive, clock
        self._interval = timedelta(seconds=interval_s)

    async def execute(self, account_id: UUID, gateway: TelegramGateway) -> int:
        """TgFlood пробрасывается — паузу опроса решает воркер аккаунта."""
        now = self._clock.now()
        due = await self._sources.due_for_poll(account_id, now - self._interval, POLL_BATCH)
        for source in due:
            first = source.last_message_id == 0
            try:
                msgs = await gateway.fetch_new(source, source.last_message_id,
                                               FIRST_POLL_LIMIT if first else 100)
            except TgSourceGone:
                await self._sources.release(source.id)
                await self._sources.mark(source.id, SourceStatus.dead)
                continue
            if first:
                # Первый опрос не тащит в отбор старую историю: только последние сутки, остальное — курсор.
                fresh = [m for m in msgs if m.date >= now - FIRST_POLL_MAX_AGE]
                if msgs and not fresh:
                    await self._sources.set_cursor(source.id, msgs[-1].message_id)
                msgs = fresh
            for m in msgs:
                await self._receive.execute(m)
            await self._sources.set_polled(source.id, now)
        return len(due)


class RunJoinQueue:
    """Одно вступление аккаунта за тик, если позволяет его темп (R5) и лимит членства (R4)."""

    def __init__(self, accounts: AccountRepository, account_service: AccountService, sources: SourceRepository,
                 clock: Clock, membership_cap: int) -> None:
        self._accounts, self._svc, self._sources = accounts, account_service, sources
        self._clock, self._cap = clock, membership_cap

    async def tick(self, account_id: UUID, gateway: TelegramGateway) -> bool:
        account = await self._accounts.get(account_id)
        if account is None or not account.can_join(self._clock.now(), self._cap):
            return False
        pending = [s for s in await self._sources.list_assigned(account_id, SourceKind.group)
                   if not s.joined and s.status is SourceStatus.active]
        if not pending:
            return False
        source = min(pending, key=lambda s: (-s.priority, s.id))
        try:
            peer = await gateway.join(source)
        except TgFlood as e:
            await self._svc.apply_flood(account_id, "join", e.seconds)
            return True
        except TgChannelsTooMuch:
            await self._sources.release(source.id)
            await self._svc.apply_flood(account_id, "join", CHANNELS_TOO_MUCH_PAUSE_S)
            await self._svc.mark_membership_full(account_id, self._cap)
            return True
        except (TgSourceGone, TgJoinRequested) as e:
            await self._sources.release(source.id)
            status = SourceStatus.dead if isinstance(e, TgSourceGone) else SourceStatus.rejected
            await self._sources.mark(source.id, status)
            await self._svc.record_action(account_id, "join")
            return True
        await self._svc.record_action(account_id, "join")
        if source.peer_id is None and not await self._sources.set_peer(source.id, peer.peer_id, peer.access_hash):
            # инвайт привёл в уже известный чат (R7): выйти, освободить слот
            await self._sources.release(source.id)
            await gateway.leave(source)
            return True
        await self._sources.set_joined(source.id)
        return True


class SearchSources:
    """Глобальный поиск Telegram (для стартового списка): находки → кандидаты `seed`.

    Запросы идут с первого active-аккаунта, с паузой его resolve-Pacer между запросами.
    """

    def __init__(self, accounts: AccountRepository, account_service: AccountService, sources: SourceRepository,
                 gateway_factory: GatewayFactory, clock: Clock, sleep=None) -> None:
        self._accounts, self._svc, self._sources, self._factory = accounts, account_service, sources, gateway_factory
        self._clock, self._sleep = clock, sleep or asyncio.sleep

    async def execute(self, queries: list[str], priority: int = 5) -> AddResult:
        result = AddResult()
        active = await self._accounts.list_active()
        if not active:
            raise RuntimeError("Нет active-аккаунтов для поиска")
        account_id = active[0].id
        gateway = self._factory(active[0])
        await gateway.start()
        try:
            for query in queries:
                account = await self._accounts.get(account_id)
                wait = (account.resolve.next_allowed_at - self._clock.now()).total_seconds()
                if wait > 0:
                    await self._sleep(wait)
                try:
                    found = await gateway.search(query)
                except TgFlood as e:
                    await self._svc.apply_flood(account_id, "resolve", e.seconds)
                    continue
                await self._svc.record_action(account_id, "resolve")
                for username, _title, _kind in found:
                    ref = username.lower()
                    added = await self._sources.add_candidate(ref, "seed", priority)
                    (result.added if added else result.duplicates).append(ref)
        finally:
            await gateway.stop()
        return result


class RunResolveQueue:
    """Один резолв аккаунта за тик: кандидат с наибольшим priority → peer id + access_hash в каталог."""

    def __init__(self, accounts: AccountRepository, account_service: AccountService, sources: SourceRepository,
                 clock: Clock, source_service: SourceService | None = None) -> None:
        self._accounts, self._svc, self._sources, self._clock = accounts, account_service, sources, clock
        self._source_service = source_service

    async def tick(self, account_id: UUID, gateway: TelegramGateway) -> bool:
        account = await self._accounts.get(account_id)
        if account is None or not account.can_resolve(self._clock.now()):
            return False
        source = await self._sources.claim_candidate()
        if source is None:
            return False
        try:
            resolved = await gateway.resolve(source.ref)
        except TgFlood as e:
            await self._sources.mark(source.id, SourceStatus.candidate)
            await self._svc.apply_flood(account_id, "resolve", e.seconds)
            return True
        except TgSourceGone:
            await self._sources.mark(source.id, SourceStatus.dead)
            await self._svc.record_action(account_id, "resolve")
            return True
        except BaseException:
            await self._sources.mark(source.id, SourceStatus.candidate)
            raise
        await self._svc.record_action(account_id, "resolve")
        if resolved.kind is None:
            await self._sources.mark(source.id, SourceStatus.rejected)  # человек или бот, не чат
            return True
        if not await self._sources.set_resolved(source.id, resolved.peer_id, resolved.access_hash,
                                                resolved.kind, resolved.title, at=self._clock.now()):
            return True  # дубль уже известного чата (R7)
        if source.added_by == "discovery" and self._source_service is not None:
            await self._vet(source.id, resolved, gateway)
        return True

    async def _vet(self, source_id: int, resolved, gateway: TelegramGateway) -> None:
        """Кандидат из автопополнения: по теме, по-русски, не ретранслятор агрегатора — иначе rejected."""
        sample: list[str] = []
        current = await self._sources.get(source_id)
        if current is not None and current.peer_id is not None:
            try:
                sample = [m.text for m in await gateway.recent(current, 30)]
            except (TgSourceGone, TgFlood):
                sample = []
        verdict = self._source_service.vet(resolved.title, resolved.about, sample)
        if verdict is SourceStatus.rejected:
            await self._sources.mark(source_id, SourceStatus.rejected)
