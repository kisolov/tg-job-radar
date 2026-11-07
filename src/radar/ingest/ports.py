"""Транспорт Telegram: порт шлюза (один на аккаунт), журнал виденных сообщений, приёмник конвейера."""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from radar.accounts.entities import Account
from radar.sources.entities import Source, SourceKind


@dataclass(frozen=True)
class IncomingMessage:
    source_id: int
    message_id: int
    text: str
    date: datetime
    sender_id: int | None
    sender_username: str | None
    sender_is_user: bool
    fwd_from_username: str | None
    link: str
    source_title: str | None = None


@dataclass(frozen=True)
class Resolved:
    peer_id: int | None  # None — инвайт, в который ещё не вступили
    access_hash: int | None
    kind: SourceKind | None  # None — это человек/бот, а не чат
    title: str
    about: str = ""


@dataclass(frozen=True)
class Peer:
    peer_id: int
    access_hash: int


class TgError(Exception):
    pass


class TgFlood(TgError):
    def __init__(self, seconds: int) -> None:
        super().__init__(f"FloodWait {seconds}s")
        self.seconds = seconds


class TgBanned(TgError):
    pass


class TgUnauthorized(TgError):
    pass


class TgSourceGone(TgError):
    """Чат приватный / удалён / username свободен / нас забанили в чате."""


class TgJoinRequested(TgError):
    """Вступление по заявке: заявка отправлена, ждать одобрения админа."""


class TgChannelsTooMuch(TgError):
    """Telegram отказал: у аккаунта максимум каналов/групп."""


MessageCallback = Callable[[IncomingMessage], Awaitable[None]]


class TelegramGateway(Protocol):
    """Сессия одного аккаунта. Все методы бросают Tg*-исключения, а не ошибки библиотеки."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def on_message(self, callback: MessageCallback) -> None: ...
    def watch(self, sources: list[Source]) -> None:
        """Live-апдейты передаются в callback только для этих источников."""

    async def fetch_new(self, source: Source, min_id: int, limit: int = 100) -> list[IncomingMessage]:
        """Сообщения с id > min_id, по возрастанию id. min_id == 0 — последние limit сообщений (хвост истории)."""

    async def recent(self, source: Source, limit: int = 30) -> list[IncomingMessage]:
        """Последние сообщения публичного чата (без вступления) — выборка для проверки кандидата."""

    async def resolve(self, ref: str) -> Resolved: ...
    async def join(self, source: Source) -> Peer: ...
    async def leave(self, source: Source) -> None: ...
    async def search(self, query: str) -> list[tuple[str, str, SourceKind]]:
        """Глобальный поиск Telegram: (username, title, kind)."""


class GatewayFactory(Protocol):
    def __call__(self, account: Account) -> TelegramGateway: ...


class MessageLog(Protocol):
    async def remember(self, source_id: int, message_id: int, seen_at: datetime) -> bool:
        """True — сообщение видим впервые (R2). Повтор → False."""

    async def purge_older(self, before: datetime) -> int: ...


class MessageSink(Protocol):
    async def submit(self, msg: IncomingMessage) -> None: ...
