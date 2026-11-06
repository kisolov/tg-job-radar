from dataclasses import replace
from datetime import date

from radar.screening.ports import COUNTERS, DailyStats, Usage
from radar.screening.requirements_default import DEFAULT_REQUIREMENTS


class InMemoryUsageRepository:
    def __init__(self) -> None:
        self.days: dict[date, DailyStats] = {}

    def _row(self, day: date) -> DailyStats:
        return self.days.setdefault(day, DailyStats(day))

    async def reserve(self, day: date, estimated_tokens: int, limit: int) -> bool:
        r = self._row(day)
        if r.prompt_tokens + r.completion_tokens + r.reserved + estimated_tokens > limit:
            return False
        r.reserved += estimated_tokens
        return True

    async def commit_usage(self, day: date, reserved: int, usage: Usage) -> None:
        r = self._row(day)
        r.reserved = max(0, r.reserved - reserved)
        r.prompt_tokens += usage.prompt_tokens
        r.completion_tokens += usage.completion_tokens
        r.requests += 1

    async def release(self, day: date, reserved: int) -> None:
        r = self._row(day)
        r.reserved = max(0, r.reserved - reserved)

    async def bump(self, day: date, **counters: int) -> None:
        bad = set(counters) - set(COUNTERS)
        if bad:
            raise ValueError(f"Неизвестные счётчики: {bad}")
        r = self._row(day)
        for k, v in counters.items():
            setattr(r, k, getattr(r, k) + v)

    async def get(self, day: date) -> DailyStats:
        return replace(self.days.get(day) or DailyStats(day))


class InMemoryRequirementsRepository:
    def __init__(self, text: str = DEFAULT_REQUIREMENTS) -> None:
        self.versions: list[str] = [text]

    async def current(self) -> tuple[int, str]:
        return len(self.versions), self.versions[-1]

    async def set(self, text: str) -> int:
        self.versions.append(text)
        return len(self.versions)

    async def seed_default(self) -> None:
        """Версия 1 создаётся в конструкторе (в SQL — миграцией)."""
