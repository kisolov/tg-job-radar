"""Входы: сообщение → кластер находки; доставка принятых находок; возврат зависших claim'ов."""
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from radar.delivery.ports import Notifier
from radar.findings.entities import Copy, Finding, FindingStatus
from radar.findings.events import CopyAttached, EventBus
from radar.findings.ports import FindingRepository
from radar.findings.service import FindingService
from radar.ingest.ports import IncomingMessage
from radar.screening.ports import UsageRepository
from radar.screening.prefilter import PrefilterConfig, prefilter
from radar.shared.clock import Clock

logger = logging.getLogger(__name__)

DELIVER_BATCH = 50
Render = Callable[[Finding, list[Copy]], str]


class ClusterMessage:
    """MessageSink конвейера: предфильтр → кластер дублей (до LLM: не платить за копии)."""

    def __init__(self, service: FindingService, prefilter_config: Callable[[], PrefilterConfig], bus: EventBus,
                 stats: UsageRepository, clock: Clock) -> None:
        self._service, self._cfg, self._bus, self._stats, self._clock = service, prefilter_config, bus, stats, clock

    async def submit(self, msg: IncomingMessage) -> None:
        day = self._clock.now().date()
        verdict = prefilter(msg.text, self._cfg())
        if verdict != "pass":
            await self._stats.bump(day, read=1)
            return
        await self._stats.bump(day, read=1, passed_prefilter=1)
        finding, new = await self._service.cluster(msg)
        if not new and finding.status is FindingStatus.delivered:
            self._bus.publish(CopyAttached(finding.id))


class DeliverAccepted:
    """Каждая принятая находка — одна карточка (R1): claim до отправки, при сбое отправки — снять claim."""

    def __init__(self, repo: FindingRepository, notifier: Notifier, render: Render,
                 paused: Callable[[], Awaitable[bool]], stats: UsageRepository, clock: Clock) -> None:
        self._repo, self._notifier, self._render = repo, notifier, render
        self._paused, self._stats, self._clock = paused, stats, clock

    async def execute(self) -> int:
        if await self._paused():
            return 0
        sent = 0
        for finding in await self._repo.accepted(DELIVER_BATCH):
            if not await self._repo.claim(finding.id, self._clock.now()):
                continue
            copies = await self._repo.copies(finding.id)
            try:
                message_id = await self._notifier.send(self._render(finding, copies))
            except Exception:
                logger.exception("Не удалось отправить находку %s, вернём в очередь", finding.id)
                await self._repo.unclaim(finding.id)
                continue
            await self._repo.mark_delivered(finding.id, message_id, self._clock.now())
            await self._stats.bump(self._clock.now().date(), findings=1)
            sent += 1
            # копии, пришедшие, пока карточка уходила, события не породили (статус был delivering) — догоняем
            late = await self._repo.copies(finding.id)
            if len(late) > len(copies):
                try:
                    await self._notifier.edit(message_id, self._render(finding, late))
                except Exception:
                    logger.exception("Не удалось дописать копии в карточку %s", finding.id)
        return sent


class RedeliverStale:
    """claim без отправки старше stale_s (процесс упал между claim и send) → снова accepted."""

    def __init__(self, repo: FindingRepository, clock: Clock, stale_s: float) -> None:
        self._repo, self._clock, self._stale = repo, clock, timedelta(seconds=stale_s)

    async def execute(self) -> int:
        stale = await self._repo.stale_claims(self._clock.now() - self._stale)
        for f in stale:
            await self._repo.unclaim(f.id)
        return len(stale)
