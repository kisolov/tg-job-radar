import logging

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
