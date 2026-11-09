import json
import logging

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from radar.accounts.adapters.device_profiles import DefaultDeviceProfileProvider
from radar.accounts.adapters.fernet_box import FernetSecretBox
from radar.accounts.adapters.memory_repo import InMemoryAccountRepository
from radar.accounts.adapters.sqlalchemy_repo import SqlAlchemyAccountRepository
from radar.accounts.entities import AccountStatus, DeviceProfile
from radar.accounts.usecases import ImportAccount, InvalidAccountPayload, LoginAccount
from tests.factories import JOIN_POLICY, RESOLVE_POLICY

KEY = Fernet.generate_key().decode()
SESSION = "1BVtsOK8Bu-plain-session-string"


class FakeProbe:
    def __init__(self, authorized: bool = True) -> None:
        self.authorized = authorized
        self.calls: list[tuple] = []
        self.phones: dict[str, str] = {}  # session → номер, который «вернёт Telegram»

    async def check(self, session: str, api_id: int, api_hash: str, device: DeviceProfile) -> bool:
        self.calls.append((session, api_id, api_hash))
        return self.authorized

    async def phone(self, session: str, api_id: int, api_hash: str, device: DeviceProfile) -> str | None:
        return self.phones.get(session)


def make_import(repo, probe, clock, box=None):
    return ImportAccount(
        accounts=repo, probe=probe, devices=DefaultDeviceProfileProvider(),
        box=box or FernetSecretBox(KEY), clock=clock, default_device_profile="default",
        join_policy=JOIN_POLICY, resolve_policy=RESOLVE_POLICY,
    )


def payload(**extra) -> bytes:
    return json.dumps({"phone": "+7 (900) 111-22-33", "session_str": SESSION,
                       "app_id": 2040, "app_hash": "b18441a1ff607e10a989891a5462e627", **extra}).encode()


async def test_import_takes_only_allowed_fields(caplog, clock):
    caplog.set_level(logging.DEBUG)
    repo = InMemoryAccountRepository()
    account = await make_import(repo, FakeProbe(), clock).execute(
        payload(twoFA="hunter2-secret", device_secret="dev-secret-xyz", device="iPhone 15")
    )
    assert account.phone == "+79001112233" and account.status is AccountStatus.active
    stored = await repo.get(account.id)
    blob = repr(stored) + caplog.text
    for leaked in ("hunter2-secret", "dev-secret-xyz", "iPhone 15", SESSION):
        assert leaked not in blob
    assert FernetSecretBox(KEY).decrypt(stored.session_enc) == SESSION
    assert 25 <= stored.join.daily_limit <= 30


async def test_session_alias_and_missing_field(clock):
    repo = InMemoryAccountRepository()
    data = json.loads(payload())
    data["session"] = data.pop("session_str")
    await make_import(repo, FakeProbe(), clock).execute(json.dumps(data).encode())
    with pytest.raises(InvalidAccountPayload):
        await make_import(repo, FakeProbe(), clock).execute(b'{"phone": "+1"}')
    with pytest.raises(InvalidAccountPayload):
        await make_import(repo, FakeProbe(), clock).execute(b"not json")


async def test_unauthorized_session_saved_as_unauthorized(clock):
    repo = InMemoryAccountRepository()
    account = await make_import(repo, FakeProbe(authorized=False), clock).execute(payload())
    assert account.status is AccountStatus.unauthorized
    assert await repo.list_active() == []


async def test_reimport_same_phone_refreshes_session(clock):
    repo = InMemoryAccountRepository()
    first = await make_import(repo, FakeProbe(authorized=False), clock).execute(payload())
    second = await make_import(repo, FakeProbe(), clock).execute(payload())
    assert second.id == first.id and second.status is AccountStatus.active
    assert len(await repo.list_all()) == 1


async def test_login_uses_interactive_session(clock):
    repo = InMemoryAccountRepository()
    asked = []

    async def login_session(phone, api_id, api_hash):
        asked.append(phone)
        return SESSION

    login = LoginAccount(make_import(repo, FakeProbe(), clock), login_session)
    account = await login.execute("+79001112233", 2040, "hash")
    assert asked == ["+79001112233"] and account.status is AccountStatus.active


async def test_secrets_encrypted_at_rest(pg_sessionmaker, clock):
    repo = SqlAlchemyAccountRepository(pg_sessionmaker)
    await make_import(repo, FakeProbe(), clock).execute(payload())
    async with pg_sessionmaker() as s:
        row = (await s.execute(text("SELECT * FROM accounts"))).mappings().one()
    dump = " ".join(str(v) for v in row.values())
    assert SESSION not in dump
    assert "b18441a1ff607e10a989891a5462e627" not in dump


def test_secret_box_roundtrip_and_wrong_key():
    box = FernetSecretBox(KEY)
    token = box.encrypt("x")
    assert box.decrypt(token) == "x"
    with pytest.raises(ValueError) as e:
        FernetSecretBox(Fernet.generate_key().decode()).decrypt(token)
    assert KEY not in str(e.value)


def test_default_device_profile_passes_no_fields():
    assert DefaultDeviceProfileProvider().get("default").as_client_kwargs() == {}


async def test_imported_account_has_daily_resolve_limit(clock):
    """I1: ResolveUsername у Telegram лимитирован в сутки — резолв не безлимитный."""
    acc = await make_import(InMemoryAccountRepository(), FakeProbe(), clock).execute(payload())
    assert not acc.resolve.unlimited and acc.resolve.daily_limit >= RESOLVE_POLICY.daily_min
