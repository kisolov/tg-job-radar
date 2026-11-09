"""Импорт tdata (Telegram Desktop): адаптер на opentele + usecase поверх ImportAccount."""
import os

import pytest
from telethon.sessions import StringSession

from radar.accounts.adapters.memory_repo import InMemoryAccountRepository
from radar.accounts.adapters.tdata_reader import OpenteleTdataReader
from radar.accounts.ports import TdataSession
from radar.accounts.usecases import ImportTdata, InvalidAccountPayload
from tests.unit.accounts.test_import_account import FakeProbe, make_import

KEY = bytes(range(256))


def make_tdata(path, key=KEY, dc=2, user=777, passcode=None) -> None:
    """Настоящая tdata, записанная самим opentele: известный ключ авторизации, без сети."""
    from opentele.api import API
    from opentele.td import Account, AuthKey, TDesktop
    from opentele.td.auth import AuthKeyType
    from opentele.td.configs import DcId

    owner = TDesktop()
    owner._TDesktop__generateLocalKey()  # так делает сам TDesktop.FromTelethon
    acc = Account(owner=owner, api=API.TelegramDesktop, index=0)
    acc._setMtpAuthorizationCustom(DcId(dc), user, [AuthKey(key, AuthKeyType.ReadFromFile, DcId(dc))])
    owner._addSingleAccount(acc)
    owner.SaveTData(str(path), passcode=passcode)


async def test_reader_turns_tdata_into_telethon_session(tmp_path):
    make_tdata(tmp_path / "tdata")
    [got] = await OpenteleTdataReader().read(tmp_path / "tdata")
    s = StringSession(got.session)
    assert s.auth_key.key == KEY and s.dc_id == 2 and s.port == 443
    assert (got.api_id, got.api_hash) == (2040, "b18441a1ff607e10a989891a5462e627") and got.user_id == 777


async def test_reader_accepts_parent_folder(tmp_path):
    """Часто присылают папку «аккаунт/tdata» — можно указать и родителя."""
    make_tdata(tmp_path / "acc" / "tdata")
    assert len(await OpenteleTdataReader().read(tmp_path / "acc")) == 1


async def test_reader_passcode(tmp_path):
    make_tdata(tmp_path / "tdata", passcode="1234")
    with pytest.raises(InvalidAccountPayload, match="код-парол"):
        await OpenteleTdataReader().read(tmp_path / "tdata")
    with pytest.raises(InvalidAccountPayload, match="код-парол"):
        await OpenteleTdataReader().read(tmp_path / "tdata", passcode="0000")
    [got] = await OpenteleTdataReader().read(tmp_path / "tdata", passcode="1234")
    assert StringSession(got.session).auth_key.key == KEY


async def test_reader_rejects_non_tdata(tmp_path):
    (tmp_path / "junk").mkdir()
    (tmp_path / "junk" / "key_datas").write_bytes(os.urandom(64))
    with pytest.raises(InvalidAccountPayload, match="tdata"):
        await OpenteleTdataReader().read(tmp_path / "junk")
    with pytest.raises(InvalidAccountPayload, match="tdata"):
        await OpenteleTdataReader().read(tmp_path / "missing")


class FakeReader:
    def __init__(self, sessions):
        self.sessions, self.calls = sessions, []

    async def read(self, path, passcode=None):
        self.calls.append((path, passcode))
        return self.sessions


def sess(n=1):
    return TdataSession(session=f"S{n}", api_id=2040, api_hash="h", user_id=n)


async def test_import_tdata_asks_telegram_for_the_phone(clock):
    repo, probe = InMemoryAccountRepository(), FakeProbe()
    probe.phones = {"S1": "79001112233", "S2": "+79004445566"}
    uc = ImportTdata(make_import(repo, probe, clock), FakeReader([sess(1), sess(2)]), probe)
    accounts = await uc.execute("/x/tdata", passcode="p")
    assert sorted(a.phone for a in accounts) == ["+79001112233", "+79004445566"]
    assert all(a.api_id == 2040 for a in accounts)


async def test_import_tdata_with_explicit_phone(clock):
    repo, probe = InMemoryAccountRepository(), FakeProbe()
    uc = ImportTdata(make_import(repo, probe, clock), FakeReader([sess(1)]), probe)
    [acc] = await uc.execute("/x/tdata", phone="+7 900 111-22-33")
    assert acc.phone == "+79001112233"
    with pytest.raises(InvalidAccountPayload, match="--phone"):
        await ImportTdata(make_import(repo, probe, clock), FakeReader([sess(1), sess(2)]), probe).execute(
            "/x", phone="+79001112233")


async def test_import_tdata_unknown_phone_is_an_error(clock):
    """Сессия разлогинена — номер у Telegram не узнать; без --phone импортировать нечего."""
    repo, probe = InMemoryAccountRepository(), FakeProbe()
    probe.phones = {}
    with pytest.raises(InvalidAccountPayload, match="--phone"):
        await ImportTdata(make_import(repo, probe, clock), FakeReader([sess(1)]), probe).execute("/x")
    assert await repo.list_all() == []
