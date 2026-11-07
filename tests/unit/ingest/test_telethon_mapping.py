from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from telethon import errors
from telethon.tl import types

from radar.ingest.adapters.telethon_gateway import map_error, message_link, to_incoming
from radar.ingest.ports import (
    TgBanned,
    TgChannelsTooMuch,
    TgFlood,
    TgJoinRequested,
    TgSourceGone,
    TgUnauthorized,
)
from radar.sources.entities import Source, SourceKind, SourceStatus


def _src(**kw) -> Source:
    base = dict(id=3, username="jobs_py", invite_hash=None, peer_id=-1000001234567, access_hash=9,
                kind=SourceKind.channel, title="Jobs", status=SourceStatus.active, assigned_account_id=None,
                joined=False, last_message_id=0, found_count=0, relay_score=0.0, added_by="seed", priority=5)
    base.update(kw)
    return Source(**base)


@pytest.mark.parametrize("exc,expected", [
    (errors.FloodWaitError(request=None, capture=42), TgFlood),
    (errors.UserDeactivatedBanError(request=None), TgBanned),
    (errors.AuthKeyUnregisteredError(request=None), TgUnauthorized),
    (errors.SessionRevokedError(request=None), TgUnauthorized),
    (errors.ChannelPrivateError(request=None), TgSourceGone),
    (errors.UsernameNotOccupiedError(request=None), TgSourceGone),
    (errors.InviteHashExpiredError(request=None), TgSourceGone),
    (errors.InviteRequestSentError(request=None), TgJoinRequested),
    (errors.ChannelsTooMuchError(request=None), TgChannelsTooMuch),
])
def test_map_error(exc, expected):
    mapped = map_error(exc)
    assert isinstance(mapped, expected)
    if expected is TgFlood:
        assert mapped.seconds == 42


def test_unknown_error_not_mapped():
    assert map_error(RuntimeError("x")) is None


def test_message_link():
    assert message_link(_src(), 55) == "https://t.me/jobs_py/55"
    assert message_link(_src(username=None, invite_hash="+x"), 55) == "https://t.me/c/1234567/55"


def test_to_incoming_user_sender_and_caption():
    sender = types.User(id=77, username="hr_anna", bot=False)
    m = SimpleNamespace(id=5, message="Подпись к фото: нужен python-разработчик", date=datetime(2026, 11, 4, tzinfo=UTC),
                        sender=sender, sender_id=77, forward=None)
    got = to_incoming(_src(), m)
    assert (got.text, got.sender_username, got.sender_is_user, got.link) == (
        "Подпись к фото: нужен python-разработчик", "hr_anna", True, "https://t.me/jobs_py/5")


def test_to_incoming_channel_post_and_forward():
    chan = types.Channel(id=1, title="X", photo=types.ChatPhotoEmpty(), date=None, username="xchan")
    fwd = SimpleNamespace(chat=types.Channel(id=2, title="Y", photo=types.ChatPhotoEmpty(), date=None, username="src_chan"))
    m = SimpleNamespace(id=6, message=None, date=datetime(2026, 11, 4, tzinfo=UTC), sender=chan, sender_id=-1001,
                        forward=fwd)
    got = to_incoming(_src(), m)
    assert got.text == "" and not got.sender_is_user and got.sender_username == "xchan"
    assert got.fwd_from_username == "src_chan"


def test_to_incoming_user_without_entity_still_gets_profile_link():
    """I7: в live-апдейте sender бывает None (min-сущность), но sender_id > 0 — это человек."""
    m = SimpleNamespace(id=7, message="нужен бот", date=datetime(2026, 11, 4, tzinfo=UTC), sender=None,
                        sender_id=4242, forward=None)
    got = to_incoming(_src(), m)
    assert got.sender_is_user and got.sender_id == 4242 and got.sender_username is None


def test_to_incoming_takes_first_active_username_of_collectible_names():
    """I7: у пользователя с несколькими username (Fragment) основной лежит в usernames, а username — None."""
    sender = types.User(id=78, username=None, bot=False, usernames=[
        types.Username(username="old_nick", editable=False, active=False),
        types.Username(username="cto_marina", editable=True, active=True)])
    m = SimpleNamespace(id=8, message="x", date=datetime(2026, 11, 4, tzinfo=UTC), sender=sender, sender_id=78,
                        forward=None)
    assert to_incoming(_src(), m).sender_username == "cto_marina"


def test_to_incoming_anonymous_admin_is_not_a_user():
    m = SimpleNamespace(id=9, message="x", date=datetime(2026, 11, 4, tzinfo=UTC), sender=None,
                        sender_id=-1001234, forward=None)
    assert not to_incoming(_src(), m).sender_is_user
