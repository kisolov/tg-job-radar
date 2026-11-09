"""`radar accounts import-tdata` через весь CLI: настоящая tdata → аккаунт в хранилище."""
from dependency_injector import providers
from telethon.sessions import StringSession

from radar.accounts.adapters.fernet_box import FernetSecretBox
from radar.accounts.adapters.memory_repo import InMemoryAccountRepository
from radar.bootstrap.cli import run
from radar.bootstrap.di import Container
from radar.shared.settings import Settings
from tests.unit.accounts.test_import_account import FakeProbe
from tests.unit.accounts.test_tdata import KEY, make_tdata
from tests.unit.shared.test_settings import MIN_ENV

FERNET = "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg="


class AnyPhoneProbe(FakeProbe):
    async def phone(self, session, api_id, api_hash, device):
        self.calls.append(("phone", StringSession(session).auth_key.key == KEY))
        return "79001112233"


def container():
    c = Container()
    c.settings.override(providers.Object(Settings(_env_file=None, **{**MIN_ENV, "BOT_TOKEN": "42:TESTTOKEN",
                                                                     "USERBOT_STORE_KEY": FERNET})))
    repo, probe = InMemoryAccountRepository(), AnyPhoneProbe()
    c.account_repo.override(providers.Object(repo))
    c.session_probe.override(providers.Object(probe))
    return c, repo, probe


async def test_cli_imports_tdata(tmp_path, capsys):
    make_tdata(tmp_path / "acc" / "tdata", passcode="42")
    c, repo, probe = container()
    assert await run(["accounts", "import-tdata", str(tmp_path / "acc"), "--passcode", "42"], c) == 0
    [acc] = await repo.list_all()
    assert acc.phone == "+79001112233" and acc.api_id == 2040 and acc.status.value == "active"
    assert StringSession(FernetSecretBox(FERNET).decrypt(acc.session_enc)).auth_key.key == KEY
    assert ("phone", True) in probe.calls
    assert "+79001112233: active" in capsys.readouterr().out


async def test_cli_tdata_errors_are_readable(tmp_path, capsys):
    make_tdata(tmp_path / "tdata", passcode="42")
    c, repo, _ = container()
    assert await run(["accounts", "import-tdata", str(tmp_path / "tdata")], c) == 1
    assert "--passcode" in capsys.readouterr().err and await repo.list_all() == []
