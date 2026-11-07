"""Фейковый Telegram: общий «мир» и шлюз на аккаунт (аналог _FakeClient из infomir)."""
from dataclasses import dataclass, field
from datetime import UTC, datetime

from radar.accounts.entities import Account
from radar.ingest.ports import IncomingMessage, MessageCallback, Peer, Resolved, TgPeerStale
from radar.sources.entities import Source, SourceKind


@dataclass
class FakeTelegram:
    chats: dict[str, Resolved] = field(default_factory=dict)  # ref → что вернёт resolve
    history: dict[int, list[IncomingMessage]] = field(default_factory=dict)  # source_id → сообщения
    errors: dict[tuple[str, object], Exception] = field(default_factory=dict)  # (op, key) → исключение
    account_errors: dict[str, Exception] = field(default_factory=dict)  # phone → исключение на любой вызов
    search_results: dict[str, list[tuple[str, str, SourceKind]]] = field(default_factory=dict)
    joins: list[tuple[str, str]] = field(default_factory=list)
    fetches: list[tuple[str, int, int]] = field(default_factory=list)
    resolves: list[tuple[str, str]] = field(default_factory=list)
    gateways: list["FakeGateway"] = field(default_factory=list)
    next_peer: int = 10_000
    invite_peers: dict[str, int] = field(default_factory=dict)  # инвайт → чат, в который он ведёт

    @staticmethod
    def hash_for(peer_id: int, account: Account) -> int:
        """Как в Telegram: access_hash выдаётся паре (чат, аккаунт); чужой хэш не принимается (C2)."""
        return (peer_id * 7919 + sum(map(ord, account.phone))) % 1_000_003 + 1

    def factory(self, account: Account) -> "FakeGateway":
        gw = FakeGateway(self, account)
        self.gateways.append(gw)
        return gw

    def post(self, source_id: int, message_id: int, text: str, **kw) -> IncomingMessage:
        msg = IncomingMessage(
            source_id=source_id, message_id=message_id, text=text,
            date=kw.pop("date", datetime(2026, 11, 4, 12, 0, tzinfo=UTC)),
            sender_id=kw.pop("sender_id", 500), sender_username=kw.pop("sender_username", "author"),
            sender_is_user=kw.pop("sender_is_user", True), fwd_from_username=kw.pop("fwd_from_username", None),
            link=kw.pop("link", f"https://t.me/c/{source_id}/{message_id}"),
            source_title=kw.pop("source_title", f"chat {source_id}"),
        )
        assert not kw, kw
        self.history.setdefault(source_id, []).append(msg)
        return msg

    async def push_live(self, msg: IncomingMessage) -> int:
        delivered = 0
        for gw in self.gateways:
            if gw.started and msg.source_id in gw.watched and gw.callback:
                await gw.callback(msg)
                delivered += 1
        return delivered


class FakeGateway:
    def __init__(self, world: FakeTelegram, account: Account) -> None:
        self.world, self.account = world, account
        self.started = False
        self.callback: MessageCallback | None = None
        self.watched: set[int] = set()
        self.left: list[str] = []

    def _check(self, op: str, key: object) -> None:
        if exc := self.world.account_errors.get(self.account.phone):
            raise exc
        if exc := self.world.errors.get((op, key)):
            raise exc

    async def start(self) -> None:
        self._check("start", None)
        self.started = True

    async def stop(self) -> None:
        self.started = False

    def on_message(self, callback: MessageCallback) -> None:
        self.callback = callback

    def watch(self, sources: list[Source]) -> None:
        self.watched = {s.id for s in sources}

    def _check_hash(self, source: Source) -> None:
        if source.peer_id is not None and source.access_hash != self.world.hash_for(source.peer_id, self.account):
            raise TgPeerStale("ChannelInvalidError")

    async def fetch_new(self, source: Source, min_id: int, limit: int = 100) -> list[IncomingMessage]:
        self._check("fetch", source.id)
        self._check_hash(source)
        self.world.fetches.append((self.account.phone, source.id, min_id))
        msgs = sorted((m for m in self.world.history.get(source.id, []) if m.message_id > min_id),
                      key=lambda m: m.message_id)
        return msgs[-limit:] if min_id == 0 else msgs[:limit]

    async def resolve(self, ref: str) -> Resolved:
        self._check("resolve", ref)
        self.world.resolves.append((self.account.phone, ref))
        r = self.world.chats[ref]
        if r.peer_id is None:
            return r
        return Resolved(r.peer_id, self.world.hash_for(r.peer_id, self.account), r.kind, r.title, r.about)

    async def join(self, source: Source) -> Peer:
        self._check("join", source.ref)
        self.world.joins.append((self.account.phone, source.ref))
        if source.invite_hash:  # по инвайту — всегда импорт приглашения: хэш выдаётся вступившему
            peer = source.peer_id or self.world.invite_peers.get(source.invite_hash)
            if peer is None:
                self.world.next_peer += 1
                peer = self.world.invite_peers.setdefault(source.invite_hash, self.world.next_peer)
            return Peer(peer, self.world.hash_for(peer, self.account))
        self._check_hash(source)
        return Peer(source.peer_id, source.access_hash)

    async def leave(self, source: Source) -> None:
        self._check("leave", source.ref)
        self._check_hash(source)
        self.left.append(source.ref)

    async def recent(self, source: Source, limit: int = 30) -> list[IncomingMessage]:
        self._check("recent", source.id)
        return sorted(self.world.history.get(source.id, []), key=lambda m: m.message_id)[-limit:]

    async def search(self, query: str) -> list[tuple[str, str, SourceKind]]:
        self._check("search", query)
        return self.world.search_results.get(query, [])
