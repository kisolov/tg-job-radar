"""Telethon-адаптер шлюза: одна MTProto-сессия аккаунта. Ошибки библиотеки → Tg*-исключения порта."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from telethon import TelegramClient, errors, events, utils
from telethon.sessions import StringSession
from telethon.tl import types
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.functions.contacts import ResolveUsernameRequest, SearchRequest
from telethon.tl.functions.messages import CheckChatInviteRequest, DeleteChatUserRequest, ImportChatInviteRequest

from radar.accounts.entities import Account
from radar.accounts.ports import DeviceProfileProvider, SecretBox
from radar.ingest.ports import (
    IncomingMessage,
    MessageCallback,
    Peer,
    Resolved,
    TgBanned,
    TgChannelsTooMuch,
    TgError,
    TgFlood,
    TgJoinRequested,
    TgSourceGone,
    TgUnauthorized,
)
from radar.sources.entities import Source, SourceKind

logger = logging.getLogger(__name__)

_BANNED = (errors.UserDeactivatedBanError, errors.PhoneNumberBannedError)
_UNAUTHORIZED = (
    errors.UserDeactivatedError, errors.AuthKeyError, errors.AuthKeyUnregisteredError,
    errors.SessionRevokedError, errors.SessionExpiredError, errors.AuthKeyDuplicatedError,
)
_GONE = (
    errors.ChannelPrivateError, errors.ChannelInvalidError, errors.UsernameInvalidError,
    errors.UsernameNotOccupiedError, errors.UserBannedInChannelError, errors.InviteHashExpiredError,
    errors.InviteHashInvalidError, errors.ChannelBannedError, errors.ChatForbiddenError,
    errors.ChannelPublicGroupNaError, errors.UsernamePurchaseAvailableError,
)


def map_error(exc: BaseException) -> TgError | None:
    if isinstance(exc, TgError):
        return exc
    if isinstance(exc, (errors.FloodWaitError, errors.FloodPremiumWaitError)):
        return TgFlood(int(exc.seconds))
    if isinstance(exc, _BANNED):
        return TgBanned(type(exc).__name__)
    if isinstance(exc, _UNAUTHORIZED):
        return TgUnauthorized(type(exc).__name__)
    if isinstance(exc, _GONE):
        return TgSourceGone(type(exc).__name__)
    if isinstance(exc, errors.InviteRequestSentError):
        return TgJoinRequested(type(exc).__name__)
    if isinstance(exc, errors.ChannelsTooMuchError):
        return TgChannelsTooMuch(type(exc).__name__)
    return None


def _mapped(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            mapped = map_error(exc)
            if mapped is None or mapped is exc:
                raise
            raise mapped from exc

    return wrapper


def message_link(source: Source, message_id: int) -> str:
    if source.username:
        return f"https://t.me/{source.username}/{message_id}"
    real_id, _ = utils.resolve_id(source.peer_id or 0)
    return f"https://t.me/c/{real_id}/{message_id}"


def to_incoming(source: Source, m: Any) -> IncomingMessage:
    # sender бывает None (пост от имени канала, анонимный админ) — сообщение всё равно полезно.
    sender = getattr(m, "sender", None)
    is_user = isinstance(sender, types.User) and not sender.bot
    fwd_chat = getattr(getattr(m, "forward", None), "chat", None)
    return IncomingMessage(
        source_id=source.id, message_id=m.id, text=m.message or "", date=m.date,
        sender_id=getattr(m, "sender_id", None), sender_username=getattr(sender, "username", None),
        sender_is_user=is_user, fwd_from_username=getattr(fwd_chat, "username", None),
        link=message_link(source, m.id), source_title=source.title,
    )


def _kind(chat: Any) -> SourceKind | None:
    if isinstance(chat, types.Channel):
        return SourceKind.channel if chat.broadcast else SourceKind.group
    if isinstance(chat, types.Chat):
        return SourceKind.group
    return None


def _input_peer(source: Source):
    real_id, cls = utils.resolve_id(source.peer_id)
    if cls is types.PeerChannel:
        return types.InputPeerChannel(real_id, source.access_hash or 0)
    return types.InputPeerChat(real_id)


class TelethonGateway:
    def __init__(self, account: Account, box: SecretBox, devices: DeviceProfileProvider) -> None:
        self._account = account
        self._client = TelegramClient(
            StringSession(box.decrypt(account.session_enc)), account.api_id, box.decrypt(account.api_hash_enc),
            **devices.get(account.device_profile).as_client_kwargs(),
        )
        self._callback: MessageCallback | None = None
        self._watched: dict[int, Source] = {}
        self._client.add_event_handler(self._on_new_message, events.NewMessage(incoming=True))

    @_mapped
    async def start(self) -> None:
        # connect + проверка вместо start(): start() при невалидной сессии ждёт код в консоли и вешает процесс.
        await self._client.connect()
        if not await self._client.is_user_authorized():
            raise TgUnauthorized("сессия недействительна или разлогинена")
        logger.info("Аккаунт %s подключён", self._account.phone)

    async def stop(self) -> None:
        if self._client.is_connected():
            await self._client.disconnect()

    def on_message(self, callback: MessageCallback) -> None:
        self._callback = callback

    def watch(self, sources: list[Source]) -> None:
        self._watched = {s.peer_id: s for s in sources if s.peer_id is not None}

    async def _on_new_message(self, event) -> None:
        source = self._watched.get(event.chat_id)
        if source is None or self._callback is None:
            return
        await self._callback(to_incoming(source, event.message))

    @_mapped
    async def fetch_new(self, source: Source, min_id: int, limit: int = 100) -> list[IncomingMessage]:
        out = []
        async for m in self._client.iter_messages(_input_peer(source), min_id=min_id, limit=limit, reverse=True):
            if isinstance(m, types.Message):
                out.append(to_incoming(source, m))
        return out

    @_mapped
    async def resolve(self, ref: str) -> Resolved:
        if ref.startswith("+"):
            invite = await self._client(CheckChatInviteRequest(ref[1:]))
            chat = getattr(invite, "chat", None)
            if chat is not None:  # ChatInviteAlready / ChatInvitePeek
                return Resolved(utils.get_peer_id(chat), getattr(chat, "access_hash", None) or 0,
                                _kind(chat), chat.title)
            kind = SourceKind.channel if getattr(invite, "broadcast", False) else SourceKind.group
            return Resolved(None, None, kind, invite.title, getattr(invite, "about", "") or "")
        res = await self._client(ResolveUsernameRequest(ref))
        if isinstance(res.peer, types.PeerUser):
            user = res.users[0] if res.users else None
            return Resolved(None, None, None, getattr(user, "first_name", "") or "")
        chat = res.chats[0]
        return Resolved(utils.get_peer_id(chat), getattr(chat, "access_hash", None) or 0, _kind(chat), chat.title)

    @_mapped
    async def join(self, source: Source) -> Peer:
        if source.peer_id is None and source.invite_hash:
            try:
                updates = await self._client(ImportChatInviteRequest(source.invite_hash[1:]))
                chat = updates.chats[0]
            except errors.UserAlreadyParticipantError:
                chat = (await self._client(CheckChatInviteRequest(source.invite_hash[1:]))).chat
            return Peer(utils.get_peer_id(chat), getattr(chat, "access_hash", None) or 0)
        real_id, cls = utils.resolve_id(source.peer_id)
        if cls is types.PeerChannel:
            try:
                await self._client(JoinChannelRequest(types.InputChannel(real_id, source.access_hash or 0)))
            except errors.UserAlreadyParticipantError:
                pass
        return Peer(source.peer_id, source.access_hash or 0)

    @_mapped
    async def leave(self, source: Source) -> None:
        if source.peer_id is None:
            return
        real_id, cls = utils.resolve_id(source.peer_id)
        if cls is types.PeerChannel:
            await self._client(LeaveChannelRequest(types.InputChannel(real_id, source.access_hash or 0)))
        else:
            await self._client(DeleteChatUserRequest(real_id, types.InputUserSelf()))

    @_mapped
    async def search(self, query: str) -> list[tuple[str, str, SourceKind]]:
        res = await self._client(SearchRequest(q=query, limit=50))
        out = []
        for chat in res.chats:
            kind, username = _kind(chat), getattr(chat, "username", None)
            if kind and username:
                out.append((username, chat.title, kind))
        return out


class TelethonGatewayFactory:
    def __init__(self, box: SecretBox, devices: DeviceProfileProvider) -> None:
        self._box, self._devices = box, devices

    def __call__(self, account: Account) -> TelethonGateway:
        return TelethonGateway(account, self._box, self._devices)
