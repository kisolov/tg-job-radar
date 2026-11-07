from dataclasses import asdict
from datetime import date, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from radar.accounts.entities import Account, AccountStatus, Pacer
from radar.accounts.ports import AccountExists, StaleAccount
from radar.shared.db import SessionFactory, transaction
from radar.shared.models import accounts as t


def pacer_to_json(p: Pacer) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in asdict(p).items():
        out[k] = v.isoformat() if isinstance(v, (date, datetime)) else v
    return out


def pacer_from_json(d: dict[str, Any]) -> Pacer:
    def ts(v: str | None) -> datetime | None:
        return datetime.fromisoformat(v) if v else None

    return Pacer(
        daily_limit=d["daily_limit"], base_daily_limit=d["base_daily_limit"],
        day=date.fromisoformat(d["day"]), next_allowed_at=ts(d["next_allowed_at"]),
        interval_factor=d["interval_factor"], done_today=d["done_today"],
        last_flood_at=ts(d["last_flood_at"]), last_recovery_at=ts(d["last_recovery_at"]),
        unlimited=d["unlimited"],
    )


def _values(a: Account) -> dict[str, Any]:
    return dict(
        phone=a.phone, api_id=a.api_id, api_hash_enc=a.api_hash_enc, session_enc=a.session_enc,
        device_profile=a.device_profile, status=a.status.value, status_until=a.status_until,
        last_error=a.last_error, membership_count=a.membership_count, external_memberships=a.external_memberships,
        join_state=pacer_to_json(a.join), resolve_state=pacer_to_json(a.resolve),
    )


def _row(r: sa.Row) -> Account:
    return Account(
        id=r.id, phone=r.phone, api_id=r.api_id, api_hash_enc=r.api_hash_enc,
        session_enc=r.session_enc, device_profile=r.device_profile,
        status=AccountStatus(r.status), status_until=r.status_until, last_error=r.last_error,
        membership_count=r.membership_count, join=pacer_from_json(r.join_state),
        resolve=pacer_from_json(r.resolve_state), version=r.version, created_at=r.created_at,
        external_memberships=r.external_memberships,
    )


class SqlAlchemyAccountRepository:
    def __init__(self, sf: SessionFactory) -> None:
        self._sf = sf

    async def add(self, account: Account) -> None:
        try:
            async with transaction(self._sf) as s:
                await s.execute(t.insert().values(id=account.id, version=account.version, **_values(account)))
        except IntegrityError as exc:
            raise AccountExists(account.phone) from exc

    async def _one(self, where) -> Account | None:
        async with self._sf() as s:
            r = (await s.execute(sa.select(t).where(where))).first()
        return _row(r) if r else None

    async def get(self, account_id: UUID) -> Account | None:
        return await self._one(t.c.id == account_id)

    async def get_by_phone(self, phone: str) -> Account | None:
        return await self._one(t.c.phone == phone)

    async def list_active(self) -> list[Account]:
        async with self._sf() as s:
            rows = (await s.execute(
                sa.select(t).where(t.c.status == AccountStatus.active.value).order_by(t.c.created_at)
            )).all()
        return [_row(r) for r in rows]

    async def list_all(self) -> list[Account]:
        async with self._sf() as s:
            rows = (await s.execute(sa.select(t).order_by(t.c.created_at))).all()
        return [_row(r) for r in rows]

    async def save(self, account: Account) -> None:
        async with transaction(self._sf) as s:
            res = await s.execute(
                t.update()
                .where(t.c.id == account.id, t.c.version == account.version)
                .values(version=t.c.version + 1, updated_at=sa.func.now(), **_values(account))
            )
        if res.rowcount != 1:
            raise StaleAccount(account.id)
        account.version += 1
