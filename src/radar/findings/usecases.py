"""Входы: сообщение → кластер находки; доставка принятых находок; возврат зависших claim'ов."""
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from radar.accounts.ports import AlertSink
from radar.delivery.ports import DeliveryRejected, Notifier
from radar.findings.entities import Copy, Finding, FindingStatus
from radar.findings.events import CopyAttached, EventBus
from radar.findings.ports import FindingRepository
from radar.findings.service import FindingService
from radar.ingest.ports import IncomingMessage
from radar.screening.ports import UsageRepository
from radar.screening.prefilter import PrefilterConfig, prefilter
from radar.shared.clock import Clock
from radar.sources.ports import SourceRepository

logger = logging.getLogger(__name__)

DELIVER_BATCH = 50
Render = Callable[[Finding, list[Copy]], str]


class ClusterMessage:
    """MessageSink конвейера: предфильтр → кластер дублей (до LLM: не платить за копии)."""

    def __init__(self, service: FindingService, prefilter_config: Callable[[], PrefilterConfig], bus: EventBus,
                 stats: UsageRepository, clock: Clock, discover=None, sources: SourceRepository | None = None) -> None:
        self._service, self._cfg, self._bus, self._stats, self._clock = service, prefilter_config, bus, stats, clock
        self._discover, self._sources = discover, sources

    async def submit(self, msg: IncomingMessage) -> None:
        day = self._clock.now().date()
        if self._discover is not None:
            try:
                await self._discover.execute(msg)  # до предфильтра: ссылки есть и в мусоре
            except Exception:
                logger.exception("Автопополнение по сообщению %s/%s не удалось", msg.source_id, msg.message_id)
        verdict = prefilter(msg.text, self._cfg())
        passed = verdict == "pass"
        if self._sources is not None:
            await self._sources.bump_counts(msg.source_id, read=1, passed=int(passed))
        if not passed:
            await self._stats.bump(day, read=1)
            return
        await self._stats.bump(day, read=1, passed_prefilter=1)
        finding, new = await self._service.cluster(msg)
        if not new and finding.status is FindingStatus.delivered:
            self._bus.publish(CopyAttached(finding.id))


class DeliverAccepted:
    """Каждая принятая находка — одна карточка (R1): claim до отправки, при сбое отправки — снять claim."""

    def __init__(self, repo: FindingRepository, notifier: Notifier, render: Render,
                 paused: Callable[[], Awaitable[bool]], stats: UsageRepository, clock: Clock,
                 plain: Callable[[str], str] | None = None, alerts: AlertSink | None = None) -> None:
        self._repo, self._notifier, self._render = repo, notifier, render
        self._paused, self._stats, self._clock = paused, stats, clock
        self._plain, self._alerts = plain, alerts

    async def _send(self, finding: Finding, html: str) -> int | None:
        """→ message_id; None — не отправлено (claim уже снят или находка failed)."""
        try:
            return await self._notifier.send(html)
        except DeliveryRejected as exc:
            logger.warning("Telegram отклонил карточку %s (%s), шлём простым текстом", finding.id, exc)
        except Exception:
            logger.exception("Не удалось отправить находку %s, вернём в очередь", finding.id)
            await self._repo.unclaim(finding.id)
            return None
        try:
            if self._plain is not None:
                return await self._notifier.send(self._plain(html), parse_mode=None)
            raise DeliveryRejected("нет запасного вида")
        except DeliveryRejected as exc:
            await self._repo.fail_delivery(finding.id)
            if self._alerts is not None:
                await self._alerts.notify(f"⚠️ Telegram не принял карточку находки {finding.id} ({exc}); "
                                          "она отмечена failed и видна в веб-панели.")
        except Exception:
            logger.exception("Не удалось отправить находку %s, вернём в очередь", finding.id)
            await self._repo.unclaim(finding.id)
        return None

    async def execute(self) -> int:
        if await self._paused():
            return 0
        sent = 0
        for finding in await self._repo.accepted(DELIVER_BATCH):
            if not await self._repo.claim(finding.id, self._clock.now()):
                continue
            copies = await self._repo.copies(finding.id)
            message_id = await self._send(finding, self._render(finding, copies))
            if message_id is None:
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
