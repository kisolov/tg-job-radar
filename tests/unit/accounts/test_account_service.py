import random
from datetime import timedelta

from radar.accounts.adapters.alerts import RecordingAlertSink
from radar.accounts.adapters.memory_repo import InMemoryAccountRepository
from radar.accounts.entities import AccountStatus
from radar.accounts.ports import StaleAccount
from radar.accounts.service import AccountService
from tests.factories import JOIN_POLICY, RESOLVE_POLICY, make_account


def make_service(repo, clock, alerts=None):
    return AccountService(
        accounts=repo, alerts=alerts or RecordingAlertSink(), clock=clock, rng=random.Random(7),
        join_policy=JOIN_POLICY, resolve_policy=RESOLVE_POLICY,
    )


async def test_ban_alerts_once(clock):
    repo, alerts = InMemoryAccountRepository(), RecordingAlertSink()
    a = make_account(phone="+79990001122")
    await repo.add(a)
    svc = make_service(repo, clock, alerts)
    await svc.mark_failed(a.id, AccountStatus.banned, "UserDeactivatedBanError")
    await svc.mark_failed(a.id, AccountStatus.banned, "UserDeactivatedBanError")
    got = await repo.get(a.id)
    assert got.status is AccountStatus.banned and got.last_error == "UserDeactivatedBanError"
    assert len(alerts.sent) == 1 and "+79990001122" in alerts.sent[0]


async def test_flood_over_hour_alerts(clock):
    repo, alerts = InMemoryAccountRepository(), RecordingAlertSink()
    a = make_account()
    await repo.add(a)
    svc = make_service(repo, clock, alerts)
    await svc.apply_flood(a.id, "join", 120)
    assert alerts.sent == []
    got = await repo.get(a.id)
    assert got.status is AccountStatus.active and got.join.interval_factor == 1.5
    await svc.apply_flood(a.id, "resolve", 7200)
    got = await repo.get(a.id)
    assert got.status is AccountStatus.flood_wait
    assert got.status_until == clock.now() + timedelta(seconds=7200)
    assert got.resolve.interval_factor == 1.5 and len(alerts.sent) == 1


async def test_flood_wait_expires(clock):
    repo = InMemoryAccountRepository()
    a = make_account()
    await repo.add(a)
    svc = make_service(repo, clock)
    await svc.apply_flood(a.id, "join", 7200)
    clock.advance(7199)
    await svc.wake_expired()
    assert (await repo.get(a.id)).status is AccountStatus.flood_wait
    clock.advance(1)
    await svc.wake_expired()
    assert (await repo.get(a.id)).status is AccountStatus.active


async def test_record_action_counts_join(clock):
    repo = InMemoryAccountRepository()
    a = make_account()
    await repo.add(a)
    svc = make_service(repo, clock)
    await svc.record_action(a.id, "join")
    got = await repo.get(a.id)
    assert got.join.done_today == 1 and not got.join.can_act(clock.now())


class FlakyRepo(InMemoryAccountRepository):
    """Первый save проигрывает гонку, как при параллельной записи другой корутиной."""

    def __init__(self) -> None:
        super().__init__()
        self.failures = 1

    async def save(self, account):
        if self.failures:
            self.failures -= 1
            raise StaleAccount(account.id)
        await super().save(account)


async def test_retries_on_stale_version(clock):
    repo = FlakyRepo()
    a = make_account()
    await repo.add(a)
    await make_service(repo, clock).record_action(a.id, "join")
    assert (await repo.get(a.id)).join.done_today == 1
