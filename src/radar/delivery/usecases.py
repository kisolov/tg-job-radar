"""Операции бота управления и правка карточек. Сервиса нет: usecase работает с портами напрямую."""
import logging
from collections import Counter
from collections.abc import Callable

from radar.accounts.ports import AccountRepository
from radar.delivery.ports import Notifier
from radar.findings.entities import Copy, Finding, FindingStatus
from radar.findings.events import CopyAttached
from radar.findings.ports import FindingRepository
from radar.screening.ports import RequirementsRepository, UsageRepository
from radar.shared.clock import Clock
from radar.shared.runtime import RuntimeConfig
from radar.sources.ports import SourceRepository

logger = logging.getLogger(__name__)
SOURCES_PAGE = 20


class StatusReport:
    def __init__(self, accounts: AccountRepository, sources: SourceRepository, usage: UsageRepository,
                 runtime: RuntimeConfig, clock: Clock) -> None:
        self._accounts, self._sources, self._usage, self._runtime, self._clock = accounts, sources, usage, runtime, clock

    async def execute(self) -> str:
        accounts = Counter(a.status.value for a in await self._accounts.list_all())
        sources = {k.value: v for k, v in (await self._sources.count_by_status()).items()}
        day = self._clock.now().date()
        st = await self._usage.get(day)
        s = self._runtime.settings
        cost = (st.prompt_tokens * s.LLM_PRICE_PER_1K_PROMPT + st.completion_tokens * s.LLM_PRICE_PER_1K_COMPLETION) / 1000
        paused = " ⏸ доставка на паузе" if await self._runtime.paused() else ""
        fmt = lambda c: ", ".join(f"{k}: {v}" for k, v in sorted(c.items())) or "—"  # noqa: E731
        return (
            f"📊 Статус{paused}\n"
            f"Аккаунты — {fmt(accounts)}\n"
            f"Источники — {fmt(sources)}\n"
            f"За {day:%d.%m} (UTC): прочитано {st.read}, предфильтр {st.passed_prefilter}, "
            f"в LLM {st.llm_items}, находок {st.findings}\n"
            f"LLM: {st.requests} запросов, токены {st.prompt_tokens}+{st.completion_tokens} "
            f"из {self._runtime.get('LLM_DAILY_TOKEN_LIMIT')}, ≈{cost:.2f}; модель {self._runtime.get('NEUROAPI_MODEL')}"
        )


class ListSources:
    def __init__(self, sources: SourceRepository) -> None:
        self._sources = sources

    async def execute(self, page: int = 1) -> str:
        page = max(1, page)
        rows = await self._sources.top(SOURCES_PAGE, (page - 1) * SOURCES_PAGE)
        if not rows:
            return "Пусто."
        lines = [f"Источники по находкам, стр. {page}:"]
        for i, s in enumerate(rows, start=(page - 1) * SOURCES_PAGE + 1):
            kind = "👥" if s.kind and s.kind.value == "group" else "📢"
            lines.append(f"{i}. {kind} {s.title or s.ref} (@{s.ref}) — {s.found_count}")
        return "\n".join(lines)


class ShowRequirements:
    def __init__(self, requirements: RequirementsRepository) -> None:
        self._req = requirements

    async def execute(self) -> tuple[int, str]:
        return await self._req.current()


class SetRequirements:
    def __init__(self, requirements: RequirementsRepository) -> None:
        self._req = requirements

    async def execute(self, text: str) -> int:
        text = text.strip()
        if not text:
            raise ValueError("Пустые требования")
        return await self._req.set(text)


class SetPaused:
    def __init__(self, runtime: RuntimeConfig) -> None:
        self._runtime = runtime

    async def execute(self, paused: bool) -> None:
        await self._runtime.set_paused(paused)


class SetOverride:
    def __init__(self, runtime: RuntimeConfig) -> None:
        self._runtime = runtime

    async def execute(self, key: str, raw: str) -> object:
        return await self._runtime.set(key, raw)


class AttachCopyEdit:
    """Потребитель CopyAttached: карточка отправленной находки правится до текущего списка копий (R9)."""

    def __init__(self, findings: FindingRepository, notifier: Notifier,
                 render: Callable[[Finding, list[Copy]], str]) -> None:
        self._findings, self._notifier, self._render = findings, notifier, render

    async def execute(self, event: CopyAttached) -> bool:
        f = await self._findings.get(event.finding_id)
        if f is None or f.status is not FindingStatus.delivered or f.bot_message_id is None:
            return False
        await self._notifier.edit(f.bot_message_id, self._render(f, await self._findings.copies(f.id)))
        return True
