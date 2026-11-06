import asyncio
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CopyAttached:
    """У уже отправленной находки появилась новая копия — карточку надо отредактировать (R9)."""

    finding_id: int


class EventBus(Protocol):
    def publish(self, event: CopyAttached) -> None: ...


class InProcessEventBus:
    """Очередь в памяти процесса. Потеря при рестарте допустима: R9 eventual, следующая копия догонит список."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[CopyAttached] = asyncio.Queue()

    def publish(self, event: CopyAttached) -> None:
        self.queue.put_nowait(event)
