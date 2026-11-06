import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from radar.accounts.entities import Account, AccountStatus, Pacer, PacingPolicy

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
POLICY = PacingPolicy(
    daily_min=25, daily_max=30, interval_min_s=300, interval_max_s=600,
    factor=1.5, max_factor=8.0, limit_step=5, limit_floor=5, recovery_days=3,
)


def fresh(seed: int = 1) -> Pacer:
    p = Pacer.new(T0, random.Random(seed), POLICY)
    return p


def test_daily_limit_within_25_30():
    for seed in range(50):
        p = fresh(seed)
        assert 25 <= p.base_daily_limit <= 30
        assert p.daily_limit == p.base_daily_limit


def test_cannot_exceed_daily_limit():
    p = fresh()
    rng = random.Random(2)
    now = T0
    for _ in range(p.daily_limit):
        assert p.can_act(now)
        p.record_action(now, rng, POLICY)
        now = p.next_allowed_at
    assert not p.can_act(now + timedelta(hours=1))
    tomorrow = datetime(2026, 11, 5, 0, 1, tzinfo=UTC)
    p.roll_day(tomorrow, rng, POLICY)
    assert p.can_act(tomorrow) and p.done_today == 0


def test_interval_respected():
    p = fresh()
    p.record_action(T0, random.Random(3), POLICY)
    assert not p.can_act(T0 + timedelta(seconds=299))
    assert p.can_act(T0 + timedelta(seconds=600))


def test_flood_throttles():
    p = fresh()
    base = p.base_daily_limit
    p.record_flood(T0, 120, POLICY)
    assert p.interval_factor == 1.5
    assert p.daily_limit == base - 5
    assert not p.can_act(T0 + timedelta(seconds=119))
    assert p.can_act(T0 + timedelta(seconds=120))
    p.record_action(T0 + timedelta(seconds=120), random.Random(4), POLICY)
    assert p.next_allowed_at >= T0 + timedelta(seconds=120 + 300 * 1.5)


def test_flood_floor_and_cap():
    p = fresh()
    for i in range(10):
        p.record_flood(T0 + timedelta(seconds=i), 10, POLICY)
    assert p.interval_factor == 8.0
    assert p.daily_limit == 5


def test_recovery_after_quiet_days():
    p = fresh()
    rng = random.Random(5)
    p.record_flood(T0, 60, POLICY)
    p.record_flood(T0, 60, POLICY)  # factor 2.25, deficit 10
    day = lambda n: datetime(2026, 11, 4 + n, 0, 5, tzinfo=UTC)  # noqa: E731
    p.roll_day(day(1), rng, POLICY)
    p.roll_day(day(2), rng, POLICY)
    assert p.interval_factor == 2.25  # ещё нет 3 суток тишины
    assert p.daily_limit == p.base_daily_limit - 10
    p.roll_day(day(3), rng, POLICY)
    assert p.interval_factor == 1.5
    assert p.daily_limit == p.base_daily_limit - 5
    p.roll_day(day(4), rng, POLICY)
    assert p.interval_factor == 1.0
    assert p.daily_limit == p.base_daily_limit
    p.roll_day(day(5), rng, POLICY)
    assert p.interval_factor == 1.0 and p.daily_limit == p.base_daily_limit


def test_unlimited_pacer_ignores_daily_limit():
    p = Pacer.new(T0, random.Random(1), POLICY, unlimited=True)
    rng = random.Random(1)
    now = T0
    for _ in range(100):
        p.record_action(now, rng, POLICY)
        now = p.next_allowed_at
    assert p.can_act(now)


def _account(**kw) -> Account:
    a = Account(
        id=uuid4(), phone="+1", api_id=1, api_hash_enc="h", session_enc="s",
        device_profile="default", status=AccountStatus.active, status_until=None,
        last_error=None, membership_count=0, join=fresh(), resolve=fresh(), version=0,
    )
    return replace(a, **kw)


def test_banned_cannot_join():
    assert _account().can_join(T0, cap=500)
    assert not _account(status=AccountStatus.banned).can_join(T0, cap=500)
    assert not _account(status=AccountStatus.flood_wait).can_resolve(T0)


def test_membership_cap_blocks_join():
    assert not _account(membership_count=500).can_join(T0, cap=500)
    assert _account(membership_count=499).can_join(T0, cap=500)
