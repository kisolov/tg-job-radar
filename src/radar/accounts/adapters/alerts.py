import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from radar.accounts.ports import AlertSink
from radar.shared.clock import Clock, SystemClock

logger = logging.getLogger(__name__)


class LogAlertSink:
    async def notify(self, text: str) -> None:
        logger.warning("ALERT: %s", text)


class RecordingAlertSink:
    """Фейк для тестов."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def notify(self, text: str) -> None:
        self.sent.append(text)


@dataclass(frozen=True)
class Alert:
    at: datetime
    text: str


class AlertLog:
    """Последние алерты в памяти процесса — для веб-панели (особенно в режиме без бота). Рестарт их стирает."""

    def __init__(self, clock: Clock | None = None, size: int = 50) -> None:
        self._clock = clock or SystemClock()
        self._items: deque[Alert] = deque(maxlen=size)

    def record(self, text: str) -> None:
        self._items.append(Alert(self._clock.now(), text))

    def recent(self) -> list[Alert]:
        return list(reversed(self._items))


class TeeAlertSink:
    """Алерт — в журнал панели и, если есть бот, владельцу в Telegram."""

    def __init__(self, log: AlertLog, inner: AlertSink | None = None) -> None:
        self._log, self._inner = log, inner

    async def notify(self, text: str) -> None:
        logger.warning("ALERT: %s", text)
        self._log.record(text)
        if self._inner is not None:
            await self._inner.notify(text)
