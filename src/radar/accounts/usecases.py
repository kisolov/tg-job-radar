"""Входы в операции с аккаунтами (CLI, бот)."""
from __future__ import annotations

import json
import logging
import random
import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from radar.accounts.entities import Account, AccountStatus, DeviceProfile, Pacer, PacingPolicy
from radar.accounts.ports import AccountRepository, DeviceProfileProvider, SecretBox, SessionProbe, TdataReader
from radar.accounts.service import AccountService
from radar.shared.clock import Clock

logger = logging.getLogger(__name__)


class InvalidAccountPayload(ValueError):
    pass


class ImportAccount:
    """Из файла аккаунта берутся только phone, сессия и app_id/app_hash.

    Остальное (2FA-пароль, device_secret/device_token, поля устройства) намеренно не читается:
    пара «сессия + 2FA» в БД даёт полный захват аккаунта при утечке.
    Повторный импорт того же номера обновляет сессию (перелогин после `unauthorized`).
    """

    def __init__(
        self, accounts: AccountRepository, probe: SessionProbe, devices: DeviceProfileProvider,
        box: SecretBox, clock: Clock, default_device_profile: str,
        join_policy: PacingPolicy, resolve_policy: PacingPolicy, rng: random.Random | None = None,
    ) -> None:
        self._accounts, self._probe, self._devices, self._box = accounts, probe, devices, box
        self._clock, self._profile = clock, default_device_profile
        self._join_policy, self._resolve_policy = join_policy, resolve_policy
        self._rng = rng or random.Random()

    async def execute(self, raw: bytes) -> Account:
        try:
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidAccountPayload("Файл аккаунта — не JSON") from exc
        if not isinstance(data, dict):
            raise InvalidAccountPayload("Файл аккаунта — не JSON-объект")
        return await self.from_fields(
            phone=_required(data, "phone"), session=_required(data, "session_str", alias="session"),
            api_id=int(_required(data, "app_id")), api_hash=str(_required(data, "app_hash")),
        )

    def device(self) -> DeviceProfile:
        return self._devices.get(self._profile)

    async def from_fields(self, phone: Any, session: str, api_id: int, api_hash: str) -> Account:
        phone = _normalize_phone(phone)
        authorized = await self._probe.check(session, api_id, api_hash, self._devices.get(self._profile))
        status = AccountStatus.active if authorized else AccountStatus.unauthorized
        error = None if authorized else "Сессия недействительна или разлогинена"
        existing = await self._accounts.get_by_phone(phone)
        if existing:
            existing.api_id = api_id
            existing.api_hash_enc = self._box.encrypt(api_hash)
            existing.session_enc = self._box.encrypt(session)
            existing.status, existing.last_error, existing.status_until = status, error, None
            await self._accounts.save(existing)
            account = existing
        else:
            now = self._clock.now()
            account = Account(
                id=uuid4(), phone=phone, api_id=api_id, api_hash_enc=self._box.encrypt(api_hash),
                session_enc=self._box.encrypt(session), device_profile=self._profile,
                status=status, status_until=None, last_error=error, membership_count=0,
                join=Pacer.new(now, self._rng, self._join_policy),
                resolve=Pacer.new(now, self._rng, self._resolve_policy),
            )
            await self._accounts.add(account)
        logger.info("Аккаунт импортирован: %s → %s", phone, status.value)
        return account


class ImportTdata:
    """Папка tdata Telegram Desktop → аккаунты. Номера в tdata нет: его спрашиваем у Telegram (get_me) или берём
    из --phone (только для tdata с одним аккаунтом). Дальше — как обычный импорт (проверка, шифрование, перелогин)."""

    def __init__(self, importer: ImportAccount, reader: TdataReader, probe: SessionProbe) -> None:
        self._importer, self._reader, self._probe = importer, reader, probe

    async def execute(self, path, passcode: str | None = None, phone: str | None = None) -> list[Account]:
        sessions = await self._reader.read(path, passcode)
        if phone and len(sessions) > 1:
            raise InvalidAccountPayload(f"В tdata {len(sessions)} аккаунта — --phone подходит только для одного")
        found = []
        for s in sessions:
            number = phone or await self._probe.phone(s.session, s.api_id, s.api_hash, self._importer.device())
            if not number:
                raise InvalidAccountPayload(
                    f"Сессия аккаунта {s.user_id or '?'} не авторизована — номер не узнать; укажите --phone")
            found.append((number, s))
        return [await self._importer.from_fields(number, s.session, s.api_id, s.api_hash) for number, s in found]


class LoginAccount:
    def __init__(self, importer: ImportAccount, login_session: Callable[[str, int, str], Awaitable[str]]) -> None:
        self._importer, self._login = importer, login_session

    async def execute(self, phone: str, api_id: int, api_hash: str) -> Account:
        session = await self._login(phone, api_id, api_hash)
        return await self._importer.from_fields(phone, session, api_id, api_hash)


class ListAccounts:
    def __init__(self, accounts: AccountRepository) -> None:
        self._accounts = accounts

    async def execute(self) -> list[Account]:
        return await self._accounts.list_all()


class DisableAccount:
    def __init__(self, accounts: AccountRepository, service: AccountService) -> None:
        self._accounts, self._service = accounts, service

    async def execute(self, phone: str) -> Account | None:
        account = await self._accounts.get_by_phone(_normalize_phone(phone))
        return await self._service.disable(account.id) if account else None


def _required(payload: dict[str, Any], key: str, alias: str | None = None) -> Any:
    value = payload.get(key) or (payload.get(alias) if alias else None)
    if not value:
        raise InvalidAccountPayload(f"В файле аккаунта нет обязательного поля {key}")
    return value


def _normalize_phone(raw: Any) -> str:
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        raise InvalidAccountPayload("Поле phone не содержит цифр")
    return f"+{digits}"
