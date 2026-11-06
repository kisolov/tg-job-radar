"""Что считать одной находкой: нормализация → отпечаток/шинглы → кластер (R1 держит репозиторий)."""
from radar.findings.entities import Finding
from radar.findings.ports import FindingRepository
from radar.findings.similarity import fingerprint, normalize, shingles
from radar.ingest.ports import IncomingMessage
from radar.shared.clock import Clock


class FindingService:
    def __init__(self, repo: FindingRepository, clock: Clock, window_days: int, threshold: float) -> None:
        self._repo, self._clock = repo, clock
        self._window_days, self._threshold = window_days, threshold

    async def cluster(self, msg: IncomingMessage) -> tuple[Finding, bool]:
        norm = normalize(msg.text)
        return await self._repo.cluster(msg, norm, fingerprint(norm), shingles(norm), self._window_days,
                                        self._threshold, self._clock.now())
