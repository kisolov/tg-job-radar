import random
from datetime import UTC, datetime
from uuid import uuid4

from radar.accounts.entities import Account, AccountStatus, Pacer, PacingPolicy

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)

JOIN_POLICY = PacingPolicy(
    daily_min=25, daily_max=30, interval_min_s=300, interval_max_s=600,
    factor=1.5, max_factor=8.0, limit_step=5, limit_floor=5, recovery_days=3,
)
RESOLVE_POLICY = PacingPolicy(
    daily_min=25, daily_max=30, interval_min_s=60, interval_max_s=60,
    factor=1.5, max_factor=8.0, limit_step=5, limit_floor=5, recovery_days=3,
)


def make_account(phone: str | None = None, **kw) -> Account:
    rng = random.Random(1)
    fields = dict(
        id=uuid4(), phone=phone or f"+7900{random.randint(0, 9_999_999):07d}", api_id=1,
        api_hash_enc="h-enc", session_enc="s-enc", device_profile="default",
        status=AccountStatus.active, status_until=None, last_error=None, membership_count=0,
        join=Pacer.new(T0, rng, JOIN_POLICY),
        resolve=Pacer.new(T0, rng, RESOLVE_POLICY, unlimited=True),
        version=0,
    )
    fields.update(kw)
    return Account(**fields)
