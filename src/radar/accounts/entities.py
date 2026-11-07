"""Аккаунт-читатель и его темп (R4, R5, R6 живут в корне Account)."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from uuid import UUID


class AccountStatus(str, Enum):
    active = "active"
    flood_wait = "flood_wait"
    banned = "banned"
    unauthorized = "unauthorized"
    disabled = "disabled"


@dataclass(frozen=True)
class DeviceProfile:
    device_model: str | None = None
    system_version: str | None = None
    app_version: str | None = None
    lang_code: str | None = None
    system_lang_code: str | None = None

    def as_client_kwargs(self) -> dict[str, str]:
        # Не заданное поле не передаём вовсе — иначе Telethon затрёт свой дефолт значением None.
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass(frozen=True)
class PacingPolicy:
    daily_min: int
    daily_max: int
    interval_min_s: float
    interval_max_s: float
    factor: float
    max_factor: float
    limit_step: int
    limit_floor: int
    recovery_days: int

    @classmethod
    def join_from_settings(cls, s) -> PacingPolicy:
        return cls(
            daily_min=s.JOIN_DAILY_MIN, daily_max=s.JOIN_DAILY_MAX,
            interval_min_s=s.JOIN_INTERVAL_MIN_S, interval_max_s=s.JOIN_INTERVAL_MAX_S,
            factor=s.THROTTLE_FACTOR, max_factor=s.THROTTLE_MAX_FACTOR,
            limit_step=s.THROTTLE_LIMIT_STEP, limit_floor=s.THROTTLE_LIMIT_FLOOR,
            recovery_days=s.THROTTLE_RECOVERY_DAYS,
        )

    @classmethod
    def resolve_from_settings(cls, s) -> PacingPolicy:
        return cls(
            daily_min=s.RESOLVE_DAILY_MIN, daily_max=s.RESOLVE_DAILY_MAX,
            interval_min_s=s.RESOLVE_INTERVAL_S, interval_max_s=s.RESOLVE_INTERVAL_S,
            factor=s.THROTTLE_FACTOR, max_factor=s.THROTTLE_MAX_FACTOR,
            limit_step=s.THROTTLE_LIMIT_STEP, limit_floor=s.THROTTLE_LIMIT_FLOOR,
            recovery_days=s.THROTTLE_RECOVERY_DAYS,
        )


@dataclass
class Pacer:
    """Темп одного вида действий аккаунта: суточный лимит + интервал, автоторможение на FloodWait."""

    daily_limit: int
    base_daily_limit: int
    day: date
    next_allowed_at: datetime
    interval_factor: float = 1.0
    done_today: int = 0
    last_flood_at: datetime | None = None
    last_recovery_at: datetime | None = None
    unlimited: bool = False

    @classmethod
    def new(cls, now: datetime, rng: random.Random, policy: PacingPolicy, unlimited: bool = False) -> Pacer:
        base = rng.randint(policy.daily_min, policy.daily_max)
        return cls(daily_limit=base, base_daily_limit=base, day=now.date(),
                   next_allowed_at=now, unlimited=unlimited)

    def can_act(self, now: datetime) -> bool:
        if now < self.next_allowed_at:
            return False
        if self.unlimited:
            return True
        done = 0 if now.date() != self.day else self.done_today
        return done < self.daily_limit

    def record_action(self, now: datetime, rng: random.Random, policy: PacingPolicy) -> None:
        if now.date() != self.day:
            self.roll_day(now, rng, policy)
        self.done_today += 1
        delay = rng.uniform(policy.interval_min_s, policy.interval_max_s) * self.interval_factor
        self.next_allowed_at = now + timedelta(seconds=delay)

    def record_flood(self, now: datetime, seconds: float, policy: PacingPolicy) -> None:
        self.next_allowed_at = max(self.next_allowed_at, now + timedelta(seconds=seconds))
        self.interval_factor = min(policy.max_factor, self.interval_factor * policy.factor)
        self.daily_limit = max(policy.limit_floor, self.daily_limit - policy.limit_step)
        self.last_flood_at = now

    def roll_day(self, now: datetime, rng: random.Random, policy: PacingPolicy) -> None:
        if now.date() == self.day:
            return
        deficit = max(0, self.base_daily_limit - self.daily_limit)
        self.day = now.date()
        self.done_today = 0
        self.base_daily_limit = rng.randint(policy.daily_min, policy.daily_max)
        throttled = deficit > 0 or self.interval_factor > 1.0
        if throttled and self._quiet_long_enough(now, policy):
            self.interval_factor = max(1.0, self.interval_factor / policy.factor)
            deficit = max(0, deficit - policy.limit_step)
            self.last_recovery_at = now
        self.daily_limit = max(policy.limit_floor, self.base_daily_limit - deficit)

    def _quiet_long_enough(self, now: datetime, policy: PacingPolicy) -> bool:
        if self.last_flood_at is None:
            return True
        if (now.date() - self.last_flood_at.date()).days < policy.recovery_days:
            return False
        return self.last_recovery_at is None or (now.date() - self.last_recovery_at.date()).days >= 1


@dataclass
class Account:
    id: UUID
    phone: str
    api_id: int
    api_hash_enc: str
    session_enc: str
    device_profile: str
    status: AccountStatus
    status_until: datetime | None
    last_error: str | None
    membership_count: int
    join: Pacer
    resolve: Pacer
    version: int = 0
    external_memberships: int = 0  # чаты вне учёта (узнали по ChannelsTooMuch), занимают лимит (M4)
    created_at: datetime | None = field(default=None, compare=False)

    def can_join(self, now: datetime, cap: int) -> bool:
        return (self.status is AccountStatus.active and self.membership_count + self.external_memberships < cap
                and self.join.can_act(now))

    def can_resolve(self, now: datetime) -> bool:
        return self.status is AccountStatus.active and self.resolve.can_act(now)
