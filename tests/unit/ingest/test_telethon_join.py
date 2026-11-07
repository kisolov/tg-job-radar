"""C2: TelethonGateway.join/ошибки без сети — клиент Telethon заменён записывающей заглушкой."""
from types import SimpleNamespace

import pytest
from telethon import errors
from telethon.tl import types
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

from radar.ingest.adapters.telethon_gateway import TelethonGateway, map_error
from radar.ingest.ports import TgPeerStale
from tests.unit.ingest.test_telethon_mapping import _src


class StubClient:
    def __init__(self, reply):
        self.calls, self.reply = [], reply

    async def __call__(self, request):
        self.calls.append(request)
        return self.reply


def gateway(client) -> TelethonGateway:
    gw = TelethonGateway.__new__(TelethonGateway)
    gw._client = client
    return gw


def test_channel_invalid_means_stale_hash_not_dead_chat():
    assert isinstance(map_error(errors.ChannelInvalidError(request=None)), TgPeerStale)


async def test_invite_join_imports_invite_even_when_peer_is_known():
    chat = types.Channel(id=1234567, title="Priv", photo=types.ChatPhotoEmpty(), date=None, access_hash=555,
                         broadcast=True)
    client = StubClient(SimpleNamespace(chats=[chat]))
    peer = await gateway(client).join(_src(username=None, invite_hash="+AbCd", peer_id=-1000001234567, access_hash=9))
    assert isinstance(client.calls[0], ImportChatInviteRequest) and client.calls[0].hash == "AbCd"
    assert peer.access_hash == 555  # хэш вступившего, а не тот, что лежал в каталоге


async def test_public_group_join_uses_join_channel():
    client = StubClient(None)
    await gateway(client).join(_src(kind=None, peer_id=-1000001234567, access_hash=9))
    assert isinstance(client.calls[0], JoinChannelRequest)


@pytest.mark.parametrize("err", [errors.ChannelInvalidError(request=None)])
async def test_join_maps_stale_hash(err):
    class Failing(StubClient):
        async def __call__(self, request):
            raise err

    with pytest.raises(TgPeerStale):
        await gateway(Failing(None)).join(_src(peer_id=-1000001234567, access_hash=9))


async def test_resolve_picks_the_chat_named_by_peer():
    """M1: в ответе ResolveUsername бывает несколько чатов (например, связанный канал) — берём тот, что в res.peer."""
    linked = types.Channel(id=111, title="Связанный", photo=types.ChatPhotoEmpty(), date=None, access_hash=1,
                           broadcast=True)
    target = types.Channel(id=222, title="Нужный", photo=types.ChatPhotoEmpty(), date=None, access_hash=2,
                           megagroup=True)
    res = SimpleNamespace(peer=types.PeerChannel(222), chats=[linked, target], users=[])
    got = await gateway(StubClient(res)).resolve("needed_chat")
    assert got.title == "Нужный" and got.access_hash == 2
