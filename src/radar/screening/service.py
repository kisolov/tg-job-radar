"""Решение «тратить ли LLM»: оценка пакета и дневной бюджет (R8)."""
from datetime import date, datetime

from radar.accounts.ports import AlertSink
from radar.screening.ports import UsageRepository
from radar.shared.clock import Clock

SYSTEM_PROMPT_TOKENS = 400
CHARS_PER_TOKEN = 3


OUTAGE_ALERT_S = 3600


class ScreeningService:
    def __init__(self, usage: UsageRepository, alerts: AlertSink, clock: Clock) -> None:
        self._usage, self._alerts, self._clock = usage, alerts, clock
        self._alerted_on: date | None = None
        self._outage_alerted_on: date | None = None

    async def outage(self, since: datetime, error: str) -> None:
        """LLM недоступен с `since`: дольше часа — алерт владельцу, не чаще раза в сутки (I4)."""
        now = self._clock.now()
        if (now - since).total_seconds() < OUTAGE_ALERT_S or self._outage_alerted_on == now.date():
            return
        self._outage_alerted_on = now.date()
        await self._alerts.notify(
            f"⚠️ LLM недоступен {int((now - since).total_seconds() // 60)} мин ({error}). "
            "Находки копятся в очереди; проверьте NEUROAPI_KEY / баланс / NEUROAPI_MODEL.")

    def estimate(self, texts: list[str]) -> int:
        return sum(len(t) for t in texts) // CHARS_PER_TOKEN + SYSTEM_PROMPT_TOKENS

    async def reserve(self, texts: list[str], limit: int) -> int | None:
        """Зарезервировать оценку пакета в дневном бюджете. None — лимит исчерпан (алерт раз в сутки)."""
        day = self._clock.now().date()
        estimated = self.estimate(texts)
        if await self._usage.reserve(day, estimated, limit):
            return estimated
        if self._alerted_on != day:
            self._alerted_on = day
            await self._alerts.notify(
                f"⏸ Дневной лимит LLM исчерпан ({limit} токенов). Отбор на паузе до конца суток UTC; "
                "поднять: /set LLM_DAILY_TOKEN_LIMIT <число>")
        return None
