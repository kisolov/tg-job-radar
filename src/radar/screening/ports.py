from dataclasses import dataclass
from datetime import date
from typing import Protocol

from radar.findings.entities import Classification


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.prompt_tokens + other.prompt_tokens, self.completion_tokens + other.completion_tokens)


class LlmUnavailable(Exception):
    """LLM не ответил осмысленно (сеть, 5xx, мусор после повтора). Пакет остаётся pending.
    spent — токены, уже оплаченные неудачными попытками (I4: идут в дневной расход)."""

    def __init__(self, message: str = "", spent: "Usage | None" = None) -> None:
        super().__init__(message)
        self.spent = spent or Usage()


class LlmClassifier(Protocol):
    async def classify(
        self, items: list[tuple[str, str]], requirements: str, *, model: str | None = None,
        max_chars: int | None = None,
    ) -> tuple[dict[str, Classification], Usage]:
        """items: (id, text). Отсутствующие в ответе id в словарь не попадают."""


COUNTERS = ("read", "passed_prefilter", "llm_items", "findings")


@dataclass
class DailyStats:
    day: date
    read: int = 0
    passed_prefilter: int = 0
    llm_items: int = 0
    findings: int = 0
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reserved: int = 0


class UsageRepository(Protocol):
    async def reserve(self, day: date, estimated_tokens: int, limit: int) -> bool:
        """Атомарно: факт + резерв + оценка ≤ limit → резерв растёт, True (R8)."""

    async def commit_usage(self, day: date, reserved: int, usage: Usage) -> None:
        """Снять резерв, прибавить фактический расход и +1 запрос."""

    async def release(self, day: date, reserved: int) -> None: ...
    async def bump(self, day: date, **counters: int) -> None:
        """Атомарный инкремент счётчиков из COUNTERS."""

    async def get(self, day: date) -> DailyStats: ...


class RequirementsRepository(Protocol):
    async def current(self) -> tuple[int, str]: ...
    async def set(self, text: str) -> int: ...
