"""Решение «тратить ли LLM»: оценка пакета и дневной бюджет (R8)."""
from datetime import date

from radar.accounts.ports import AlertSink
from radar.screening.ports import UsageRepository
from radar.shared.clock import Clock

SYSTEM_PROMPT_TOKENS = 400
CHARS_PER_TOKEN = 3


class ScreeningService:
    def __init__(self, usage: UsageRepository, alerts: AlertSink, clock: Clock) -> None:
        self._usage, self._alerts, self._clock = usage, alerts, clock
        self._alerted_on: date | None = None

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
