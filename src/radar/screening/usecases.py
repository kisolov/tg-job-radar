"""Входы в отбор: пакетная классификация кластеров, проба модели."""
import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from importlib import resources

from radar.findings.ports import FindingRepository
from radar.screening.ports import LlmClassifier, LlmUnavailable, RequirementsRepository, Usage, UsageRepository
from radar.screening.service import ScreeningService
from radar.shared.clock import Clock
from radar.shared.runtime import RuntimeConfig
from radar.sources.ports import SourceRepository

logger = logging.getLogger(__name__)
OUTAGE_PAUSE_S = 60
IDLE_S = 5


class ClassifyPending:
    """Пакет pending-кластеров → LLM. Пакет уходит, когда набралось LLM_BATCH_SIZE или самый старый
    ждёт дольше LLM_BATCH_WAIT_S. Настройки читаются на каждом шаге (меняются через /set)."""

    def __init__(self, findings: FindingRepository, classifier: LlmClassifier, screening: ScreeningService,
                 requirements: RequirementsRepository, usage: UsageRepository, sources: SourceRepository,
                 runtime: RuntimeConfig, clock: Clock, on_accepted: Callable[[], Awaitable[None]],
                 sleep: Callable[[float], Awaitable[None]] | None = None) -> None:
        self._findings, self._classifier, self._screening = findings, classifier, screening
        self._requirements, self._usage, self._sources = requirements, usage, sources
        self._runtime, self._clock, self._on_accepted = runtime, clock, on_accepted
        self._sleep = sleep or asyncio.sleep

    async def step(self) -> int:
        """→ сколько кластеров классифицировано. LlmUnavailable пробрасывается (кластеры остаются pending)."""
        size = self._runtime.get("LLM_BATCH_SIZE")
        batch = await self._findings.pending(size)
        if not batch:
            return 0
        now = self._clock.now()
        oldest = await self._findings.oldest_pending_at()
        if len(batch) < size and oldest and oldest > now - timedelta(seconds=self._runtime.get("LLM_BATCH_WAIT_S")):
            return 0
        max_chars = self._runtime.get("LLM_MAX_CHARS")
        items = [(str(f.id), f.text_snapshot) for f in batch]
        reserved = await self._screening.reserve([t[:max_chars] for _, t in items],
                                                 self._runtime.get("LLM_DAILY_TOKEN_LIMIT"))
        if reserved is None:
            return 0
        day = now.date()
        version, text = await self._requirements.current()
        try:
            results, usage = await self._classifier.classify(
                items, text, model=self._runtime.get("NEUROAPI_MODEL"), max_chars=max_chars)
        except BaseException:
            await self._usage.release(day, reserved)
            raise
        await self._usage.commit_usage(day, reserved, usage)
        await self._usage.bump(day, llm_items=len(items))
        accepted = 0
        for f in batch:
            cls = results.get(str(f.id))
            if cls is None or not await self._findings.set_classification(f.id, cls, version):
                continue
            if cls.relevant:
                accepted += 1
                for source_id in {c.source_id for c in await self._findings.copies(f.id)}:
                    await self._sources.add_found(source_id)
        if accepted:
            await self._on_accepted()
        return len(results)

    async def run_forever(self) -> None:
        while True:
            try:
                n = await self.step()
            except LlmUnavailable as exc:
                logger.warning("LLM недоступен (%s), пауза %s с", exc, OUTAGE_PAUSE_S)
                await self._sleep(OUTAGE_PAUSE_S)
                continue
            await self._sleep(0 if n else IDLE_S)


def load_probe_samples() -> list[dict]:
    return json.loads(resources.files("radar.screening").joinpath("probe_samples.json").read_text("utf-8"))


@dataclass
class ProbeResult:
    model: str
    correct: int
    total: int
    wrong: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


class ProbeModel:
    """6 эталонных сообщений (3 подходят, 3 нет) одним пакетом — как в бою."""

    def __init__(self, classifier: LlmClassifier, requirements: RequirementsRepository) -> None:
        self._classifier, self._requirements = classifier, requirements

    async def execute(self, model: str) -> ProbeResult:
        samples = load_probe_samples()
        _, req = await self._requirements.current()
        results, usage = await self._classifier.classify([(s["id"], s["text"]) for s in samples], req, model=model)
        wrong = [s["id"] for s in samples if s["id"] not in results or results[s["id"]].relevant != s["relevant"]]
        return ProbeResult(model, len(samples) - len(wrong), len(samples), wrong, usage)
