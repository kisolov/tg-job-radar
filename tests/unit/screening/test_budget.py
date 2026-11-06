from datetime import date

from radar.accounts.adapters.alerts import RecordingAlertSink
from radar.screening.adapters.memory_repos import InMemoryUsageRepository
from radar.screening.service import ScreeningService


def make(clock):
    usage, alerts = InMemoryUsageRepository(), RecordingAlertSink()
    return ScreeningService(usage, alerts, clock), usage, alerts


def test_estimate_tokens():
    svc = ScreeningService(InMemoryUsageRepository(), RecordingAlertSink(), None)
    assert svc.estimate(["a" * 300, "b" * 600]) == 300 + 400


async def test_reserve_within_limit(clock):
    svc, usage, alerts = make(clock)
    assert await svc.reserve(["x" * 300], limit=1000) == 500
    assert (await usage.get(clock.now().date())).reserved == 500
    assert alerts.sent == []


async def test_budget_alert_once_per_day(clock):
    svc, _, alerts = make(clock)
    assert await svc.reserve(["x" * 3000], limit=1000) is None
    assert await svc.reserve(["x" * 3000], limit=1000) is None
    assert len(alerts.sent) == 1 and "лимит" in alerts.sent[0]
    clock.advance(86400)
    assert await svc.reserve(["x" * 3000], limit=1000) is None
    assert len(alerts.sent) == 2
    assert clock.now().date() == date(2026, 11, 5)
